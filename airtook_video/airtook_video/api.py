import secrets
import frappe
from frappe import _
from .daily import daily_create_room, daily_create_meeting_token, daily_get_room

SESSION_DTYPE = "Video Consultation Session"


# -------------------------
# Auth helper
# -------------------------
def _require_login():
    """Ensure the caller is logged in (no Guest access)."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


# -------------------------
# Utility
# -------------------------
def _room_name(prefix="airtook"):
    """Generate a short, URL-safe room name."""
    return f"{prefix}-{secrets.token_urlsafe(8).lower()}"


# -------------------------
# Department resolution (unicode-safe)
# -------------------------
def _resolve_department(dept: str | None) -> str | None:
    """
    Resolve incoming department text (e.g. 'Nutrition') to Medical Department DOCNAME (name).
    Unicode-safe: prefix match is done in Python (not SQL LIKE) to survive emoji/encoding issues.
    """
    if not dept:
        return None

    dept = dept.strip()

    # 1) Exact DOCNAME match
    if frappe.db.exists("Medical Department", dept):
        return dept

    # 2) Unicode-safe prefix match in Python
    rows = frappe.get_all("Medical Department", fields=["name"], limit_page_length=300)
    matches = [r["name"] for r in rows if (r.get("name") or "").startswith(dept)]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        frappe.throw(
            f"Ambiguous Medical Department: '{dept}'. Matches: {matches}. Please be more specific.",
            frappe.ValidationError,
        )

    frappe.throw(
        f"Unknown Medical Department: '{dept}'. Please specify a valid department.",
        frappe.ValidationError,
    )


# -------------------------
# Practitioner helpers (ERPNext Healthcare)
# -------------------------
def _pick_practitioner(dept: str | None):
    """
    v1: pick the first ACTIVE Healthcare Practitioner matching department with a user_id.
    Returns practitioner docname or None.
    """
    if not dept:
        return None

    # "Healthcare Practitioner" DocType fields you showed:
    # - status: Active/Disabled
    # - department: Link to Medical Department
    # - user_id: Link to User
    rows = frappe.get_all(
        "Healthcare Practitioner",
        filters={
            "status": "Active",
            "department": dept,
        },
        fields=["name", "user_id"],
        limit_page_length=50,
        order_by="modified desc",
    )

    # choose first with a linked user
    for r in rows:
        if r.get("user_id"):
            return r["name"]

    return None


def _get_practitioner_user(practitioner_name: str | None):
    """Map practitioner docname -> linked User (user_id)."""
    if not practitioner_name:
        return None

    user_id = frappe.db.get_value("Healthcare Practitioner", practitioner_name, "user_id")
    return user_id


# -------------------------
# API: create session
# -------------------------
@frappe.whitelist(methods=["POST"])
def create_session(patient_appointment=None, department=None, practitioner=None):
    """
    Create a Video Consultation Session + Daily room.
    """
    _require_login()

    session_type = "Scheduled" if patient_appointment else "Quick Consult"

    patient = None
    dept = department

    # Pull from appointment if provided
    if patient_appointment:
        appt = frappe.get_doc("Patient Appointment", patient_appointment)
        patient = getattr(appt, "patient", None)
        dept = getattr(appt, "department", None) or dept
        # In some setups, appointment may already have practitioner
        practitioner = practitioner or getattr(appt, "practitioner", None)

    # Resolve department (required for Quick Consult)
    dept = _resolve_department(dept)
    if not dept:
        frappe.throw("Department is required", frappe.ValidationError)

    # Pick practitioner if not supplied
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
            "practitioner": prac,         # practitioner docname (Healthcare Practitioner)
            "department": dept,           # Medical Department docname
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


# -------------------------
# API: join info for /video/<session_id>
# -------------------------
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

    current_user = frappe.session.user

    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    is_owner = bool(practitioner_user and practitioner_user == current_user)

    room = daily_get_room(doc.daily_room_name)
    room_url = room.get("url")

    token = daily_create_meeting_token(
        room_name=doc.daily_room_name,
        is_owner=is_owner,
        user_id=current_user,
    )

    if doc.status in ("Draft", "Scheduled"):
        doc.status = "Waiting"
        doc.save(ignore_permissions=True)

    return {
        "session_id": doc.name,
        "room_name": doc.daily_room_name,
        "room_url": room_url,
        "token": token,
        "role": "practitioner" if is_owner else "patient",
        "practitioner": doc.practitioner,
    }


# -------------------------
# API: Aira entry point
# -------------------------
@frappe.whitelist(methods=["POST"])
def quick_consult(department=None):
    """
    Aira-triggerable entry point:
    - creates Quick Consult session
    - auto-picks an active practitioner for that department (if any)
    """
    _require_login()
    return create_session(patient_appointment=None, department=department, practitioner=None)
