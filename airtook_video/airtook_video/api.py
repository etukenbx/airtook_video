# -*- coding: utf-8 -*-
import secrets
import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime, get_url

from .daily import (
    daily_create_room,
    daily_create_meeting_token,
    daily_get_room,
)

SESSION_DTYPE = "Video Consultation Session"

JOIN_KEY_TTL_MINUTES = 60
JOIN_EARLY_MINUTES   = 10
SESSION_EXPIRE_AFTER_MINUTES = 60
DEFAULT_APPT_DURATION_MINUTES = 30

# Extension pricing: 20% discount applied to per-minute rate
EXTENSION_DISCOUNT_PCT = 20


# ─── helpers ────────────────────────────────────────────────────────────────

def _generate_join_key():
    return secrets.token_urlsafe(24)

def _is_expired(dt):
    return (not dt) or (now_datetime() > dt)

def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)

def _room_name(prefix="airtook"):
    return f"{prefix}-{secrets.token_urlsafe(8).lower()}"

def _get_user_display_name(user):
    try:
        from frappe.utils import get_fullname
        name = get_fullname(user)
        return name or user
    except Exception:
        first = frappe.db.get_value("User", user, "first_name") or ""
        last  = frappe.db.get_value("User", user, "last_name")  or ""
        return f"{first} {last}".strip() or user

def _require_valid_user(user_id):
    if not user_id or not frappe.db.exists("User", user_id):
        frappe.throw(_("Invalid patient user"), frappe.ValidationError)

