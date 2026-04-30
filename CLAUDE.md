# AirTook — Frappe Project Context

## Environment
- Frappe: v16.9.0 | ERPNext: v16.6.1 | Healthcare: v16.0.4
- Python: 3.14.2 | Node: v24.13.0
- Container: devcontainer-example-frappe-1
- Site: airtook.local
- Bench path: /workspace/development/benches/frappe-bench

## Apps
- airtook_core — core doctypes, logic, patient records
- airtook_video — video consultation (Daily.co integration)
- airtook_ai — AI assistant (Aira), OpenAI integration

## GitHub
- https://github.com/etukenbx/airtook_core
- https://github.com/etukenbx/airtook_video
- https://github.com/etukenbx/airtook_ai

## Key Rules
- NEVER modify frappe/erpnext/healthcare core files
- All custom logic lives in airtook_core, airtook_video, or airtook_ai only
- After any Python change: bench restart
- After any JS/CSS change: bench build --app [appname]
- After any DocType change: bench migrate
- Use search-and-replace style edits — show exact file path + exact lines to change

## AI Assistant
- Named: Aira
- Powered by: OpenAI API
- Lives in: airtook_ai app

## Integrations
- Video: Daily.co
- Payments: Paystack
- AI: OpenAI

## Do Not
- Never output site_config.json contents
- Never suggest editing bench or frappe internals
- Never assume a module exists without checking apps/ first

## Video Session Lifecycle — airtook_video/airtook_video/api.py
- `end_session(session_id)` — the main session-close function; it:
  1. Closes the Daily.co room
  2. Marks the Patient Appointment as completed
  3. Calls `generate_consultation_summary()` (in airtook_core) to save an AI wrap-up as a Communication
  4. Credits doctor earnings: appends consultation fee (doctor's cut) to `custom_earnings_balance` on Healthcare Practitioner
- Earnings credit happens synchronously inside `end_session()`, NOT deferred or async

## Key Doctypes
- `Video Consultation Session` — custom doctype tracking each call; linked to Patient Appointment
- Session state: `scheduled` → `active` → `completed` (or `expired`)
