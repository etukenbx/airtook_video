import secrets
import frappe
from frappe import _
from airtook_video.daily import daily_create_room, daily_create_meeting_token


def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _room_name(prefix="airtook"):
    return f"{prefix}_{secrets.token_urlsafe(16).replace('-', '').replace('_', '')}".lower()


@frappe.whitelist(methods=["POST"])
def create_room(prefix="airtook", exp_minutes=None):
    _require_login()

    room_name = _room_name(prefix)
    room = daily_create_room(room_name, exp_minutes)

    return {
        "room_name": room.get("name") or room_name,
        "room_url": room.get("url"),
    }


@frappe.whitelist(methods=["POST"])
def create_token(room_name, is_owner=0):
    _require_login()

    token = daily_create_meeting_token(
        room_name=room_name,
        is_owner=int(is_owner),
        user_id=frappe.session.user,
    )

    return {
        "room_name": room_name,
        "token": token,
    }
