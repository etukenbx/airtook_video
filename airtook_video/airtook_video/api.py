# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import random
import struct
import time
import zlib

import frappe
from frappe import _
from frappe.utils import now_datetime, get_url

SESSION_DTYPE = "AirTook Video Session"
DEFAULT_DURATION_MINUTES = 30
TOKEN_EXPIRE_SECONDS = 7200  # 2 hours

ROLE_PUBLISHER   = 1
ROLE_SUBSCRIBER  = 2

EXTENSION_DISCOUNT_PCT = 20


# ─── Agora credentials ───────────────────────────────────────────────────────

def _get_agora_credentials():
    app_id = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
        frappe.conf.get("agora_app_id") or ""
    ).strip()
    certificate = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_certificate") or
        frappe.conf.get("agora_app_certificate") or ""
    ).strip()
    if not app_id or not certificate:
        frappe.throw(
            _("Agora credentials not configured. Set agora_app_id and agora_app_certificate."),
            frappe.ValidationError,
        )
    return app_id, certificate


# ─── Token generation ────────────────────────────────────────────────────────

def _generate_uid():
    return random.randint(100000, 999999)


def _generate_agora_token_manual(app_id, app_certificate, channel_name, uid, role, expire_ts):
    """
    Agora AccessToken (DynamicKey5) HMAC-SHA256 implementation.
    Matches the reference implementation at github.com/AgoraIO/Tools/DynamicKey/AgoraDynamicKey.
    """
    ts   = int(time.time())
    salt = random.randint(1, 0x7FFFFFFF)
    uid_str = str(uid)

    privileges = {1: expire_ts}  # join channel
    if role == ROLE_PUBLISHER:
        privileges[2] = expire_ts  # publish audio
        privileges[3] = expire_ts  # publish video
        privileges[4] = expire_ts  # publish data stream

    msg = struct.pack("<H", len(privileges))
    for k in sorted(privileges.keys()):
        msg += struct.pack("<HI", k, privileges[k])

    signing = (app_id + channel_name + uid_str).encode("utf-8") + msg
    signature = hmac.new(app_certificate.encode("utf-8"), signing, hashlib.sha256).digest()

    crc_chan = zlib.crc32(channel_name.encode("utf-8")) & 0xFFFFFFFF
    crc_uid  = zlib.crc32(uid_str.encode("utf-8"))      & 0xFFFFFFFF

    content = (
        struct.pack("<I", salt) +
        struct.pack("<I", ts) +
        struct.pack("<H", len(signature)) + signature +
        struct.pack("<I", crc_chan) +
        struct.pack("<I", crc_uid) +
        struct.pack("<H", len(msg)) + msg
    )
    return "006" + base64.b64encode(content).decode("utf-8")


def _generate_agora_token(app_id, app_certificate, channel_name, uid,
                          role=ROLE_PUBLISHER, expire_seconds=TOKEN_EXPIRE_SECONDS):
    expire_ts = int(time.time()) + expire_seconds
    try:
        from agora_token_builder import RtcTokenBuilder
        return RtcTokenBuilder.buildTokenWithUid(
            app_id, app_certificate, channel_name, uid, role, expire_ts
        )
    except ImportError:
        pass
    except Exception:
        frappe.log_error(frappe.get_traceback(), "agora_token_builder failed — using manual fallback")
    return _generate_agora_token_manual(app_id, app_certificate, channel_name, uid, role, expire_ts)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _get_practitioner_user(practitioner_name):
    if not practitioner_name:
        return None
    return frappe.db.get_value("Healthcare Practitioner", practitioner_name, "user_id")


def _patient_user_from_patient(patient_name):
    if not patient_name:
        return None
    return frappe.db.get_value("Patient", patient_name, "user_id")


def _get_fee_per_minute(appointment_type, mode="Video"):
    PRICES = {
        "Priority Consultation 15min": 4499,
        "Priority Consultation 30min": 7499,
        "Priority Consultation 45min": 9999,
        "Priority Consultation 60min": 12499,
        "Scheduled Consultation 15min": 2999,
        "Scheduled Consultation 30min": 4999,
        "Scheduled Consultation 45min": 6499,
        "Scheduled Consultation 60min": 7999,
        "Quick Consultation": 7499,
        "General Consultation": 4999,
    }
    base    = PRICES.get(appointment_type or "", 4999)
    minutes = 30
    for suffix in ["15min", "30min", "45min", "60min"]:
        if (appointment_type or "").endswith(suffix):
            minutes = int(suffix.replace("min", ""))
            break
    return round(base / minutes, 2)


