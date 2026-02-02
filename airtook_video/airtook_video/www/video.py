import frappe

def get_context(context):
    context.no_cache = 1

    # Supports /video/<session_id> and /video?session_id=<id>
    context.session_id = (
        frappe.form_dict.get("session_id")
        or frappe.form_dict.get("name")
        or frappe.form_dict.get("session")
    )

    # CSRF token needed for POST calls from website pages
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
