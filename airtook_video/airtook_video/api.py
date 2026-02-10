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

# Elderly-friendly magic link TTL (minutes)
JOIN_KEY_TTL_MINUTES = 60


# -------------------------
# Helpers
# -------------------------
def _generate_join_key() -> str:
    return secrets.token_urlsafe(24)


def _is_expired(dt) -> bool:
    return (not dt) or (now_datetime() > dt)


def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _room_name(prefix="airtook"):
    return f"{prefix}-{secrets.token_urlsafe(8).lower()}"


def _get_user_display_name(user: str) -> str:
    # Uses Frappe's built-in display name formatting when possible
    try:
        from frappe.utils import get_fullname
        name = get_fullname(user)
        return name or user
    except Exception:
        first = frappe.db.get_value("User", user, "first_name")
        last = frappe.db.get_value("User", user, "last_name")
        if first and last:
            return f"{first} {last}"
        return first or user


def _require_valid_user(user_id: str):
    if not user_id or not frappe.db.exists("User", user_id):
        frappe.throw(_("Invalid patient user"), frappe.ValidationError)


# -------------------------
# Department resolution (emoji-safe)
# -------------------------
def _resolve_department(dept: str | None) -> str | None:
    if not dept:
        return None

    dept = dept.strip()

    if frappe.db.exists("Medical Department", dept):
        return dept

    rows = frappe.get_all(
        "Medical Department",
        fields=["name"],
        limit_page_length=300,
    )

    matches = [r["name"] for r in rows if (r.get("name") or "").startswith(dept)]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        frappe.throw(
            f"Ambiguous Medical Department: '{dept}'. Matches: {matches}.",
            frappe.ValidationError,
        )

    frappe.throw(
        f"Unknown Medical Department: '{dept}'.",
        frappe.ValidationError,
    )


# -------------------------
# Practitioner helpers
# -------------------------
def _pick_practitioner(dept: str | None):
    if not dept:
        return None

    rows = frappe.get_all(
        "Healthcare Practitioner",
        filters={
            "status": "Active",
            "department": dept,
        },
        fields=["name", "user_id"],
        order_by="modified desc",
        limit_page_length=50,
    )

    for r in rows:
        if r.get("user_id"):
            return r["name"]

    return None


def _get_practitioner_user(practitioner_name: str | None):
    if not practitioner_name:
        return None

    return frappe.db.get_value(
        "Healthcare Practitioner",
        practitioner_name,
        "user_id",
    )


def _patient_user_from_patient(patient_name: str | None):
    """Map Healthcare Patient -> User ID (if linked)."""
    if not patient_name:
        return None
    return frappe.db.get_value("Patient", patient_name, "user_id")


# -------------------------
# API: create session
# -------------------------
@frappe.whitelist(methods=["GET", "POST"])
def create_session(patient_appointment=None, department=None, practitioner=None, patient_user=None, allow_magic_link=1):
    """
    Creates a Video Consultation Session.

    Security rules:
    - Must be logged in to create any session.
    - Every session must be tied to a registered User via `patient_user`.
    - Magic link is optional and controlled by `allow_magic_link`.
    """
    _require_login()

    session_type = "Scheduled" if patient_appointment else "Quick Consult"

    patient = None
    dept = department

    # If scheduled via Patient Appointment, pull patient + dept + practitioner from it
    if patient_appointment:
        appt = frappe.get_doc("Patient Appointment", patient_appointment)
        patient = getattr(appt, "patient", None)
        dept = getattr(appt, "department", None) or dept
        practitioner = practitioner or getattr(appt, "practitioner", None)

    dept = _resolve_department(dept)
    if not dept:
        frappe.throw("Department is required", frappe.ValidationError)

    # Practitioner selection
    prac = practitioner or _pick_practitioner(dept)

    # -------------------------
    # Patient identity (MUST be a registered User)
    # Priority:
    # 1) If appointment has Patient linked to a User -> use it
    # 2) Else if caller provided patient_user -> use it (doctor booking for elderly)
    # 3) Else default to current logged-in user (patient booking self)
    # -------------------------
    appt_patient_user = _patient_user_from_patient(patient) if patient else None
    final_patient_user = appt_patient_user or patient_user or frappe.session.user
    _require_valid_user(final_patient_user)

    # Who booked it (trackable)
    booked_by = frappe.session.user

    # Normalise allow_magic_link to 0/1
    allow_magic = 1 if str(allow_magic_link) in ("1", "true", "True", "yes", "on") else 0

    # Create Daily room
    room_name = _room_name("airtook")
    room = daily_create_room(room_name)

    daily_room_name = room.get("name") or room_name
    room_url = room.get("url")

    # Create session doc (includes new fields)
    doc = frappe.get_doc(
        {
            "doctype": SESSION_DTYPE,
            "session_type": session_type,
            "status": "Waiting",
            "patient_appointment": patient_appointment,
            "patient": patient,
            "patient_user": final_patient_user,   # NEW (mandatory in DocType)
            "booked_by": booked_by,               # NEW
            "allow_magic_link": allow_magic,      # NEW
            "practitioner": prac,
            "department": dept,
            "daily_room_name": daily_room_name,
            "daily_room_url": room_url,
        }
    )
    doc.insert(ignore_permissions=True)

    # Magic link is only generated/enabled if allow_magic_link is ON
    join_key = None
    expires_at = None

    if allow_magic:
        join_key = _generate_join_key()
        expires_at = add_to_date(now_datetime(), minutes=JOIN_KEY_TTL_MINUTES)

        doc.db_set("patient_join_key", join_key, update_modified=False)
        doc.db_set("patient_join_key_expires_at", expires_at, update_modified=False)

    frappe.db.commit()

    payload = {
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
    }

    # Provide magic URL only when enabled
    if join_key:
        payload["patient_join_url"] = f"{get_url()}/video/{doc.name}?k={join_key}"
        payload["patient_join_expires_at"] = expires_at

    return payload


