# -*- coding: utf-8 -*-
import frappe

no_cache = 1  # ensure fresh token fetch + no stale HTML caching


def _extract_session_id():
    """
    Works for:
    - /video/<session_id> via website_route_rules (view_args)
    - /video?session_id=... (query string fallback)
    """
    # Query-string fallback
    if frappe.form_dict.get("session_id"):
        return frappe.form_dict.get("session_id").strip()

    # Route-rule args (Flask view args)
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
    context.session_id = session_id
    context.page_title = "AirTook Video Consultation"

    # Optional: show basic error if session_id missing
    context.invalid = 0 if session_id else 1

    # Read optional magic link key (?k=...)
    join_key = (frappe.form_dict.get("k") or "").strip()
    context.join_key = join_key
    context.allow_guest = 1 if join_key else 0

    # Guest flag for template UI decisions
    context.is_guest = 1 if frappe.session.user == "Guest" else 0

    return context
