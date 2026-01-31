import time
import requests
import frappe


def _get_daily_config():
    api_key = frappe.conf.get("daily_api_key")
    base_url = (frappe.conf.get("daily_api_base_url") or "https://api.daily.co/v1").rstrip("/")
    token_ttl_minutes = int(frappe.conf.get("daily_token_ttl_minutes") or 10)
    room_exp_minutes = int(frappe.conf.get("daily_room_exp_minutes") or 60)

    if not api_key:
        frappe.throw("Missing daily_api_key in site config (Frappe Cloud).")

    return api_key, base_url, token_ttl_minutes, room_exp_minutes


def daily_create_room(room_name, exp_minutes=None):
    api_key, base_url, _, default_room_exp = _get_daily_config()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    minutes = exp_minutes if exp_minutes is not None else default_room_exp
    payload = {
        "name": room_name,
        "properties": {
            "enable_chat": False,
            "enable_screenshare": True,
            "start_video_off": False,
            "start_audio_off": False,
        },
    }

    if minutes and minutes > 0:
        payload["properties"]["exp"] = int(time.time()) + (int(minutes) * 60)

    r = requests.post(f"{base_url}/rooms", json=payload, headers=headers, timeout=30)

    if r.status_code == 409:
        r2 = requests.get(f"{base_url}/rooms/{room_name}", headers=headers, timeout=30)
        if not r2.ok:
            frappe.throw(f"Daily get room failed: {r2.status_code} {r2.text}")
        return r2.json()

    if not r.ok:
        frappe.throw(f"Daily create room failed: {r.status_code} {r.text}")

    return r.json()


def daily_create_meeting_token(room_name, is_owner, user_id):
    api_key, base_url, token_ttl_minutes, _ = _get_daily_config()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    exp = int(time.time()) + (int(token_ttl_minutes) * 60)

    payload = {
        "properties": {
            "room_name": room_name,
            "is_owner": bool(is_owner),
            "user_id": user_id,
            "exp": exp,
        }
    }

    r = requests.post(f"{base_url}/meeting-tokens", json=payload, headers=headers, timeout=30)
    if not r.ok:
        frappe.throw(f"Daily create token failed: {r.status_code} {r.text}")

    token = r.json().get("token")
    if not token:
        frappe.throw("Daily token missing in response")

    return token

def daily_get_room(room_name):
    api_key, base_url, _, _ = _get_daily_config()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    r = requests.get(f"{base_url}/rooms/{room_name}", headers=headers, timeout=30)
    if not r.ok:
        frappe.throw(f"Daily get room failed: {r.status_code} {r.text}")
    return r.json()

