import secrets
import frappe
from frappe import _
from .daily import daily_create_room, daily_create_meeting_token, daily_get_room


SESSION_DTYPE = "Video Consultation Session"


def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _room_name(prefix="airtook"):
    return f"{prefix}_{secrets.token_urlsafe(16).replace('-', '').replace('_', '')}".lower()


def _get_practitioner_user(practitioner_name: str) -> str | None:
    """Return linked system user for a Healthcare Practitioner record."""
    if not practitioner_name:
        return None
    try:
        return frappe.db.get_value("Healthcare Practitioner", practitioner_name, "user_id")
    except Exception:
        return None


def _pick_practitioner(department: str | None = None) -> str | None:
    """
    Basic v1 routing:
    - pick first Active Healthcare Practitioner with a linked user_id
    - if department provided, try to match department first
    """
    filters = {"status": "Active"}
    fields = ["name", "user_id", "department"]

    # Try department match first
    if department:
        rows = frappe.get_all("Healthcare Practitioner",
            filters={"status": "Active", "department": department},
            fields=fields,
            limit_page_length=50
        )
        for r in rows:
            if r.get("user_id"):
                return r["name"]

    # Fallback: any active practitioner with user_id
    rows = frappe.get_all("Healthcare Practitioner", filters=filters, fields=fields, limit_page_length=50)
    for r in rows:
        if r.get("user_id"):
            return r["name"]

    return None


@frappe.whitelist(methods=["POST"])
def create_session(patient_appointment=None, department=None, practitioner=None):
    """
    Create a session + Daily room.
    - If patient_appointment provided: Scheduled session
    - Else: Quick Consult session
    Returns: session_id, room_name, room_url
    """
    _require_login()

    session_type = "Scheduled" if patient_appointment else "Quick Consult"

    patient = None
    dept = department

    # Pull from appointment if provided
    if patient_appointment:
        appt = frappe.get_doc("Patient Appointment", patient_appointment)

        # common fields in Healthcare app
        patient = getattr(appt, "patient", None)

        # department field exists in your system
        dept = getattr(appt, "department", None) or dept

    # Choose practitioner if not supplied
    prac = practitioner or _pick_practitioner(dept)

    # Create Daily room
    room_name = _room_name("airtook")
    room = daily_create_room(room_name)

    # Create Session doc
    doc = frappe.get_doc({
        "doctype": SESSION_DTYPE,
        "session_type": session_type,
        "status": "Waiting",
        "patient_appointment": patient_appointment,
        "patient": patient,
        "practitioner": prac,
        "department": dept,
        "daily_room_name": room.get("name") or room_name,
    })
    doc.insert(ignore_permissions=True)

    return {
        "session_id": doc.name,
        "session_type": session_type,
        "status": doc.status,
        "department": doc.department,
        "practitioner": doc.practitioner,
        "room_name": doc.daily_room_name,
        "room_url": room.get("url"),
    }


@frappe.whitelist(methods=["POST"])
def get_join_info(session_id):
    """
    Returns join details for current user:
    - room_url
    - meeting token (owner if practitioner user, else attendee)
    """
    _require_login()

    doc = frappe.get_doc(SESSION_DTYPE, session_id)

    if not doc.daily_room_name:
        frappe.throw("Session has no Daily room assigned")

    # Determine role
    current_user = frappe.session.user
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    is_owner = bool(practitioner_user and practitioner_user == current_user)

    # Fetch room URL fresh from Daily (since we didn't store it in DocType)
    room = daily_get_room(doc.daily_room_name)
    room_url = room.get("url")

    token = daily_create_meeting_token(
        room_name=doc.daily_room_name,
        is_owner=is_owner,
        user_id=current_user,
    )

    # Update status lightly
    if doc.status in ("Draft", "Scheduled"):
        doc.status = "Waiting"
        doc.save(ignore_permissions=True)

    return {
        "session_id": doc.name,
        "room_name": doc.daily_room_name,
        "room_url": room_url,
        "token": token,
        "role": "practitioner" if is_owner else "patient",
    }


@frappe.whitelist(methods=["POST"])
def quick_consult(department=None):
    """
    Aira-triggerable entry point:
    - creates Quick Consult session
    - routes to an available practitioner (v1: first Active with user_id)
    """
    _require_login()
    return create_session(patient_appointment=None, department=department, practitioner=None)