def _resolve_department(dept):
    if not dept:
        return None
    dept = dept.strip()
    if frappe.db.exists("Medical Department", dept):
        return dept
    rows = frappe.get_all("Medical Department", fields=["name"], limit_page_length=300)
    matches = [r["name"] for r in rows if (r.get("name") or "").startswith(dept)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        frappe.throw(f"Ambiguous department: '{dept}'", frappe.ValidationError)
    frappe.throw(f"Unknown department: '{dept}'", frappe.ValidationError)

def _pick_practitioner(dept):
    if not dept:
        return None
    rows = frappe.get_all(
        "Healthcare Practitioner",
        filters={"status": "Active", "department": dept},
        fields=["name", "user_id"],
        order_by="modified desc",
        limit_page_length=50,
    )
    for r in rows:
        if r.get("user_id"):
            return r["name"]
    return None

def _get_practitioner_user(practitioner_name):
    if not practitioner_name:
        return None
    return frappe.db.get_value("Healthcare Practitioner", practitioner_name, "user_id")

def _patient_user_from_patient(patient_name):
    if not patient_name:
        return None
    return frappe.db.get_value("Patient", patient_name, "user_id")

def _get_fee_per_minute(appointment_type, mode):
    """Return per-minute fee in NGN based on appointment type."""
    PRICES = {
        "Priority Consultation 15min":  4499,
        "Priority Consultation 30min":  7499,
        "Priority Consultation 45min":  9999,
        "Priority Consultation 60min":  12499,
        "Scheduled Consultation 15min": 2999,
        "Scheduled Consultation 30min": 4999,
        "Scheduled Consultation 45min": 6499,
        "Scheduled Consultation 60min": 7999,
        "Quick Consultation":           7499,
        "General Consultation":         4999,
    }
    base = PRICES.get(appointment_type or "", 4999)
    minutes = 30
    for suffix in ["15min", "30min", "45min", "60min"]:
        if (appointment_type or "").endswith(suffix):
            minutes = int(suffix.replace("min", ""))
            break
    # Return per-minute rate
    return round(base / minutes, 2)


# ─── create_session ─────────────────────────────────────────────────────────

@frappe.whitelist(methods=["GET", "POST"])
def create_session(patient_appointment=None, department=None, practitioner=None,
                   patient_user=None, allow_magic_link=1, consultation_mode="Video",
                   duration_minutes=None, **kwargs):
    _require_login()

    session_type = "Scheduled" if patient_appointment else "Quick Consult"
    patient = None
    dept = department
    appt_type = None

    if patient_appointment:
        appt = frappe.get_doc("Patient Appointment", patient_appointment)

        # Reuse existing session if already linked
        existing_session = getattr(appt, "airtook_video_session", None)
        if existing_session and frappe.db.exists(SESSION_DTYPE, existing_session):
            existing = frappe.get_doc(SESSION_DTYPE, existing_session, ignore_permissions=True)
            payload = _session_payload(existing)
            return payload

        patient   = getattr(appt, "patient", None)
        dept      = getattr(appt, "department", None) or dept or "General Practice"
        practitioner = practitioner or getattr(appt, "practitioner", None)
        appt_type = getattr(appt, "appointment_type", None)
        # Read duration from appointment type string if not explicitly passed
        if not duration_minutes:
            for mins in [15, 30, 45, 60]:
                if (appt_type or "").endswith(f"{mins}min"):
                    duration_minutes = mins
                    break

    dept = _resolve_department(dept)
    if not dept:
        frappe.throw("Department is required", frappe.ValidationError)

    prac = practitioner or _pick_practitioner(dept)

    appt_patient_user = _patient_user_from_patient(patient) if patient else None
    final_patient_user = appt_patient_user or patient_user or frappe.session.user
    _require_valid_user(final_patient_user)

    booked_by  = frappe.session.user
    allow_magic = 1 if str(allow_magic_link) in ("1", "true", "True", "yes", "on") else 0
    mode = consultation_mode if consultation_mode in ("Video", "Audio") else "Video"
    dur  = int(duration_minutes or DEFAULT_APPT_DURATION_MINUTES)

    # Daily.co room — audio-only uses start_video_off
    room_name = _room_name("airtook")
    room_props = {}
    if mode == "Audio":
        room_props["start_video_off"] = True
    room = daily_create_room(room_name, extra_properties=room_props)

    daily_room_name = room.get("name") or room_name
    room_url = room.get("url")

    doc = frappe.get_doc({
        "doctype": SESSION_DTYPE,
        "session_type": session_type,
        "status": "Waiting",
        "appointment": patient_appointment,
        "patient": patient,
        "patient_user": final_patient_user,
        "booked_by": booked_by,
        "allow_magic_link": allow_magic,
        "practitioner": prac,
        "department": dept,
        "daily_room_name": daily_room_name,
        "daily_room_url": room_url,
        "consultation_mode": mode,
        "duration_minutes": dur,
        "participant_count": 0,
        "extensions_count": 0,
    })
    doc.insert(ignore_permissions=True)

    # Link back to appointment
    if patient_appointment and frappe.db.has_column("Patient Appointment", "airtook_video_session"):
        frappe.db.set_value("Patient Appointment", patient_appointment,
                            "airtook_video_session", doc.name)

    # Generate magic link if enabled
    join_key = None
    expires_at = None
    if allow_magic:
        join_key  = _generate_join_key()
        expires_at = add_to_date(now_datetime(), minutes=JOIN_KEY_TTL_MINUTES)
        doc.db_set("patient_join_key", join_key, update_modified=False)
        doc.db_set("patient_join_key_expires_at", expires_at, update_modified=False)

    frappe.db.commit()

    payload = _session_payload(doc)
    if join_key:
        payload["patient_join_url"] = f"{get_url()}/video/{doc.name}?k={join_key}"
        payload["patient_join_expires_at"] = str(expires_at)
    return payload


def _session_payload(doc):
    return {
        "session_id": doc.name,
        "session_type": doc.session_type,
        "status": doc.status,
        "department": doc.department,
        "practitioner": doc.practitioner,
        "room_name": doc.daily_room_name,
        "room_url": doc.daily_room_url,
        "patient_user": doc.patient_user,
        "booked_by": doc.booked_by,
        "allow_magic_link": doc.allow_magic_link,
        "consultation_mode": getattr(doc, "consultation_mode", "Video") or "Video",
        "duration_minutes": getattr(doc, "duration_minutes", DEFAULT_APPT_DURATION_MINUTES) or DEFAULT_APPT_DURATION_MINUTES,
        "extensions_count": getattr(doc, "extensions_count", 0) or 0,
    }


# ─── get_join_info ───────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_join_info(session_id, k=None):
    if not session_id:
        frappe.throw("Missing session id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)

    if not doc.daily_room_name:
        frappe.throw("Session has no Daily room assigned")
    if not doc.get("patient_user"):
        frappe.throw("Session is not linked to a patient account")

    current_user     = frappe.session.user
    is_guest         = current_user == "Guest"
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    is_owner         = (not is_guest and practitioner_user and practitioner_user == current_user)

    # Determine role + display name
    if is_owner:
        role         = "practitioner"
        display_name = _get_user_display_name(current_user)
        if display_name and not display_name.lower().startswith("dr"):
            display_name = f"Dr. {display_name}"
        token_user_id = current_user
    else:
        role = "patient"
        if is_guest:
            if not k:
                frappe.throw("Login required (missing join key)")
            if not doc.get("allow_magic_link"):
                frappe.throw("Magic link access is disabled for this consultation")
            if not doc.patient_join_key or not doc.patient_join_key_expires_at:
                frappe.throw("Join link is not enabled")
            if k != doc.patient_join_key:
                frappe.throw("Invalid join key")
            if _is_expired(doc.patient_join_key_expires_at):
                frappe.throw("Join link expired")
            doc.db_set("patient_join_key", None, update_modified=False)
            doc.db_set("patient_join_key_expires_at", None, update_modified=False)
            display_name  = _get_user_display_name(doc.patient_user)
            token_user_id = doc.patient_user
        else:
            if doc.patient:
                patient_user_id = _patient_user_from_patient(doc.patient)
                if patient_user_id and patient_user_id != current_user:
                    frappe.throw("Not permitted")
            if doc.patient_user and doc.patient_user != current_user:
                frappe.throw("Not permitted")
            display_name  = _get_user_display_name(current_user)
            token_user_id = current_user

    # Access window check
    now = now_datetime()
    open_from, close_at, kind = _compute_access_window(doc)
    if kind == "scheduled" and open_from and now < open_from:
        frappe.throw("Please join within 10 minutes of your appointment time.")
    if close_at and now > close_at:
        if doc.status != "Ended":
            doc.status = "Ended"
            if not doc.get("ended_at"):
                doc.db_set("ended_at", now, update_modified=False)
            doc.save(ignore_permissions=True)
        frappe.throw("This session has expired. Please book a new appointment.")
    if doc.status == "Ended" and doc.get("ended_at"):
        hard_close = add_to_date(doc.ended_at, minutes=SESSION_EXPIRE_AFTER_MINUTES)
        if now > hard_close:
            frappe.throw("This session has expired. Please book a new appointment.")

    # Ensure Daily room still exists
    room_url = None
    try:
        room = daily_get_room(doc.daily_room_name)
        room_url = (room or {}).get("url")
    except Exception:
        pass

    if not room_url:
        if doc.status == "Ended":
            frappe.throw("This consultation session has ended.")
        new_room_name = _room_name("airtook")
        mode = getattr(doc, "consultation_mode", "Video") or "Video"
        extra = {"start_video_off": True} if mode == "Audio" else {}
        new_room = daily_create_room(new_room_name, extra_properties=extra)
        doc.daily_room_name = new_room.get("name") or new_room_name
        doc.daily_room_url  = new_room.get("url")
        doc.save(ignore_permissions=True)
        room_url = doc.daily_room_url

    # Create Daily token
    token = daily_create_meeting_token(
        room_name=doc.daily_room_name,
        is_owner=(role == "practitioner"),
        user_id=token_user_id,
    )

    # Increment participant count (used for both-parties detection)
    current_count = int(getattr(doc, "participant_count", 0) or 0) + 1
    doc.db_set("participant_count", current_count, update_modified=False)

    # Mark session Waiting → Active when BOTH parties have joined
    if doc.status in ("Draft", "Scheduled", "Waiting"):
        doc.status = "Waiting"
        if not doc.get("started_at"):
            doc.db_set("started_at", now, update_modified=False)
        doc.db_set("status", "Waiting", update_modified=False)
        doc.save(ignore_permissions=True)

    # both_joined_at is set by participant_joined API when count reaches 2
    frappe.db.commit()

    mode = getattr(doc, "consultation_mode", "Video") or "Video"
    dur  = int(getattr(doc, "duration_minutes", DEFAULT_APPT_DURATION_MINUTES) or DEFAULT_APPT_DURATION_MINUTES)

    return {
        "session_id":         doc.name,
        "room_name":          doc.daily_room_name,
        "room_url":           room_url,
        "token":              token,
        "role":               role,
        "practitioner":       doc.practitioner,
        "display_name":       display_name,
        "patient_user":       doc.patient_user,
        "consultation_mode":  mode,
        "duration_minutes":   dur,
        "extensions_count":   int(getattr(doc, "extensions_count", 0) or 0),
        "status":             doc.status,
        "both_joined_at":     str(doc.get("both_joined_at") or ""),
    }


# ─── participant_joined ──────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["POST"])
def participant_joined(session_id):
    """
    Called by the frontend when Daily.co fires 'participant-joined'.
    When participant count reaches 2, marks both_joined_at and status=Active.
    Returns the server timestamp so both clients can sync the timer.
    """
    if not session_id:
        frappe.throw("Missing session id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    count = int(getattr(doc, "participant_count", 0) or 0)

    # Count the new participant
    count += 1
    doc.db_set("participant_count", count, update_modified=False)

    both_joined_at = doc.get("both_joined_at")
    if count >= 2 and not both_joined_at:
        both_joined_at = now_datetime()
        doc.db_set("both_joined_at", both_joined_at, update_modified=False)
        doc.db_set("status", "Active", update_modified=False)

    frappe.db.commit()

    return {
        "participant_count": count,
        "both_joined_at":    str(both_joined_at or ""),
        "status":            "Active" if count >= 2 else "Waiting",
    }


# ─── participant_left ────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["POST"])
def participant_left(session_id):
    """Called when a participant leaves — decrements count."""
    if not session_id:
        return
    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    count = max(0, int(getattr(doc, "participant_count", 0) or 0) - 1)
    doc.db_set("participant_count", count, update_modified=False)
    frappe.db.commit()
    return {"participant_count": count}


# ─── extend_session ─────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def extend_session(session_id, extend_minutes):
    """
    Patient-initiated session extension with 20% discount.
    Deducts from patient wallet immediately.
    """
    _require_login()

    if not session_id:
        frappe.throw("Missing session id")

    extend_minutes = int(extend_minutes or 0)
    if extend_minutes not in (15, 30):
        frappe.throw("Extension must be 15 or 30 minutes", frappe.ValidationError)

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)

    # Only the patient on this session may extend
    if doc.patient_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if doc.status != "Active":
        frappe.throw("Session is not active")

    # Calculate discounted extension fee
    appt_type = None
    if doc.get("appointment"):
        appt_type = frappe.db.get_value("Patient Appointment", doc.appointment, "appointment_type")

    per_min = _get_fee_per_minute(appt_type, getattr(doc, "consultation_mode", "Video"))
    gross_fee = round(per_min * extend_minutes, 2)
    discount  = round(gross_fee * EXTENSION_DISCOUNT_PCT / 100, 2)
    ext_fee   = round(gross_fee - discount, 2)

    # Check wallet balance
    patient_name = doc.patient or frappe.db.get_value("Patient", {"user_id": frappe.session.user}, "name")
    if not patient_name:
        frappe.throw("Patient record not found")

    wallet_balance = frappe.db.get_value("AirTook Wallet", {"patient": patient_name}, "balance") or 0
    if float(wallet_balance) < ext_fee:
        return {
            "ok": False,
            "error": "insufficient_balance",
            "required": ext_fee,
            "balance": float(wallet_balance),
        }

    # Deduct from wallet using the existing api_pay pattern
    try:
        import airtook_core.airtook_core.api_pay as api_pay
        api_pay.deduct_from_wallet(
            patient=patient_name,
            amount=ext_fee,
            description=f"Session extension {extend_minutes}min (20% off)",
            reference_doctype="Video Consultation Session",
            reference_name=session_id,
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "extend_session wallet deduction failed")
        frappe.throw(f"Payment failed: {str(e)}")

    # Update session duration
    new_duration = int(getattr(doc, "duration_minutes", DEFAULT_APPT_DURATION_MINUTES) or DEFAULT_APPT_DURATION_MINUTES) + extend_minutes
    new_ext_count = int(getattr(doc, "extensions_count", 0) or 0) + 1
    doc.db_set("duration_minutes", new_duration, update_modified=False)
    doc.db_set("extensions_count", new_ext_count, update_modified=False)
    frappe.db.commit()

    return {
        "ok": True,
        "new_duration_minutes": new_duration,
        "extension_fee": ext_fee,
        "discount_applied": discount,
        "extensions_count": new_ext_count,
    }


# ─── get_session_status ─────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_session_status(session_id):
    if not session_id:
        frappe.throw("Missing session id")
    row = frappe.db.get_value(SESSION_DTYPE, session_id,
        ["status", "participant_count", "both_joined_at", "duration_minutes", "extensions_count"],
        as_dict=True)
    if not row:
        frappe.throw("Session not found")
    return {
        "session_id":        session_id,
        "status":            row.status,
        "participant_count": row.participant_count or 0,
        "both_joined_at":    str(row.both_joined_at or ""),
        "duration_minutes":  row.duration_minutes or DEFAULT_APPT_DURATION_MINUTES,
        "extensions_count":  row.extensions_count or 0,
    }


# ─── end_session ─────────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def end_session(session_id):
    _require_login()
    if not session_id:
        frappe.throw("Missing session id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    if not practitioner_user or practitioner_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if doc.status != "Ended":
        doc.status = "Ended"
        doc.db_set("ended_at", now_datetime(), update_modified=False)
        doc.db_set("status", "Ended", update_modified=False)
        doc.db_set("participant_count", 0, update_modified=False)
        doc.save(ignore_permissions=True)
        # Update linked appointment
        if doc.get("appointment"):
            frappe.db.set_value("Patient Appointment", doc.appointment, "status", "Checked Out")
        frappe.db.commit()

    return {"session_id": doc.name, "status": "Ended"}


# ─── submit_rating ───────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def submit_rating(session_id, rating, comment=None, rated_by_role=None):
    _require_login()
    if not session_id:
        frappe.throw("Missing session id")
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        frappe.throw("Rating must be an integer", frappe.ValidationError)
    if not (1 <= rating <= 5):
        frappe.throw("Rating must be between 1 and 5", frappe.ValidationError)

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    current_user = frappe.session.user
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    is_practitioner = bool(practitioner_user and practitioner_user == current_user)
    is_patient = bool(doc.patient_user and doc.patient_user == current_user)

    if not is_practitioner and not is_patient:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if is_patient and doc.practitioner:
        try:
            import importlib
            core_api = importlib.import_module("airtook_core.api")
            core_api.submit_doctor_rating(
                doctor=doc.practitioner, rating=rating,
                patient_user=current_user, session=session_id,
                comment=comment or "", source="Video Call",
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "submit_rating failed")

    if is_practitioner:
        if frappe.db.has_column(SESSION_DTYPE, "practitioner_rating"):
            doc.db_set("practitioner_rating", rating, update_modified=False)
        if comment and frappe.db.has_column(SESSION_DTYPE, "practitioner_rating_comment"):
            doc.db_set("practitioner_rating_comment", comment, update_modified=False)
        frappe.db.commit()

    return {"session_id": session_id, "rating": rating}


# ─── access window helpers ───────────────────────────────────────────────────

def _get_appt_datetime_and_duration(patient_appointment):
    appt = frappe.get_doc("Patient Appointment", patient_appointment)
    start_date = getattr(appt, "appointment_date", None)
    start_time = getattr(appt, "appointment_time", None)
    duration   = getattr(appt, "duration", None) or DEFAULT_APPT_DURATION_MINUTES
    if not start_date or not start_time:
        return None, int(duration)
    start_dt = frappe.utils.get_datetime(f"{start_date} {start_time}")
    return start_dt, int(duration)

def _compute_access_window(doc):
    now = now_datetime()
    if getattr(doc, "appointment", None):
        start_dt, duration = _get_appt_datetime_and_duration(doc.appointment)
        if start_dt:
            open_from = add_to_date(start_dt, minutes=-JOIN_EARLY_MINUTES)
            close_at  = add_to_date(start_dt, minutes=(duration + SESSION_EXPIRE_AFTER_MINUTES))
            return open_from, close_at, "scheduled"
    if getattr(doc, "ended_at", None):
        open_from = add_to_date(doc.ended_at, minutes=-10000)
        close_at  = add_to_date(doc.ended_at, minutes=SESSION_EXPIRE_AFTER_MINUTES)
        return open_from, close_at, "quick"
    return add_to_date(now, minutes=-10000), None, "quick"


# ─── quick_consult ───────────────────────────────────────────────────────────

@frappe.whitelist(methods=["GET", "POST"])
def quick_consult(department=None, consultation_mode="Video", duration_minutes=30):
    _require_login()
    return create_session(
        patient_appointment=None,
        department=department,
        practitioner=None,
        patient_user=None,
        allow_magic_link=1,
        consultation_mode=consultation_mode,
        duration_minutes=duration_minutes,
    )
