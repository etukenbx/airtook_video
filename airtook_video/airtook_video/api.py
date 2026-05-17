# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import random
import struct
import time
import zlib

import frappe
from frappe import _
from frappe.utils import now_datetime, get_url

SESSION_DTYPE = "AirTook Video Session"
DEFAULT_DURATION_MINUTES = 30
TOKEN_EXPIRE_SECONDS = 7200  # 2 hours

ROLE_PUBLISHER   = 1
ROLE_SUBSCRIBER  = 2

EXTENSION_DISCOUNT_PCT = 20


# ─── Agora credentials ───────────────────────────────────────────────────────

def _get_agora_credentials():
    app_id = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
        frappe.conf.get("agora_app_id") or ""
    ).strip()
    certificate = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_certificate") or
        frappe.conf.get("agora_app_certificate") or ""
    ).strip()
    if not app_id or not certificate:
        frappe.throw(
            _("Agora credentials not configured. Set agora_app_id and agora_app_certificate."),
            frappe.ValidationError,
        )
    return app_id, certificate


# ─── Token generation ────────────────────────────────────────────────────────

def _generate_uid():
    return random.randint(100000, 999999)


def _pack_string(s):
    """Length-prefixed (uint16 LE) bytes packing used in Agora DynamicKey5."""
    b = s if isinstance(s, bytes) else s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _generate_agora_token_manual(app_id, app_certificate, channel_name, uid, role, expire_ts):
    """
    Agora AccessToken (DynamicKey5) HMAC-SHA256 implementation.
    Reference: github.com/AgoraIO/Tools/DynamicKey/AgoraDynamicKey/python3
    Token format: "006" + base64(content)
    content = salt(4) + ts(4) + privileges_msg
    signing  = app_id + uid_str + crc_chan(8 hex) + crc_uid(8 hex) + ts(10 dec) + salt(10 dec) + privileges_msg
    """
    ts   = int(time.time())
    salt = random.randint(1, 0x7FFFFFFF)
    uid_str = str(uid)

    privileges = {1: expire_ts}  # join channel
    if role == ROLE_PUBLISHER:
        privileges[2] = expire_ts  # publish audio
        privileges[3] = expire_ts  # publish video
        privileges[4] = expire_ts  # data stream

    # Pack privileges: uint16 count + (uint16 priv_id + uint32 expire) per entry
    msg = struct.pack("<H", len(privileges))
    for k in sorted(privileges.keys()):
        msg += struct.pack("<HI", k, privileges[k])

    crc_chan = zlib.crc32(channel_name.encode("utf-8")) & 0xFFFFFFFF
    crc_uid  = zlib.crc32(uid_str.encode("utf-8"))      & 0xFFFFFFFF

    # Signing message per Agora DynamicKey5 reference
    signing_str = (
        app_id +
        uid_str +
        "%08x" % crc_chan +
        "%08x" % crc_uid +
        str(ts) +
        str(salt) +
        msg.hex()
    )
    signature = hmac.new(
        app_certificate.encode("utf-8"),
        signing_str.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    content = (
        struct.pack("<I", salt) +
        struct.pack("<I", ts) +
        _pack_string(signature) +
        struct.pack("<I", crc_chan) +
        struct.pack("<I", crc_uid) +
        _pack_string(msg)
    )
    return "006" + base64.b64encode(content).decode("utf-8")


def _generate_agora_token(app_id, app_certificate, channel_name, uid,
                          role=ROLE_PUBLISHER, expire_seconds=TOKEN_EXPIRE_SECONDS):
    expire_ts = int(time.time()) + expire_seconds
    try:
        from agora_token_builder import RtcTokenBuilder
        return RtcTokenBuilder.buildTokenWithUid(
            app_id, app_certificate, channel_name, uid, role, expire_ts
        )
    except ImportError:
        pass
    except Exception:
        frappe.log_error(frappe.get_traceback(), "agora_token_builder failed — using manual fallback")
    return _generate_agora_token_manual(app_id, app_certificate, channel_name, uid, role, expire_ts)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _get_practitioner_user(practitioner_name):
    if not practitioner_name:
        return None
    return frappe.db.get_value("Healthcare Practitioner", practitioner_name, "user_id")


def _patient_user_from_patient(patient_name):
    if not patient_name:
        return None
    return frappe.db.get_value("Patient", patient_name, "user_id")


def _get_fee_per_minute(appointment_type, mode="Video"):
    PRICES = {
        "Priority Consultation 15min": 4499,
        "Priority Consultation 30min": 7499,
        "Priority Consultation 45min": 9999,
        "Priority Consultation 60min": 12499,
        "Scheduled Consultation 15min": 2999,
        "Scheduled Consultation 30min": 4999,
        "Scheduled Consultation 45min": 6499,
        "Scheduled Consultation 60min": 7999,
        "Quick Consultation": 7499,
        "General Consultation": 4999,
    }
    base    = PRICES.get(appointment_type or "", 4999)
    minutes = 30
    for suffix in ["15min", "30min", "45min", "60min"]:
        if (appointment_type or "").endswith(suffix):
            minutes = int(suffix.replace("min", ""))
            break
    return round(base / minutes, 2)


def _build_join_url(session_name, channel_name, uid, token, role, appointment_name, duration_minutes):
    from urllib.parse import urlencode
    params = urlencode({
        "ch":   channel_name,
        "uid":  uid,
        "tok":  token,
        "role": role,
        "apt":  appointment_name or "",
        "dur":  duration_minutes,
    })
    return f"{get_url()}/video/{session_name}?{params}"


def _build_session_response(doc, doctor_token=None, patient_token=None):
    app_id = (
        frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
        frappe.conf.get("agora_app_id") or ""
    )
    if not doctor_token or not patient_token:
        try:
            app_cert = (
                frappe.db.get_single_value("AirTook Configuration", "agora_app_certificate") or
                frappe.conf.get("agora_app_certificate") or ""
            )
            if app_cert:
                doctor_token  = _generate_agora_token(app_id, app_cert, doc.channel_name, doc.doctor_uid, ROLE_PUBLISHER)
                patient_token = _generate_agora_token(app_id, app_cert, doc.channel_name, doc.patient_uid, ROLE_PUBLISHER)
        except Exception:
            doctor_token  = doctor_token  or ""
            patient_token = patient_token or ""

    dur = int(doc.duration_minutes or DEFAULT_DURATION_MINUTES)
    doctor_join_url  = _build_join_url(doc.name, doc.channel_name, doc.doctor_uid,  doctor_token,  "doctor",  doc.appointment, dur)
    patient_join_url = _build_join_url(doc.name, doc.channel_name, doc.patient_uid, patient_token, "patient", doc.appointment, dur)

    return {
        "session_id":        doc.name,
        "appointment":       doc.appointment or "",
        "channel_name":      doc.channel_name,
        "app_id":            app_id,
        "doctor_uid":        doc.doctor_uid,
        "patient_uid":       doc.patient_uid,
        "doctor_token":      doctor_token  or "",
        "patient_token":     patient_token or "",
        "doctor_join_url":   doctor_join_url,
        "patient_join_url":  patient_join_url,
        "video_join_url":    patient_join_url,   # backwards-compat alias for callers
        "status":            doc.status,
        "duration_minutes":  dur,
        "extensions_count":  int(getattr(doc, "extensions_count", 0) or 0),
    }


# ─── Agora Cloud Recording ───────────────────────────────────────────────────

def _get_agora_auth_header():
    customer_key = (frappe.conf.get("agora_customer_key") or "").strip()
    customer_secret = (frappe.conf.get("agora_customer_secret") or "").strip()
    if not customer_key:
        try:
            customer_key = (
                frappe.db.get_single_value("AirTook Configuration", "agora_customer_key") or ""
            ).strip()
        except Exception:
            pass
    if not customer_secret:
        try:
            customer_secret = (
                frappe.db.get_single_value("AirTook Configuration", "agora_customer_secret") or ""
            ).strip()
        except Exception:
            pass
    credentials = base64.b64encode(f"{customer_key}:{customer_secret}".encode()).decode()
    return f"Basic {credentials}"


def _acquire_cloud_recording(app_id, channel_name, uid):
    """POST to Agora acquire endpoint. Returns resourceId or None."""
    import requests as _req
    try:
        auth = _get_agora_auth_header()
        url = f"https://api.agora.io/v1/apps/{app_id}/cloud_recording/acquire"
        body = {
            "cname": channel_name,
            "uid": str(uid),
            "clientRequest": {
                "resourceExpiredHour": 24,
                "scene": 0,
            },
        }
        r = _req.post(url, json=body, headers={"Authorization": auth, "Content-Type": "application/json"}, timeout=15)
        if r.status_code == 200:
            return r.json().get("resourceId")
        frappe.log_error(f"Agora acquire failed {r.status_code}: {r.text[:300]}", "Agora Transcription")
    except Exception as e:
        frappe.log_error(f"Agora acquire exception: {e}", "Agora Transcription")
    return None


def _start_transcription(app_id, channel_name, uid, resource_id, token):
    """POST to Agora start endpoint. Returns sid or None."""
    import requests as _req
    try:
        s3_bucket = (frappe.conf.get("agora_s3_bucket") or "").strip()
        s3_access_key = (frappe.conf.get("agora_s3_access_key") or "").strip()
        s3_secret_key = (frappe.conf.get("agora_s3_secret_key") or "").strip()
        if not s3_bucket or not s3_access_key or not s3_secret_key:
            frappe.log_error(
                "Agora S3 not configured — transcription disabled. Set agora_s3_bucket, agora_s3_access_key, agora_s3_secret_key in site_config.json.",
                "Agora Transcription",
            )
            return None

        auth = _get_agora_auth_header()
        url = (
            f"https://api.agora.io/v1/apps/{app_id}/cloud_recording"
            f"/resourceid/{resource_id}/mode/mix/start"
        )
        body = {
            "cname": channel_name,
            "uid": str(uid),
            "clientRequest": {
                "token": token,
                "recordingConfig": {
                    "maxIdleTime": 30,
                    "streamTypes": 0,
                    "channelType": 0,
                },
                "transcodeOptions": {
                    "transConfig": {
                        "transcriptionMode": 1,
                    }
                },
                "storageConfig": {
                    "vendor": 1,
                    "region": 0,
                    "bucket": s3_bucket,
                    "accessKey": s3_access_key,
                    "secretKey": s3_secret_key,
                    "fileNamePrefix": ["airtook", "transcripts"],
                },
            },
        }
        r = _req.post(url, json=body, headers={"Authorization": auth, "Content-Type": "application/json"}, timeout=15)
        if r.status_code == 200:
            return r.json().get("sid")
        frappe.log_error(f"Agora start failed {r.status_code}: {r.text[:300]}", "Agora Transcription")
    except Exception as e:
        frappe.log_error(f"Agora start exception: {e}", "Agora Transcription")
    return None


def _stop_cloud_recording(app_id, channel_name, uid, resource_id, sid):
    """POST to Agora stop endpoint. Returns response JSON or None."""
    import requests as _req
    try:
        auth = _get_agora_auth_header()
        url = (
            f"https://api.agora.io/v1/apps/{app_id}/cloud_recording"
            f"/resourceid/{resource_id}/sid/{sid}/mode/mix/stop"
        )
        body = {"cname": channel_name, "uid": str(uid), "clientRequest": {}}
        r = _req.post(url, json=body, headers={"Authorization": auth, "Content-Type": "application/json"}, timeout=15)
        if r.status_code == 200:
            return r.json()
        frappe.log_error(f"Agora stop failed {r.status_code}: {r.text[:300]}", "Agora Transcription")
    except Exception as e:
        frappe.log_error(f"Agora stop exception: {e}", "Agora Transcription")
    return None


def _save_transcript_to_encounter(session_name, transcript_text):
    """Create or update a draft Patient Encounter pre-filled with the transcript."""
    try:
        session = frappe.get_doc("AirTook Video Session", session_name, ignore_permissions=True)

        if not session.get("appointment"):
            return

        appointment = frappe.get_doc("Patient Appointment", session.appointment)

        formatted_transcript = (
            f"--- Consultation Transcript (Auto-generated) ---\n"
            f"Date: {frappe.utils.nowdate()}\n"
            f"Duration: {session.duration_minutes or 0} minutes\n\n"
            f"{transcript_text}\n\n"
            f"--- End of Transcript ---\n"
            f"Note: This transcript was auto-generated by AirTook AI. "
            f"Please review and edit before submitting."
        )

        existing = frappe.db.get_value(
            "Patient Encounter",
            {"appointment": session.appointment, "docstatus": 0},
            "name",
            order_by="creation desc",
        )

        if existing:
            frappe.db.set_value(
                "Patient Encounter", existing, "encounter_comment", formatted_transcript
            )
            encounter_name = existing
        else:
            enc = frappe.get_doc({
                "doctype": "Patient Encounter",
                "patient": appointment.patient,
                "practitioner": appointment.practitioner,
                "appointment": appointment.name,
                "appointment_type": appointment.appointment_type or "",
                "encounter_date": frappe.utils.nowdate(),
                "encounter_comment": formatted_transcript,
            })
            enc.insert(ignore_permissions=True)
            encounter_name = enc.name

        frappe.db.set_value("AirTook Video Session", session_name, {
            "transcript_encounter": encounter_name,
            "transcript_status": "Saved to Encounter",
        })
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Save transcript failed: {e}\n{frappe.get_traceback()}", "Agora Transcription")
        try:
            frappe.db.set_value(
                "AirTook Video Session", session_name, "transcript_status", "Failed"
            )
            frappe.db.commit()
        except Exception:
            pass


# ─── Transcription webhook ───────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def agora_transcription_webhook():
    """Receives Agora cloud recording transcription callback."""
    import json as _json

    payload = frappe.request.get_data(as_text=True)
    try:
        data = _json.loads(payload)
    except Exception:
        frappe.response["http_status_code"] = 400
        return {"error": "invalid json"}

    channel_name = (data.get("details") or {}).get("channelName", "")
    transcriptions = (data.get("details") or {}).get("transcriptions") or []

    if not channel_name:
        return {"ok": True}

    words = []
    for t in transcriptions:
        for w in (t.get("words") or []):
            text = (w.get("text") or "").strip()
            if text:
                words.append(text)
    transcript_text = " ".join(words).strip()

    if not transcript_text:
        return {"ok": True}

    try:
        session_name = frappe.db.get_value(
            "AirTook Video Session", {"channel_name": channel_name}, "name"
        )
        if not session_name:
            return {"ok": True}

        frappe.db.set_value("AirTook Video Session", session_name, {
            "transcript_text": transcript_text,
            "transcript_status": "Received",
        })
        frappe.db.commit()

        _save_transcript_to_encounter(session_name, transcript_text)
    except Exception as e:
        frappe.log_error(f"Transcription webhook error: {e}", "Agora Transcription")

    return {"ok": True}


# ─── create_session ──────────────────────────────────────────────────────────

@frappe.whitelist(methods=["GET", "POST"])
def create_session(patient_appointment=None, appointment_name=None,
                   duration_minutes=None, consultation_mode="Video", **kwargs):
    _require_login()

    appt_name = appointment_name or patient_appointment
    if not appt_name:
        frappe.throw(_("appointment_name is required"), frappe.ValidationError)

    # Reuse an existing non-completed session for this appointment
    existing = frappe.db.get_value(
        SESSION_DTYPE,
        {"appointment": appt_name, "status": ["not in", ["completed", "expired"]]},
        "name",
    )
    if existing:
        doc = frappe.get_doc(SESSION_DTYPE, existing, ignore_permissions=True)
        return _build_session_response(doc)

    appt = frappe.get_doc("Patient Appointment", appt_name)
    patient      = getattr(appt, "patient", None)
    practitioner = getattr(appt, "practitioner", None)
    appt_type    = getattr(appt, "appointment_type", None)

    if not duration_minutes:
        for mins in [15, 30, 45, 60]:
            if (appt_type or "").endswith(f"{mins}min"):
                duration_minutes = mins
                break
    duration_minutes = int(duration_minutes or DEFAULT_DURATION_MINUTES)

    patient_user = _patient_user_from_patient(patient) if patient else frappe.session.user

    app_id, app_certificate = _get_agora_credentials()

    # Sanitise channel name: lowercase alphanumerics + hyphens, max 64 chars
    raw_channel = f"at-{appt_name.lower()}-{random.randint(1000, 9999)}"
    channel_name = "".join(c if c.isalnum() or c == "-" else "-" for c in raw_channel)[:64]

    doctor_uid  = _generate_uid()
    patient_uid = _generate_uid()

    doctor_token  = _generate_agora_token(app_id, app_certificate, channel_name, doctor_uid,  ROLE_PUBLISHER)
    patient_token = _generate_agora_token(app_id, app_certificate, channel_name, patient_uid, ROLE_PUBLISHER)

    doc = frappe.get_doc({
        "doctype":          SESSION_DTYPE,
        "appointment":      appt_name,
        "practitioner":     practitioner,
        "patient":          patient,
        "patient_user":     patient_user,
        "channel_name":     channel_name,
        "doctor_uid":       doctor_uid,
        "patient_uid":      patient_uid,
        "duration_minutes": duration_minutes,
        "status":           "scheduled",
        "created_at":       now_datetime(),
    })
    doc.insert(ignore_permissions=True)

    if frappe.db.has_column("Patient Appointment", "airtook_video_session"):
        frappe.db.set_value("Patient Appointment", appt_name, "airtook_video_session", doc.name)

    frappe.db.commit()

    # Start cloud recording / transcription (non-blocking)
    try:
        resource_id = _acquire_cloud_recording(app_id, channel_name, str(doctor_uid))
        if resource_id:
            sid = _start_transcription(app_id, channel_name, str(doctor_uid), resource_id, doctor_token)
            if sid:
                _update = {"cloud_recording_resource_id": resource_id, "cloud_recording_sid": sid}
                if frappe.db.has_column("AirTook Video Session", "cloud_recording_status"):
                    _update["cloud_recording_status"] = "Recording"
                frappe.db.set_value("AirTook Video Session", doc.name, _update)
                frappe.db.commit()
    except Exception as _e:
        frappe.log_error(f"Transcription start failed: {_e}", "Agora Transcription")

    return _build_session_response(doc, doctor_token=doctor_token, patient_token=patient_token)


# ─── get_session_status ──────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_session_status(session_id):
    if not session_id:
        frappe.throw("Missing session_id")
    row = frappe.db.get_value(
        SESSION_DTYPE, session_id,
        ["status", "started_at", "duration_minutes", "extensions_count",
         "appointment", "channel_name", "doctor_uid", "patient_uid"],
        as_dict=True,
    )
    if not row:
        frappe.throw("Session not found")
    return {
        "session_id":       session_id,
        "status":           row.status,
        "started_at":       str(row.started_at or ""),
        "duration_minutes": row.duration_minutes or DEFAULT_DURATION_MINUTES,
        "extensions_count": row.extensions_count or 0,
        "appointment":      row.appointment or "",
    }


# ─── start_session_timer ─────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def start_session_timer(session_id):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    if practitioner_user and practitioner_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if doc.status != "active":
        now = now_datetime()
        doc.db_set("status",     "active", update_modified=False)
        doc.db_set("started_at", now,      update_modified=False)
        frappe.db.commit()

    frappe.publish_realtime(
        event="video_session_started",
        message={"session_id": session_id, "started_at": str(doc.started_at or now_datetime())},
        room=f"video_{session_id}",
    )
    return {"session_id": session_id, "status": "active", "started_at": str(doc.started_at or "")}


# ─── end_session ─────────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def end_session(session_id, transcript=None):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    if not practitioner_user or practitioner_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Row-lock to prevent double end_session (concurrent calls from doctor + patient)
    frappe.db.sql(
        "SELECT name FROM `tabAirTook Video Session` WHERE name = %s FOR UPDATE",
        session_id,
    )

    if frappe.db.get_value(SESSION_DTYPE, session_id, "status") != "completed":
        now = now_datetime()
        doc.db_set("status",   "completed", update_modified=False)
        doc.db_set("ended_at", now,         update_modified=False)
        if transcript:
            doc.db_set("transcript", transcript, update_modified=False)
        doc.save(ignore_permissions=True)

        if doc.get("appointment"):
            frappe.db.set_value("Patient Appointment", doc.appointment, "status", "Closed")
        frappe.db.commit()

        # ── Credit doctor earnings ──────────────────────────────────────────
        if doc.get("practitioner") and doc.get("appointment"):
            try:
                from frappe.utils import flt as _flt
                appt = doc.appointment
                paid_amount = _flt(
                    frappe.db.get_value("Patient Appointment", appt, "paid_amount") or 0
                )
                if paid_amount <= 0:
                    paid_amount = _flt(
                        frappe.db.get_value("Patient Appointment", appt, "custom_payment_amount") or 0
                    )
                if paid_amount > 0:
                    commission_pct = 20.0
                    try:
                        cp = frappe.db.get_value(
                            "AirTook Setting", "platform_commission_pct", "setting_value"
                        )
                        if cp:
                            commission_pct = _flt(cp)
                    except Exception:
                        pass
                    doctor_pct = 100.0 - commission_pct
                    doctor_cut = round(paid_amount * doctor_pct / 100, 2)
                    if doctor_cut > 0:
                        frappe.db.sql(
                            "SELECT name FROM `tabHealthcare Practitioner` WHERE name = %s FOR UPDATE",
                            doc.practitioner,
                        )
                        current_earn = _flt(
                            frappe.db.get_value(
                                "Healthcare Practitioner", doc.practitioner,
                                "custom_earnings_balance"
                            ) or 0
                        )
                        frappe.db.set_value(
                            "Healthcare Practitioner", doc.practitioner,
                            "custom_earnings_balance", current_earn + doctor_cut,
                            update_modified=False,
                        )
                        frappe.db.commit()
                        frappe.logger().info(
                            f"end_session: credited ₦{doctor_cut} to {doc.practitioner} "
                            f"for session {doc.name}"
                        )
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"end_session: earnings credit failed for {doc.name}",
                )

        # ── Save transcript to Patient Encounter ─────────────────────────────
        if transcript and doc.get("appointment"):
            try:
                enc_name = frappe.db.get_value(
                    "Patient Encounter", {"appointment": doc.appointment}, "name"
                )
                if enc_name and frappe.db.has_column("Patient Encounter", "custom_transcript"):
                    frappe.db.set_value(
                        "Patient Encounter", enc_name,
                        "custom_transcript", transcript, update_modified=False,
                    )
                    frappe.db.commit()
            except Exception:
                pass

        # ── Enqueue AI consultation summary ──────────────────────────────────
        if doc.get("appointment"):
            try:
                import frappe.utils.background_jobs as _bj
                _bj.enqueue(
                    "airtook_core.api_dashboard.generate_consultation_summary",
                    appointment_name=doc.appointment,
                    queue="short",
                    timeout=60,
                )
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"end_session: failed to enqueue summary for {doc.name}",
                )

        # ── Stop cloud recording ──────────────────────────────────────────────
        try:
            _res_id = doc.get("cloud_recording_resource_id") or ""
            _sid    = doc.get("cloud_recording_sid") or ""
            if _res_id and _sid:
                _app_id = (
                    frappe.db.get_single_value("AirTook Configuration", "agora_app_id") or
                    frappe.conf.get("agora_app_id") or ""
                ).strip()
                _stop_cloud_recording(
                    _app_id,
                    doc.channel_name,
                    str(doc.doctor_uid),
                    _res_id,
                    _sid,
                )
                if frappe.db.has_column("AirTook Video Session", "cloud_recording_status"):
                    frappe.db.set_value(
                        "AirTook Video Session", session_id, "cloud_recording_status", "Stopped"
                    )
                    frappe.db.commit()
        except Exception as _e:
            frappe.log_error(f"Transcription stop failed: {_e}", "Agora Transcription")

    return {"session_id": doc.name, "status": "completed"}