def _build_join_url(session_name, channel_name, uid, token, role, appointment_name, duration_minutes):
    from urllib.parse import urlencode
    params = urlencode({
        "ch":   channel_name,
        "uid":  uid,
        "tok":  token,
        "role": role,
        "apt":  appointment_name or "",
        "dur":  duration_minutes,
    })
    return f"{get_url()}/video/{session_name}?{params}"


def _build_session_response(doc, doctor_token=None, patient_token=None):
    app_id = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
        frappe.conf.get("agora_app_id") or ""
    )
    if not doctor_token or not patient_token:
        try:
            app_cert = (
                frappe.db.get_single_value("AirTook Configuration", "agora_app_certificate") or
                frappe.conf.get("agora_app_certificate") or ""
            )
            if app_cert:
                doctor_token  = _generate_agora_token(app_id, app_cert, doc.channel_name, doc.doctor_uid, ROLE_PUBLISHER)
                patient_token = _generate_agora_token(app_id, app_cert, doc.channel_name, doc.patient_uid, ROLE_PUBLISHER)
        except Exception:
            doctor_token  = doctor_token  or ""
            patient_token = patient_token or ""

    dur = int(doc.duration_minutes or DEFAULT_DURATION_MINUTES)
    doctor_join_url  = _build_join_url(doc.name, doc.channel_name, doc.doctor_uid,  doctor_token,  "doctor",  doc.appointment, dur)
    patient_join_url = _build_join_url(doc.name, doc.channel_name, doc.patient_uid, patient_token, "patient", doc.appointment, dur)

    return {
        "session_id":        doc.name,
        "appointment":       doc.appointment or "",
        "channel_name":      doc.channel_name,
        "app_id":            app_id,
        "doctor_uid":        doc.doctor_uid,
        "patient_uid":       doc.patient_uid,
        "doctor_token":      doctor_token  or "",
        "patient_token":     patient_token or "",
        "doctor_join_url":   doctor_join_url,
        "patient_join_url":  patient_join_url,
        "video_join_url":    patient_join_url,   # backwards-compat alias for callers
        "status":            doc.status,
        "duration_minutes":  dur,
        "extensions_count":  int(getattr(doc, "extensions_count", 0) or 0),
    }


# ─── create_session ──────────────────────────────────────────────────────────

@frappe.whitelist(methods=["GET", "POST"])
def create_session(patient_appointment=None, appointment_name=None,
                   duration_minutes=None, consultation_mode="Video", **kwargs):
    _require_login()

    appt_name = appointment_name or patient_appointment
    if not appt_name:
        frappe.throw(_("appointment_name is required"), frappe.ValidationError)

    # Reuse an existing non-completed session for this appointment
    existing = frappe.db.get_value(
        SESSION_DTYPE,
        {"appointment": appt_name, "status": ["not in", ["completed", "expired"]]},
        "name",
    )
    if existing:
        doc = frappe.get_doc(SESSION_DTYPE, existing, ignore_permissions=True)
        return _build_session_response(doc)

    appt = frappe.get_doc("Patient Appointment", appt_name)
    patient      = getattr(appt, "patient", None)
    practitioner = getattr(appt, "practitioner", None)
    appt_type    = getattr(appt, "appointment_type", None)

    if not duration_minutes:
        for mins in [15, 30, 45, 60]:
            if (appt_type or "").endswith(f"{mins}min"):
                duration_minutes = mins
                break
    duration_minutes = int(duration_minutes or DEFAULT_DURATION_MINUTES)

    patient_user = _patient_user_from_patient(patient) if patient else frappe.session.user

    app_id, app_certificate = _get_agora_credentials()

    # Sanitise channel name: lowercase alphanumerics + hyphens, max 64 chars
    raw_channel = f"at-{appt_name.lower()}-{random.randint(1000, 9999)}"
    channel_name = "".join(c if c.isalnum() or c == "-" else "-" for c in raw_channel)[:64]

    doctor_uid  = _generate_uid()
    patient_uid = _generate_uid()

    doctor_token  = _generate_agora_token(app_id, app_certificate, channel_name, doctor_uid,  ROLE_PUBLISHER)
    patient_token = _generate_agora_token(app_id, app_certificate, channel_name, patient_uid, ROLE_PUBLISHER)

    doc = frappe.get_doc({
        "doctype":          SESSION_DTYPE,
        "appointment":      appt_name,
        "practitioner":     practitioner,
        "patient":          patient,
        "patient_user":     patient_user,
        "channel_name":     channel_name,
        "doctor_uid":       doctor_uid,
        "patient_uid":      patient_uid,
        "duration_minutes": duration_minutes,
        "status":           "scheduled",
        "created_at":       now_datetime(),
    })
    doc.insert(ignore_permissions=True)

    if frappe.db.has_column("Patient Appointment", "airtook_video_session"):
        frappe.db.set_value("Patient Appointment", appt_name, "airtook_video_session", doc.name)

    frappe.db.commit()
    return _build_session_response(doc, doctor_token=doctor_token, patient_token=patient_token)