# -------------------------
# API: join info
# -------------------------
@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_join_info(session_id, k=None):
    if not session_id:
        frappe.throw("Missing session id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)

    if not doc.daily_room_name:
        frappe.throw("Session has no Daily room assigned")

    # Every session must be tied to a registered patient user
    if not doc.get("patient_user"):
        frappe.throw("Session is not linked to a patient account")

    current_user = frappe.session.user
    is_guest = current_user == "Guest"

    practitioner_user = (
        _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    )
    is_owner = (
        not is_guest
        and practitioner_user
        and practitioner_user == current_user
    )

    # -------------------------
    # Determine role + identity
    # -------------------------
    if is_owner:
        role = "practitioner"
        display_name = _get_user_display_name(current_user)
        if display_name and not display_name.lower().startswith("dr"):
            display_name = f"Dr. {display_name}"

        token_user_id = current_user

    else:
        role = "patient"

        if is_guest:
            # Magic link join (no-login UX), but must be enabled and mapped to a registered patient_user
            if not k:
                frappe.throw("Login required (missing join key)")

            if not doc.get("allow_magic_link"):
                frappe.throw("Magic link access is disabled for this consultation")

            if not doc.patient_join_key or not doc.patient_join_key_expires_at:
                frappe.throw("This join link is not enabled")

            if k != doc.patient_join_key:
                frappe.throw("Invalid join key")

            if _is_expired(doc.patient_join_key_expires_at):
                frappe.throw("Join link expired")

            # burn key (single-use)
            doc.db_set("patient_join_key", None, update_modified=False)
            doc.db_set("patient_join_key_expires_at", None, update_modified=False)

            # Use the registered patient's identity (trackable)
            display_name = _get_user_display_name(doc.patient_user)
            token_user_id = doc.patient_user

        else:
            # Logged-in patient join:
            # If Patient record is linked to a different user, block.
            if doc.patient:
                patient_user_id = _patient_user_from_patient(doc.patient)
                if patient_user_id and patient_user_id != current_user:
                    frappe.throw("Not permitted")

            # Also enforce patient_user match if set
            if doc.patient_user and doc.patient_user != current_user:
                # Allow practitioner already handled above; here it's patient role mismatch
                frappe.throw("Not permitted")

            display_name = _get_user_display_name(current_user)
            token_user_id = current_user

    room = daily_get_room(doc.daily_room_name)
    room_url = room.get("url")

    token = daily_create_meeting_token(
        room_name=doc.daily_room_name,
        is_owner=(role == "practitioner"),
        user_id=token_user_id,
    )

    # -------------------------
    # Lifecycle
    # -------------------------
    if doc.status in ("Draft", "Scheduled"):
        doc.status = "Waiting"
        doc.save(ignore_permissions=True)

    if doc.status == "Waiting":
        doc.status = "Active"
        if not doc.started_at:
            doc.started_at = now_datetime()
        doc.save(ignore_permissions=True)

    return {
        "session_id": doc.name,
        "room_name": doc.daily_room_name,
        "room_url": room_url,
        "token": token,
        "role": role,
        "practitioner": doc.practitioner,
        "display_name": display_name,
        "patient_user": doc.patient_user,
    }


# -------------------------
# API: Aira entry point
# -------------------------
@frappe.whitelist(methods=["GET", "POST"])
def quick_consult(department=None):
    _require_login()
    return create_session(
        patient_appointment=None,
        department=department,
        practitioner=None,
        patient_user=None,       # defaults to current user
        allow_magic_link=1,      # quick consult supports elderly flow by default
    )
