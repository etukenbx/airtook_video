import frappe

def get_context(context):
    context.no_cache = 1
    context.session_id = (
        frappe.form_dict.get("session_id")
        or frappe.form_dict.get("name")
        or frappe.form_dict.get("session")
    )
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