# ─── extend_session ─────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def extend_session(session_id, extend_minutes):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")

    extend_minutes = int(extend_minutes or 0)
    if extend_minutes not in (15, 30):
        frappe.throw("Extension must be 15 or 30 minutes", frappe.ValidationError)

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)

    if doc.patient_user != frappe.session.user:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if doc.status != "active":
        frappe.throw("Session is not active")

    appt_type = None
    if doc.get("appointment"):
        appt_type = frappe.db.get_value("Patient Appointment", doc.appointment, "appointment_type")

    per_min   = _get_fee_per_minute(appt_type)
    gross_fee = round(per_min * extend_minutes, 2)
    discount  = round(gross_fee * EXTENSION_DISCOUNT_PCT / 100, 2)
    ext_fee   = round(gross_fee - discount, 2)

    patient_name = doc.patient or frappe.db.get_value(
        "Patient", {"user_id": frappe.session.user}, "name"
    )
    if not patient_name:
        frappe.throw("Patient record not found")

    from frappe.utils import flt
    wallet_balance = flt(frappe.db.get_value("Patient", patient_name, "custom_wallet_balance") or 0)
    if wallet_balance < ext_fee:
        return {
            "ok": False, "error": "insufficient_balance",
            "required": ext_fee, "balance": wallet_balance,
        }

    try:
        frappe.db.sql("SELECT name FROM `tabPatient` WHERE name = %s FOR UPDATE", patient_name)
        current_bal = flt(frappe.db.get_value("Patient", patient_name, "custom_wallet_balance") or 0)
        if current_bal < ext_fee:
            return {"ok": False, "error": "insufficient_balance", "required": ext_fee, "balance": current_bal}
        new_bal = current_bal - ext_fee
        frappe.db.set_value("Patient", patient_name, "custom_wallet_balance", new_bal, update_modified=False)
        frappe.db.commit()
        try:
            frappe.get_doc({
                "doctype": "AirTook Wallet Transaction",
                "patient": patient_name,
                "transaction_type": "Deduction",
                "amount": ext_fee,
                "balance_before": current_bal,
                "balance_after": new_bal,
                "reference_doctype": SESSION_DTYPE,
                "reference_name": session_id,
                "notes": f"Session extension {extend_minutes}min (20% discount)",
                "created_by_user": frappe.session.user,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass  # transaction log failure is non-fatal
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "extend_session wallet deduction failed")
        frappe.throw(f"Payment failed: {str(e)}")

    new_duration  = int(doc.duration_minutes or DEFAULT_DURATION_MINUTES) + extend_minutes
    new_ext_count = int(getattr(doc, "extensions_count", 0) or 0) + 1
    doc.db_set("duration_minutes",  new_duration,  update_modified=False)
    doc.db_set("extensions_count",  new_ext_count, update_modified=False)
    frappe.db.commit()

    return {
        "ok": True,
        "new_duration_minutes": new_duration,
        "extension_fee":        ext_fee,
        "discount_applied":     discount,
        "extensions_count":     new_ext_count,
    }


# ─── submit_rating ───────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def submit_rating(session_id, rating, comment=None, rated_by_role=None):
    _require_login()
    if not session_id:
        frappe.throw("Missing session_id")
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        frappe.throw("Rating must be an integer", frappe.ValidationError)
    if not (1 <= rating <= 5):
        frappe.throw("Rating must be between 1 and 5", frappe.ValidationError)

    doc = frappe.get_doc(SESSION_DTYPE, session_id, ignore_permissions=True)
    current_user      = frappe.session.user
    practitioner_user = _get_practitioner_user(doc.practitioner) if doc.practitioner else None
    is_practitioner   = bool(practitioner_user and practitioner_user == current_user)
    is_patient        = bool(doc.patient_user and doc.patient_user == current_user)

    if not is_practitioner and not is_patient:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if is_patient and doc.practitioner:
        try:
            import importlib
            core_api = importlib.import_module("airtook_core.api")
            core_api.submit_doctor_rating(
                doctor=doc.practitioner, rating=rating,
                patient_user=current_user, session=session_id,
                comment=comment or "", source="Video Call",
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "submit_rating failed")

    if is_practitioner:
        if frappe.db.has_column(SESSION_DTYPE, "practitioner_rating"):
            doc.db_set("practitioner_rating", rating, update_modified=False)
        if comment and frappe.db.has_column(SESSION_DTYPE, "practitioner_rating_comment"):
            doc.db_set("practitioner_rating_comment", comment, update_modified=False)
        frappe.db.commit()

    return {"session_id": session_id, "rating": rating}
