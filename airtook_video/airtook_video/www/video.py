# -*- coding: utf-8 -*-
import frappe

no_cache = 1

def _extract_session_id():
    if frappe.form_dict.get("session_id"):
        return frappe.form_dict.get("session_id").strip()
    try:
        req = getattr(frappe.local, "request", None)
        view_args = getattr(req, "view_args", None) if req else None
        if view_args and view_args.get("session_id"):
            return str(view_args.get("session_id")).strip()
    except Exception:
        pass
    return None

def get_context(context):
    session_id = _extract_session_id()
    context.session_id   = session_id or ""
    context.page_title   = "AirTook™ Video Consultation"
    context.invalid      = 0 if session_id else 1
    context.join_key     = (frappe.form_dict.get("k") or "").strip()
    context.allow_guest  = 1 if context.join_key else 0
    context.is_guest     = 1 if frappe.session.user == "Guest" else 0
    context.session_status = ""
    context.consultation_mode = "Video"
    context.duration_minutes  = 30
    context.appointment_type  = ""
    context.practitioner_name = ""
    context.patient_name      = ""

    if session_id:
        try:
            row = frappe.db.get_value(
                "Video Consultation Session", session_id,
                ["status", "consultation_mode", "duration_minutes",
                 "appointment", "practitioner", "patient"],
                as_dict=True
            )
            if row:
                context.session_status    = row.get("status") or ""
                context.consultation_mode = row.get("consultation_mode") or "Video"
                context.duration_minutes  = int(row.get("duration_minutes") or 30)

                if row.get("appointment"):
                    appt = frappe.db.get_value(
                        "Patient Appointment", row["appointment"],
                        ["appointment_type", "patient_name", "practitioner_name"],
                        as_dict=True
                    )
                    if appt:
                        context.appointment_type  = appt.get("appointment_type") or ""
                        context.patient_name      = appt.get("patient_name") or ""
                        context.practitioner_name = appt.get("practitioner_name") or ""

                if not context.practitioner_name and row.get("practitioner"):
                    context.practitioner_name = frappe.db.get_value(
                        "Healthcare Practitioner", row["practitioner"], "practitioner_name"
                    ) or ""
        except Exception:
            pass

    return context