# ─── get_session_status ──────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_session_status(session_id):
    if not session_id:
        frappe.throw("Missing session_id")
    row = frappe.db.get_value(
        SESSION_DTYPE, session_id,
        ["status", "started_at", "duration_minutes", "extensions_count",
         "appointment", "channel_name", "doctor_uid", "patient_uid"],
        as_dict=True,
    )
    if not row:
        frappe.throw("Session not found")
    return {
        "session_id":       session_id,
        "status":           row.status,
        "started_at":       str(row.started_at or ""),
        "duration_minutes": row.duration_minutes or DEFAULT_DURATION_MINUTES,
        "extensions_count": row.extensions_count or 0,
        "appointment":      row.appointment or "",
    }


# ─── start_session_timer ─────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def start_session_timer(session_id):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    if practitioner_user and practitioner_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if doc.status != "active":
        now = now_datetime()
        doc.db_set("status",     "active", update_modified=False)
        doc.db_set("started_at", now,      update_modified=False)
        frappe.db.commit()

    frappe.publish_realtime(
        event="video_session_started",
        message={"session_id": session_id, "started_at": str(doc.started_at or now_datetime())},
        room=f"video_{session_id}",
    )
    return {"session_id": session_id, "status": "active", "started_at": str(doc.started_at or "")}


# ─── end_session ─────────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def end_session(session_id, transcript=None):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    if not practitioner_user or practitioner_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Row-lock to prevent double end_session (concurrent calls from doctor + patient)
    frappe.db.sql(
        "SELECT name FROM `tabAirTook Video Session` WHERE name = %s FOR UPDATE",
        session_id,
    )

    if frappe.db.get_value(SESSION_DTYPE, session_id, "status") != "completed":
        now = now_datetime()
        doc.db_set("status",   "completed", update_modified=False)
        doc.db_set("ended_at", now,         update_modified=False)
        if transcript:
            doc.db_set("transcript", transcript, update_modified=False)
        doc.save(ignore_permissions=True)

        if doc.get("appointment"):
            frappe.db.set_value("Patient Appointment", doc.appointment, "status", "Closed")
        frappe.db.commit()

        # ── Credit doctor earnings ──────────────────────────────────────────
        if doc.get("practitioner") and doc.get("appointment"):
            try:
                from frappe.utils import flt as _flt
                appt = doc.appointment
                paid_amount = _flt(
                    frappe.db.get_value("Patient Appointment", appt, "paid_amount") or 0
                )
                if paid_amount <= 0:
                    paid_amount = _flt(
                        frappe.db.get_value("Patient Appointment", appt, "custom_payment_amount") or 0
                    )
                if paid_amount > 0:
                    commission_pct = 20.0
                    try:
                        cp = frappe.db.get_value(
                            "AirTook Setting", "platform_commission_pct", "setting_value"
                        )
                        if cp:
                            commission_pct = _flt(cp)
                    except Exception:
                        pass
                    doctor_pct = 100.0 - commission_pct
                    doctor_cut = round(paid_amount * doctor_pct / 100, 2)
                    if doctor_cut > 0:
                        frappe.db.sql(
                            "SELECT name FROM `tabHealthcare Practitioner` WHERE name = %s FOR UPDATE",
                            doc.practitioner,
                        )
                        current_earn = _flt(
                            frappe.db.get_value(
                                "Healthcare Practitioner", doc.practitioner,
                                "custom_earnings_balance"
                            ) or 0
                        )
                        frappe.db.set_value(
                            "Healthcare Practitioner", doc.practitioner,
                            "custom_earnings_balance", current_earn + doctor_cut,
                            update_modified=False,
                        )
                        frappe.db.commit()
                        frappe.logger().info(
                            f"end_session: credited ₦{doctor_cut} to {doc.practitioner} "
                            f"for session {doc.name}"
                        )
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"end_session: earnings credit failed for {doc.name}",
                )

        # ── Save transcript to Patient Encounter ─────────────────────────────
        if transcript and doc.get("appointment"):
            try:
                enc_name = frappe.db.get_value(
                    "Patient Encounter", {"appointment": doc.appointment}, "name"
                )
                if enc_name and frappe.db.has_column("Patient Encounter", "custom_transcript"):
                    frappe.db.set_value(
                        "Patient Encounter", enc_name,
                        "custom_transcript", transcript, update_modified=False,
                    )
                    frappe.db.commit()
            except Exception:
                pass

        # ── Enqueue AI consultation summary ──────────────────────────────────
        if doc.get("appointment"):
            try:
                import frappe.utils.background_jobs as _bj
                _bj.enqueue(
                    "airtook_core.api_dashboard.generate_consultation_summary",
                    appointment_name=doc.appointment,
                    queue="short",
                    timeout=60,
                )
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"end_session: failed to enqueue summary for {doc.name}",
                )

    return {"session_id": doc.name, "status": "completed"}


