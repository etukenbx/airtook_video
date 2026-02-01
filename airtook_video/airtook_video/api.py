import secrets
import frappe
from frappe import _
from .daily import daily_create_room, daily_create_meeting_token, daily_get_room


SESSION_DTYPE = "Video Consultation Session"


def _resolve_department(dept: str | None) -> str | None:
    """
    Resolve incoming department text (e.g. 'Nutrition') to the
    Medical Department DOCNAME.
    """
    if not dept:
        return None

    dept = dept.strip()

    # 1) Exact DOCNAME match
    if frappe.db.exists("Medical Department", dept):
        return dept

    # 2) Exact match on `department` Data field
    rows = frappe.get_all(
        "Medical Department",
        filters={"department": dept},
        fields=["name"],
        limit_page_length=2,
    )
    if len(rows) == 1:
        return rows[0]["name"]

    # 3) Starts-with fallback (handles emojis like NutritionðŸ¥—)
    rows = frappe.get_all(
        "Medical Department",
        filters=[["department", "like", f"{dept}%"]],
        fields=["name"],
        limit_page_length=2,
    )
    if len(rows) == 1:
        return rows[0]["name"]

    # 4) Ambiguous or missing -> hard fail (safe for telemedicine)
    frappe.throw(
        f"Ambiguous or unknown Medical Department: '{dept}'. Please specify a valid department.",
        frappe.ValidationError,
    )

    # Unreachable, but keeps type checkers happy
    return None


@frappe.whitelist(methods=["POST"])
def create_session(patient_appointment=None, department=None, practitioner=None):
    """
    Create a session + Daily room.
    """
    _require_login()

    session_type = "Scheduled" if patient_appointment else "Quick Consult"

    patient = None
    dept = department  # raw input first

    # Pull from appointment if provided
    if patient_appointment:
        appt = frappe.get_doc("Patient Appointment", patient_appointment)
        patient = getattr(appt, "patient", None)
        dept = getattr(appt, "department", None) or dept

    # Resolve once, authoritatively
    dept = _resolve_department(dept)

    # Defensive check (should already be true if _resolve_department returned a docname)
    if dept and not frappe.db.exists("Medical Department", dept):
        frappe.throw(
            f"Resolved department does not exist: {dept}",
            frappe.ValidationError,
        )

    # Choose practitioner if not supplied
    prac = practitioner or _pick_practitioner(dept) or None

    # Create Daily room
    room_name = _room_name("airtook")
    room = daily_create_room(room_name)

    # Create Session doc
    doc = frappe.get_doc(
        {
            "doctype": SESSION_DTYPE,
            "session_type": session_type,
            "status": "Waiting",
            "patient_appointment": patient_appointment,
            "patient": patient,
            "practitioner": prac,
            "department": dept,  # already resolved
            "daily_room_name": room.get("name") or room_name,
        }
    )

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
    practitioner_user = (
        _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    )
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
    return create_session(
        patient_appointment=None, department=department, practitioner=None
    )
