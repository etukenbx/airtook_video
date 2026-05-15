# -*- coding: utf-8 -*-
import frappe

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.safe_render = False
    context.page_title = "AirTook™ Video Consultation"

    # Redirect unauthenticated users — Agora tokens are role-specific,
    # so we cannot allow anonymous access without a magic key.
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/video"
        raise frappe.Redirect

    # Extract session_id from /video/<session_id> route or ?session_id= query
    session_id = _extract_session_id()
    context.session_id = session_id
    context.invalid    = 0 if session_id else 1
    context.is_guest   = 0  # always logged in at this point

    # Agora credentials for the frontend SDK
    context.app_id = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
        frappe.conf.get("agora_app_id") or ""
    )

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
