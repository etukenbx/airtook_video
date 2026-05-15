# -*- coding: utf-8 -*-
import frappe

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.safe_render = False
    context.page_title = "AirTook™ Video Consultation"

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/video"
        raise frappe.Redirect

    session_id = _extract_session_id()
    context.session_id = session_id
    context.invalid    = 0 if session_id else 1
    context.is_guest   = 0

    context.app_id = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
        frappe.conf.get("agora_app_id") or ""
    )

    # If the URL has a session_id but no Agora params (ch/tok), generate a fresh
    # join URL via create_session and redirect to it so the video page gets all params.
    if session_id and not frappe.form_dict.get("ch"):
        try:
            vs = frappe.db.get_value(
                "AirTook Video Session", session_id,
                ["appointment", "status"], as_dict=True,
            )
            if vs and vs.get("appointment") and vs.get("status") in ("scheduled", "active"):
                from airtook_video.airtook_video import api as video_api
                sp = video_api.create_session(patient_appointment=vs["appointment"])
                if sp and sp.get("patient_join_url"):
                    frappe.local.flags.redirect_location = sp["patient_join_url"]
                    raise frappe.Redirect
        except frappe.Redirect:
            raise
        except Exception:
            pass  # fall through — video.html shows error state

    return context


def _extract_session_id():
    if frappe.form_dict.get("session_id"):
        return frappe.form_dict.get("session_id").strip()
    try:
        req       = getattr(frappe.local, "request", None)
        view_args = getattr(req, "view_args", None) if req else None
        if view_args and view_args.get("session_id"):
            return str(view_args.get("session_id")).strip()
    except Exception:
        pass
    return None