# ─── extend_session ─────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def extend_session(session_id, extend_minutes):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")

    extend_minutes = int(extend_minutes or 0)
    if extend_minutes not in (15, 30):
        frappe.throw("Extension must be 15 or 30 minutes", frappe.ValidationError)

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)

    if doc.patient_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if doc.status != "active":
        frappe.throw("Session is not active")

    appt_type = None
    if doc.get("appointment"):
        appt_type = frappe.db.get_value("Patient Appointment", doc.appointment, "appointment_type")

    per_min   = _get_fee_per_minute(appt_type)
    gross_fee = round(per_min * extend_minutes, 2)
    discount  = round(gross_fee * EXTENSION_DISCOUNT_PCT / 100, 2)
    ext_fee   = round(gross_fee - discount, 2)

    patient_name = doc.patient or frappe.db.get_value(
        "Patient", {"user_id": frappe.session.user}, "name"
    )
    if not patient_name:
        frappe.throw("Patient record not found")

    from frappe.utils import flt
    wallet_balance = flt(frappe.db.get_value("Patient", patient_name, "custom_wallet_balance") or 0)
    if wallet_balance < ext_fee:
        return {
            "ok": False, "error": "insufficient_balance",
            "required": ext_fee, "balance": wallet_balance,
        }

    try:
        frappe.db.sql("SELECT name FROM `tabPatient` WHERE name = %s FOR UPDATE", patient_name)
        current_bal = flt(frappe.db.get_value("Patient", patient_name, "custom_wallet_balance") or 0)
        if current_bal < ext_fee:
            return {"ok": False, "error": "insufficient_balance", "required": ext_fee, "balance": current_bal}
        new_bal = current_bal - ext_fee
        frappe.db.set_value("Patient", patient_name, "custom_wallet_balance", new_bal, update_modified=False)
        frappe.db.commit()
        try:
            frappe.get_doc({
                "doctype": "AirTook Wallet Transaction",
                "patient": patient_name,
                "transaction_type": "Deduction",
                "amount": ext_fee,
                "balance_before": current_bal,
                "balance_after": new_bal,
                "reference_doctype": SESSION_DTYPE,
                "reference_name": session_id,
                "notes": f"Session extension {extend_minutes}min (20% discount)",
                "created_by_user": frappe.session.user,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass  # transaction log failure is non-fatal
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "extend_session wallet deduction failed")
        frappe.throw(f"Payment failed: {str(e)}")

    new_duration  = int(doc.duration_minutes or DEFAULT_DURATION_MINUTES) + extend_minutes
    new_ext_count = int(getattr(doc, "extensions_count", 0) or 0) + 1
    doc.db_set("duration_minutes",  new_duration,  update_modified=False)
    doc.db_set("extensions_count",  new_ext_count, update_modified=False)
    frappe.db.commit()

    return {
        "ok": True,
        "new_duration_minutes": new_duration,
        "extension_fee":        ext_fee,
        "discount_applied":     discount,
        "extensions_count":     new_ext_count,
    }


# ─── submit_rating ───────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def submit_rating(session_id, rating, comment=None, rated_by_role=None):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        frappe.throw("Rating must be an integer", frappe.ValidationError)
    if not (1 <= rating <= 5):
        frappe.throw("Rating must be between 1 and 5", frappe.ValidationError)

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    current_user      = frappe.session.user
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    is_practitioner   = bool(practitioner_user and practitioner_user == current_user)
    is_patient        = bool(doc.patient_user and doc.patient_user == current_user)

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
