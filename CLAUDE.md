# AirTook — Master Project Context for Claude Code

> This file is the authoritative reference for every Claude Code session on AirTook.
> Read it completely before touching any file. It supersedes all older CLAUDE.md files.

---

## 1. What AirTook Is

AirTook is a Nigerian B2C/B2B healthtech SaaS built on Frappe v16 / ERPNext v16 / Healthcare v16 (Marley Health fork). It gives patients an AI-first health companion (Aira), doctor video consultations, wallet-based payments, and a family health hub — all as a web portal with no native app.

Target market: Nigeria. Currency: NGN (₦). SMS provider: Termii. Payment: Paystack. Video: Agora RTC. AI: OpenAI.

---

## 2. Complete Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Frappe v16.9.0 |
| ERP | ERPNext v16.6.1 |
| Healthcare | Healthcare v16.0.4 (Marley Health fork) |
| Python | 3.14.2 |
| Node | v24.13.0 |
| Database | MariaDB (via Frappe) |
| Cache/Queue | Redis |
| Video | Agora RTC (agora_token_builder 1.0.0) |
| AI | OpenAI (Chat Completions + Responses API) |
| Payments | Paystack (custom, NOT Frappe Payments built-in) |
| SMS | Termii (`api.ng.termii.com`) |
| PDF | WeasyPrint (base64-embedded images) |
| LMS | Frappe LMS v2.45.2 (wellness courses) |
| Payments framework | Frappe Payments v0.0.1 |

---

## 3. GitHub Repositories

```
https://github.com/etukenbx/airtook_core
https://github.com/etukenbx/airtook_video
https://github.com/etukenbx/airtook_ai
```

All repos push to `main` branch.

---

## 4. Environment & Paths

```
Container name  : devcontainer-example-frappe-1
Bench path      : /workspace/development/benches/frappe-bench          (inside container)
Apps path       : /workspace/development/benches/frappe-bench/apps/    (inside container)
Site name       : airtook.local
Site config     : /workspace/development/benches/frappe-bench/sites/airtook.local/site_config.json
```

**Edit path (WSL, Claude Code edits here):**
```
/home/airtook/airtook/airtook_core/
/home/airtook/airtook/airtook_video/
/home/airtook/airtook/airtook_ai/
```

**Container path (what bench actually runs):**
```
/workspace/development/benches/frappe-bench/apps/airtook_core/
/workspace/development/benches/frappe-bench/apps/airtook_video/
/workspace/development/benches/frappe-bench/apps/airtook_ai/
```

---

## 5. Deploy Workflow — The Two-Path Sync

**CRITICAL:** Claude Code edits files in `/home/airtook/airtook/`. The bench runs inside the Docker container and reads from a completely separate path. **Every edit requires a `docker cp` to take effect.**

### Step-by-step (run in WSL terminal):

```bash
CONTAINER=devcontainer-example-frappe-1
BENCH=/workspace/development/benches/frappe-bench/apps

# 1. Copy changed files to container
docker cp /home/airtook/airtook/airtook_core/airtook_core/www/doctor.html \
  $CONTAINER:$BENCH/airtook_core/airtook_core/www/doctor.html

docker cp /home/airtook/airtook/airtook_core/airtook_core/api_dashboard.py \
  $CONTAINER:$BENCH/airtook_core/airtook_core/api_dashboard.py

# 2a. After any Python change:
docker exec $CONTAINER bash -c "cd /workspace/development/benches/frappe-bench && bench restart"

# 2b. After any JS/CSS change:
docker exec $CONTAINER bash -c "cd /workspace/development/benches/frappe-bench && bench build --app airtook_core"

# 2c. After any DocType change:
docker exec $CONTAINER bash -c "cd /workspace/development/benches/frappe-bench && bench --site airtook.local migrate"

# 2d. Clear cache (always safe to run):
docker exec $CONTAINER bash -c "cd /workspace/development/benches/frappe-bench && bench --site airtook.local clear-cache"
```

### Pattern by file type:
| File changed | Copy path pattern | Bench command |
|-------------|------------------|---------------|
| `*.py` (Python) | `airtook_core/airtook_core/` | `bench restart` |
| `*.html` (www page) | `airtook_core/airtook_core/www/` | `bench restart` (Jinja cache clears) |
| `*.html` (template) | `airtook_core/airtook_core/templates/` | `bench restart` |
| `*.js` (public) | `airtook_core/airtook_core/public/` | `bench build --app airtook_core` |
| DocType JSON | `airtook_core/airtook_core/airtook_core/doctype/` | `bench migrate` |

### Commit and push (after testing):
```bash
cd /home/airtook/airtook/airtook_core
git add -p          # stage only intended files
git commit -m "type: description"
git push origin main
```

---

## 6. Absolute Rules — Never Break These

1. **NEVER modify Frappe / ERPNext / Healthcare (Marley Health) core files.** All custom logic lives in `airtook_core`, `airtook_video`, or `airtook_ai` only.
2. **Never output site_config.json contents.** It contains live production credentials.
3. **Never suggest editing bench internals** or framework source files.
4. **Never assume a module, doctype, or field exists** without checking the apps/ directory or running `frappe.db.exists()` / `frappe.db.has_column()` first.
5. **Patient → User link field is `user_id`**, NOT `linked_user` or `user`. This is the Marley Health field name.
6. **`frappe.db.get_value()` does NOT accept `ignore_permissions=True` in Frappe v16.** Use `ignore_permissions` only on `get_all()`, `insert()`, `save()`, `get_doc()`.
7. **`{% extends base_template %}` does NOT work in Frappe v16 when `base_template` is set only in the Python controller.** Always hardcode the path: `{% extends "airtook_core/templates/airtook_base.html" %}` — OR use YAML front matter in the HTML file.
8. **Drug Prescription child table has NO `frequency` field.** Use `interval + ' ' + interval_uom`.
9. **Patient Encounter notes field is `encounter_comment`**, not `notes`. Symptoms = child table `Patient Encounter Symptom` → `complaint`. Diagnoses = `Patient Encounter Diagnosis` → `diagnosis`.
10. **Vital Signs doctype is named exactly `Vital Signs`**, not `Patient Vital Signs`.
11. **No `console.log`, `print()`, `alert()`, or `confirm()` in production code.**
12. **No inline JSON.stringify in HTML onclick attributes** without escaping double quotes: use `.replace(/"/g,'&quot;')`.
13. **No `custom_payment_amount` on Patient Appointment** — use the built-in `paid_amount` field.

---

## 7. All Web Pages (Portal Routes)

All patient/doctor pages live in `airtook_core/airtook_core/www/`. Base template: `airtook_core/templates/airtook_base.html`.

| URL | HTML File | Python File | Notes |
|-----|-----------|-------------|-------|
| `/` | `index.html` | `index.py` | Marketing home page |
| `/patient_access` | `patient_access.html` | `patient_access.py` | **Main patient UI (Aira-first)** — active |
| `/patient` | `patient.html` | `patient.py` | Legacy patient dashboard — keep until cleanup |
| `/patient-onboarding` | `patient-onboarding.html` | `patient-onboarding.py` | Post-registration onboarding chat |
| `/doctor` | `doctor.html` | `doctor.py` | Doctor dashboard (queue, encounters, earnings) |
| `/doctor-onboarding` | `doctor-onboarding.html` | `doctor-onboarding.py` | 4-step doctor signup |
| `/doctor/<slug>` | `doctor-profile.html` | `doctor-profile.py` | Public doctor profile |
| `/coach` | `coach.html` | `coach.py` | Coach dashboard |
| `/become-a-coach` | `become-a-coach.html` | `become-a-coach.py` | Coach application form |
| `/carepoint` | `carepoint.html` | `carepoint.py` | CarePoint (clinic) walk-in booking |
| `/video/<session_id>` | `airtook_video/www/video.html` | `video.py` | Agora video call page |
| `/verify-prescription` | `verify-prescription.html` | `verify-prescription.py` | Public Rx QR verification |
| `/verify-lab-request` | `verify-lab-request.html` | `verify-lab-request.py` | Public lab request verification |
| `/lab-results` | `lab-results.html` | `lab-results.py` | Lab results viewer |
| `/paystack_checkout` | `paystack_checkout.html` | `paystack_checkout.py` | Paystack hosted-page redirect |
| `/corporate` | `corporate.html` | `corporate.py` | Corporate admin dashboard |
| `/admin` | `admin.html` | `admin.py` | System admin dashboard |
| `/signup` | `signup.html` | `signup.py` | Patient registration |
| `/login` | `login.html` | `login.py` | Login page |
| `/forgot-password` | `forgot-password.html` | `forgot-password.py` | Password reset |
| `/help` | `help.html` | `help.py` | Help & FAQs |
| `/privacy` | `privacy.html` | `privacy.py` | Privacy Policy (NDPC) |
| `/terms` | `terms.html` | `terms.py` | Terms of Service |
| `/for-doctors` | `for-doctors.html` | `for-doctors.py` | Doctor recruitment landing |
| `/for-corporates` | `for-corporates.html` | `for-corporates.py` | Corporate sales landing |
| `/airtook-carepoints` | `airtook-carepoints.html` | `airtook_carepoints.py` | CarePoints directory |

### Route rules (hooks.py):
- `airtook_core`: `/doctor/<slug>` → `doctor-profile` page
- `airtook_video`: `/video/<session_id>` → `video` page (passes `session_id` to `video.py` via `view_args`)
- LMS: `/lms/*` — restricted to Course Creator + System Manager via `page_renderers.py`

### Auth guard logic (`patient_access.py`):
1. Guest → redirect `/login?redirect-to=/patient_access`
2. System Manager with no Patient record → redirect `/admin`
3. System Manager with Patient record → let through
4. Healthcare Practitioner with no Patient record → redirect `/doctor`
5. Healthcare Practitioner with Patient record → let through
6. All others (pure patients) → let through

---

## 8. Key Source Files

### airtook_core
| File | Purpose |
|------|---------|
| `airtook_core/api_dashboard.py` | ~11,800 lines — ALL patient/doctor/admin/subscription APIs |
| `airtook_core/api_pay.py` | Wallet, Paystack, JE, withdrawal, webhook APIs |
| `airtook_core/api_booking.py` | Core `book_consultation()` function |
| `airtook_core/notifications.py` | Email + Termii SMS notifications |
| `airtook_core/hooks.py` | Doc events, scheduler, route rules, fixtures |
| `airtook_core/page_renderers.py` | LMS access guard |
| `airtook_core/setup.py` | `after_install` hook |
| `airtook_core/templates/airtook_base.html` | Custom HTML base template (no Frappe navbar/footer) |

### airtook_ai
| File | Purpose |
|------|---------|
| `airtook_ai/airtook_ai/api.py` | `aira_chat()`, `_openai_triage()`, `_update_aira_summary()`, Aira history |

### airtook_video
| File | Purpose |
|------|---------|
| `airtook_video/airtook_video/api.py` | `create_session()`, `end_session()`, Agora token generation |
| `airtook_video/www/video.py` | Jinja context for video page, doctor-vs-patient redirect |
| `airtook_video/www/video.html` | Agora video call UI |

### Doctype paths (triple-nested):
```
airtook_core/airtook_core/airtook_core/doctype/<doctype_snake_case>/
airtook_ai/airtook_ai/airtook_ai/doctype/<doctype_snake_case>/
airtook_video/airtook_video/airtook_video/doctype/<doctype_snake_case>/
```

---

## 9. Custom Doctypes

### In airtook_core/doctype/ (fixtures, exported to code):
| DocType | Type | Purpose |
|---------|------|---------|
| AirTook Configuration | Single | Central API key store (OpenAI, Agora, Daily.co, Termii, Paystack public key) |
| AirTook Chat Message | Normal | Post-consult async chat between patient and doctor (72-hour window) |
| AirTook Consultation Fee | Normal | Fee schedule per appointment type |
| AirTook Family Link | Normal | Links family members under one primary account |
| AirTook Setting | Normal (key-value) | Runtime flags/settings (`maintenance_mode`, `wallet_migration_done`, etc.) |
| AirTook Wallet Transaction | Normal | Audit log of every wallet debit/credit |
| AirTook Withdrawal Request | Normal | Doctor payout requests |
| Coach Application | Normal | Coach signup applications |
| Doctor Rating | Normal | Patient ratings of doctors (post-call) |
| Paystack Settings | Single | Paystack public + secret key for LMS |
| Wellness Coach Profile | Normal | Approved coach records linked to Healthcare Practitioner |

### Created via `run_airtook_setup()` (not in doctype/ folder — recreated on demand):
| DocType | Type | Purpose |
|---------|------|---------|
| AirTook Plans | Single | Subscription plan config (prices, trial days, wallet credits) |
| AirTook Plan Config | Normal | Per-plan feature configuration (replaces AirTook Plans going forward) |
| AirTook Corporate | Normal | Corporate account records |
| AirTook Corporate Billing | Normal | Monthly invoices for corporates |
| AirTook Corporate Dependent | Normal | Employee dependents under corporate plan |
| AirTook Corporate Pricing Tier | Normal | Custom per-corporate pricing tiers |
| AirTook Video Session | Normal | Agora video call sessions (status: scheduled→active→completed/expired) |

### In airtook_ai/doctype/:
| DocType | Type | Purpose |
|---------|------|---------|
| AirTook Aira Message | Normal | Stores Aira chat history per patient |
| AirTook Medication Log | Normal | Medication tracking from Aira conversations |

### In airtook_video/doctype/ (fixture — legacy):
| DocType | Type | Purpose |
|---------|------|---------|
| Video Consultation Session | Normal | Legacy Daily.co session tracker — kept for fixture, not actively used |

---

## 10. Custom Fields on Marley Health Doctypes

### Patient (all `custom_` prefix)
| Field | Type | Purpose |
|-------|------|---------|
| `custom_wallet_balance` | Currency | Main spendable wallet balance |
| `custom_wallet_credit_balance` | Currency | Subscription credit balance (expiring) |
| `custom_wallet_credit_expiry` | Date | When subscription credit expires |
| `custom_push_notifications_enabled` | Check | Push notification preference |
| `custom_aira_insights_enabled` | Check | Aira proactive insights toggle |
| `custom_preferred_language` | Data | `en`/`pcm`/`yo`/`ig`/`ha` |
| `custom_plan` | Select | `Free` / `Plus` / `Family` |
| `custom_plan_status` | Select | `Active` / `Trialing` / `Expired` / `Cancelled` |
| `custom_trial_end_date` | Date | Trial expiry date |
| `custom_plan_start_date` | Date | Subscription start |
| `custom_plan_renewal_date` | Date | Next renewal date |
| `custom_paystack_subscription_code` | Data | Paystack subscription ID |
| `custom_paystack_email_token` | Data | Paystack email token (for cancel) |
| `custom_aira_messages_today` | Int | Daily Aira message count |
| `custom_aira_messages_date` | Date | Date the counter applies to |
| `custom_aira_summary` | Long Text | Rolling Aira conversation summary (AI-generated, 24h TTL) |
| `custom_aira_summary_updated` | Datetime | When summary was last generated |
| `custom_corporate_account` | Link → AirTook Corporate | Corporate employer |
| `custom_corporate_enrolled_date` | Date | Corporate enrollment date |
| `custom_corporate_consultations_this_month` | Int | Monthly corp consult counter |
| `custom_corporate_usage_month` | Data | Which month the counter applies to (`YYYY-MM`) |

### Healthcare Practitioner
| Field | Type | Purpose |
|-------|------|---------|
| `custom_is_available_online` | Check | Online/offline toggle for queue |
| `custom_bank_name` | Data | Bank name for payouts |
| `custom_account_number` | Data | Bank account number |
| `custom_account_name` | Data | Bank account name |
| `custom_earnings_balance` | Currency | Accumulated earnings pending withdrawal |
| `custom_license_no` | Data | Medical license number |
| `custom_years_experience` | Int | Years of experience |
| `custom_bio` | Small Text | Bio/About |
| `custom_signature_image` | Attach Image | Electronic signature (base64 in PDF) |
| `custom_slug` | Data | Public profile URL slug |
| `custom_profile_pitch` | Long Text | Professional pitch for public profile |
| `custom_languages` | Data | Languages spoken |
| `custom_hospital_affiliation` | Data | Hospital/clinic affiliation |
| `custom_education` | Small Text | Education & qualifications |
| `custom_profile_public` | Check | Profile publicly listed |
| `custom_average_rating` | Float | Average patient rating |
| `custom_total_reviews` | Int | Total review count |
| `custom_total_consultations` | Int | Career consultation count |
| `custom_price_override_enabled` | Check | Enable custom per-doctor pricing |
| `custom_fee_scheduled_15/30/45/60` | Currency | Custom fee for scheduled slots |
| `custom_fee_priority_15/30/45/60` | Currency | Custom fee for priority slots |

### Patient Appointment
| Field | Type | Purpose |
|-------|------|---------|
| `airtook_video_session` | Data | Linked AirTook Video Session name |
| `reminded` | Check | Whether appointment reminder was sent |
| `custom_is_carepoint_booking` | Check | Booked via CarePoint (not online) |

### Vital Signs
| Field | Type | Purpose |
|-------|------|---------|
| `custom_blood_sugar` | Float | Blood sugar in mmol/L |
| `custom_spo2` | Float | SpO₂ (%) — mapped to `spo2` in API responses |

### Healthcare Service Unit (CarePoint fields)
| Field | Type | Purpose |
|-------|------|---------|
| `custom_is_carepoint` | Check | Marks this unit as a CarePoint |
| `custom_location` | Data | Location/area name |
| `custom_state` | Data | State |
| `custom_opening_hours` | Data | Opening hours text |
| `custom_days_open` | Data | Days open text |

### User
| Field | Type | Purpose |
|-------|------|---------|
| `custom_assigned_carepoint` | Link → Healthcare Service Unit | Care Aide's assigned unit |

---

## 11. ERPNext Chart of Accounts

All created for company `AirTook` (abbreviated suffix `-AT` or similar):

| Account | Type | Purpose |
|---------|------|---------|
| Paystack Clearing | Asset | Transit for incoming Paystack funds |
| Patient Wallet Liability | Liability | Outstanding wallet balances owed to patients |
| Doctor Earnings Payable | Liability | Doctor earnings pending payout |
| Coach Earnings Payable | Liability | Coach earnings pending payout |
| Consultation Revenue | Income | Revenue from paid consultations |
| LMS Course Revenue | Income | Revenue from wellness course purchases |

### Journal Entry Rules (mandatory — every payment must flow through books):
- **Wallet top-up**: DR Paystack Clearing → CR Patient Wallet Liability
- **Booking deduction**: DR Patient Wallet Liability → CR Consultation Revenue + DR Doctor Earnings Payable
- **Cancellation refund**: DR Consultation Revenue + CR Doctor Earnings Payable → CR Patient Wallet Liability
- **Doctor payout**: DR Doctor Earnings Payable → CR Bank/Cash
- **LMS course purchase**: DR Patient Wallet Liability → CR LMS Course Revenue + DR Coach Earnings Payable

---

## 12. Subscription System

### Plans
| Plan | Price | Aira Limit | Monthly Wallet Credit | Discount | Trial |
|------|-------|-----------|----------------------|---------|-------|
| Free | ₦0 | 10 msgs/day | None | None | N/A |
| Plus | ₦1,999/mo | Unlimited | ₦500 (60-day expiry) | 20% off bookings | 14 days |
| Family | ₦3,999/mo | Unlimited | ₦1,500 (60-day expiry) | 20% off bookings | 14 days |

### Paystack Plan Codes (live):
- Plus: `PLN_pbmklz9bl45ddky`
- Family: `PLN_9gtjvye4jxrrpfs`

Stored in `AirTook Plans` Single doctype fields `plus_paystack_plan_code` / `family_paystack_plan_code`.

### Subscription lifecycle:
1. Patient calls `initiate_subscription(plan)` → Paystack subscription init link returned
2. Patient subscribes on Paystack
3. Paystack webhook `charge.success` hits `/api/method/airtook_core.airtook_core.api_pay.paystack_webhook`
4. `_webhook_charge_success()` credits wallet, sets `custom_plan=Plus/Family`, `custom_plan_status=Active`
5. `_issue_subscription_credit()` adds monthly wallet credit
6. Renewal: same webhook fires monthly
7. Cancel: `cancel_subscription()` → Paystack cancel API → sets `custom_plan_status=Cancelled`

### Wallet credit:
- Stored on Patient as `custom_wallet_credit_balance` (separate from `custom_wallet_balance`)
- Expires per `custom_wallet_credit_expiry` date
- `expire_wallet_credits()` cron job runs daily at 2 AM

---

## 13. Agora Video Configuration

### Architecture:
- Token type: AccessToken v2 (DynamicKey5), prefix `006`
- Library: `agora-token-builder==1.0.0` (`agora_token_builder.RtcTokenBuilder`)
- Manual fallback: `_generate_agora_token_manual()` in `airtook_video/airtook_video/api.py`
- Token TTL: 7200 seconds (2 hours)
- UIDs: 6-digit random integers (100000–999999)

### Credentials storage:
- **Primary**: `AirTook Configuration` Single doctype — fields `agora_app_id`, `agora_app_certificate`
- **Fallback**: `site_config.json` keys `agora_app_id`, `agora_app_certificate`

### Session flow:
1. `create_session(patient_appointment)` → creates `AirTook Video Session` doc, generates channel + UIDs + tokens, returns `doctor_join_url` + `patient_join_url`
2. Both URLs = `/video/<session_id>?ch=<channel>&uid=<uid>&tok=<token>&role=doctor/patient&apt=<appt>&dur=<mins>`
3. `video.py` detects if logged-in user is practitioner → redirects to `doctor_join_url`, else `patient_join_url`
4. `start_session_timer(session_id)` → sets status to `active`, publishes realtime event
5. `end_session(session_id)` → marks completed, credits doctor earnings, enqueues AI summary

### Session statuses: `scheduled` → `active` → `completed` (or `expired`)

---

## 14. Paystack Configuration

### Keys (never hardcode — always read from config):
- `paystack_secret_key` → `site_config.json` (or AirTook Configuration doctype)
- `paystack_public_key` → `site_config.json` (or AirTook Configuration doctype)

### For Frappe Cloud production:
Set keys in **Site Config** tab in Frappe Cloud dashboard (equivalent to `bench set-config`).
Primary source: AirTook Configuration doctype (reads first). Fallback: `frappe.conf.get(...)`.

### Webhook endpoint:
`/api/method/airtook_core.airtook_core.api_pay.paystack_webhook` (allow_guest=True)

### Webhook events handled:
- `charge.success` → wallet top-up or subscription credit
- `subscription.create` → mark subscription active
- `subscription.disable` → mark subscription cancelled/expired
- `transfer.success` → mark withdrawal completed
- `transfer.failed` → mark withdrawal failed

---

## 15. Termii SMS Configuration

**Library**: Direct HTTP to `https://api.ng.termii.com/api/sms/send`

**Config** (AirTook Configuration doctype or site_config.json):
- `termii_api_key` — API key
- `termii_sender_id` — Sender ID (must be pre-approved on Termii for DND channel, e.g. `AirTook`)
- `termii_channel` — defaults to `dnd`

**Main function**: `send_termii_sms(phone, message, channel=None)` in `notifications.py`

**When SMS is sent**:
- Appointment confirmation (booking)
- Appointment cancellation
- Appointment reminder (60 min before)
- Wallet top-up confirmation
- Prescription QR code
- Lab request QR code
- Doctor payout confirmation
- Corporate billing alert

---

## 16. OpenAI / Aira Configuration

**Config** (AirTook Configuration doctype → field `openai_api_key`, or `site_config.json` key `openai_api_key`):

**Model**: Configurable via `AirTook Configuration.openai_model` or `site_config.json` key `openai_model`. Default: `gpt-4o-mini`.

**Endpoints used**:
- Chat: `POST https://api.openai.com/v1/chat/completions`
- Responses API (structured output): `POST https://api.openai.com/v1/responses` (for `_openai_triage`)

**Key functions in `airtook_ai/airtook_ai/api.py`**:
- `aira_chat()` — main entry; allow_guest=True; 3 msg/day guest limit; unlimited for logged-in
- `_openai_triage()` — builds system prompt, calls OpenAI, parses structured JSON response
- `_update_aira_summary()` — generates rolling 24-hour summary of patient conversation history (enqueued every 20 messages)
- `_check_and_increment_aira_limit()` — enforces per-plan daily Aira message limit

**Guest access**: Up to 3 messages/day (tracked in Redis). Intentional product feature.

---

## 17. Scheduled Jobs (hooks.py scheduler_events)

| Schedule | Function | Purpose |
|----------|----------|---------|
| Hourly | `notifications.send_appointment_reminders` | Email both parties 60 min before appointment |
| Every 15 min | `api_dashboard.auto_expire_no_show_appointments` | Expire no-shows, refund wallet |
| Daily 7:30 AM | `api_dashboard.send_morning_checkins` | Morning Aira follow-up for yesterday's patients |
| Daily 9:00 AM | `api_dashboard.send_followup_checkins` | 24-hour follow-up via Termii SMS |
| Monday 8:00 AM | `api_dashboard.send_weekly_pattern_reports` | Weekly AI symptom pattern reports |
| Daily 6:00 AM | `api_pay.check_stale_withdrawals` | Reconcile approved withdrawals with no Paystack confirmation |
| Daily 2:00 AM | `api_dashboard.expire_wallet_credits` | Expire subscription credits past expiry date |
| Daily 8:00 AM | `api_dashboard.send_trial_expiry_reminders` | Warn patients 3 days before trial ends |
| Daily 8:00 AM | `api_dashboard.send_contract_expiry_reminders` | Warn corporate clients before contract end |
| 1st of month 00:00 | `api_dashboard.reset_corporate_monthly_usage` | Reset corporate monthly consult counters |

---

## 18. Document Events (hooks.py doc_events)

| DocType | Event | Handler |
|---------|-------|---------|
| Patient Encounter | on_submit | `api_dashboard.on_encounter_submit` — triggers PDF generation, sends Rx/lab QR via SMS |
| Patient Appointment | after_insert | `notifications.send_booking_confirmation` |
| Patient Appointment | on_cancel | `api_pay.process_cancellation_refund` + `notifications.send_appointment_cancelled` |
| LMS Enrollment | on_update | `api_dashboard.on_lms_enrollment_update` |

---

## 19. Key API Endpoints

All endpoints live in `airtook_core.airtook_core.api_dashboard` or `airtook_core.airtook_core.api_pay`.

### Patient
- `get_patient_dashboard` — full patient data bundle (allow_guest, guards internally)
- `update_patient_profile` — sex, dob, mobile, blood_group, allergies, preferences
- `save_onboarding` — blood group, allergies, medical history, emergency contact
- `register_patient` — new patient signup (allow_guest)
- `update_patient_relations` / `get_patient_relations` — emergency contacts
- `save_vital` / `save_vitals` — record vitals
- `get_patient_vitals` — fetch vitals list
- `request_account_deletion` / `export_patient_data` — GDPR compliance
- `get_subscription_status` / `initiate_subscription` / `cancel_subscription` / `start_free_trial`

### Doctor
- `get_doctor_dashboard` — queue + earnings + appointments
- `get_patient_detail(patient_id, appointment_id)` — full patient detail
- `get_patient_vitals_for_doctor` — latest vitals for encounter panel
- `set_practitioner_availability` — toggle online/offline
- `save_encounter(payload)` — write SOAP notes + prescriptions + labs
- `get_draft_encounter(appointment_id)` — resume in-progress encounter
- `save_practitioner_schedule` / `get_practitioner_schedule` — weekly availability
- `get_patient_brief(appointment_name)` — AI pre-consult summary
- `generate_consultation_summary(appointment_name)` — AI post-consult wrap-up → Communication
- `invite_doctor` / `complete_doctor_onboarding` — invite flow
- `get_doctor_signature` / `save_doctor_signature` / `clear_doctor_signature`
- `save_doctor_profile` / `save_doctor_pricing`
- `submit_doctor_rating` — patient rates doctor after call

### Payments (api_pay.py)
- `check_wallet_and_fee` — preflight fee check
- `initiate_topup(amount)` — create Paystack payment link
- `verify_topup(reference)` — confirm and credit wallet
- `book_with_payment` — deduct wallet + create appointment + Journal Entry
- `process_cancellation_refund` — refund on cancel (doc_event hook)
- `get_wallet_history` — audit trail
- `request_withdrawal(amount)` — doctor requests payout
- `approve_withdrawal` / `reject_withdrawal` / `cancel_withdrawal` — admin manages payouts
- `get_doctor_earnings` — doctor earnings breakdown
- `paystack_webhook` — Paystack event receiver (allow_guest=True)
- `get_paystack_public_key` — returns public key to frontend
- `create_paystack_transfer_recipient` — register bank details for transfer
- `get_platform_earnings(period)` — admin revenue analytics

### Video (airtook_video.airtook_video.api)
- `create_session(patient_appointment)` — create Agora session, return join URLs
- `get_session_status(session_id)` — poll session state
- `start_session_timer(session_id)` — doctor starts timer, sets status=active
- `end_session(session_id, transcript)` — close call, credit earnings, enqueue summary
- `extend_session(session_id, extend_minutes)` — 15 or 30 min extension (deducts wallet)
- `submit_rating(session_id, rating)` — post-call rating

### Aira (airtook_ai.airtook_ai.api)
- `aira_chat(message, reply_to, lang, context, viewing_patient)` — main chat (allow_guest)
- `get_aira_history(limit, viewing_patient)` — chat history
- `clear_aira_history` / `clear_conversation` — reset chat
- `get_departments` — list bookable departments
- `start_consultation(department)` — initiate booking from chat

### Admin
- `get_admin_dashboard` — platform stats
- `get_login_redirect` — role-based post-login redirect
- `get_csrf_token` — CSRF token for frontend
- `run_airtook_setup` — first-time/repair setup (creates all custom doctypes + fields)
- `run_e2e_smoke_test` — 12-step automated smoke test
- `run_full_audit` — audit all critical system components

### CarePoint
- `carepoint_book_consultation` — Care Aide books walk-in appointment (requires `Care Aide` role)
- `get_available_slots` / `get_booked_slots` — slot availability

### Wellness / LMS
- `enroll_in_program(program_name)` — enroll patient in wellness program
- `get_wellness_programs` / `get_recommended_programs` / `get_my_enrollments`
- `get_coach_dashboard_data` / `get_coach_earnings_detail`
- `save_wellness_course` — coach creates/updates course
- `approve_coach_application` / `reject_coach_application`
- `submit_coach_application` — public form (allow_guest)

### Post-Consult Chat
- `get_chat_eligibility(appointment_name)` — check 72-hour window
- `send_chat_message(appointment_name, message)` — send message
- `get_chat_thread(appointment_name)` — fetch thread
- `get_all_chat_threads(role)` — all threads for doctor/patient
- `get_unread_chat_count` — badge count

---

## 20. Color System

| Color | Hex | Usage |
|-------|-----|-------|
| Coral / Red | `#FF6B6B` / `#ff5a2f` | Urgency, emergency, action CTA |
| Purple | `#6d4aff` | Aira-only UI — NEVER use for non-Aira elements |
| Green | `#12a06b` | Success, Family plan |
| Off-white | `#FAFAFA` / `#f2f0ec` | Default page background |

---

## 21. airtook_base.html — Custom Base Template

Lives at `airtook_core/airtook_core/templates/airtook_base.html`. It is a **standalone HTML** template — no Frappe navbar, no ERPNext footer. Defines blocks: `title`, `head_include`, `content`, `page_content`.

**Important**: The `web_include_css` loop was intentionally removed (LMS/ERPNext bundles 404 and conflict with custom styles). The `web_include_js` loop is kept.

Pages using this template must:
- Either use YAML front matter: `base_template: "airtook_core/templates/airtook_base.html"`
- Or hardcode in HTML: `{% extends "airtook_core/templates/airtook_base.html" %}`
- **NOT**: `{% extends base_template %}` — this breaks in Frappe v16 when set in Python controller only.

---

## 22. Electronic Signature

- Stored as `custom_signature_image` (Attach Image) on Healthcare Practitioner
- Canvas pad in `doctor.html` (Settings tab) and `doctor-onboarding.html` (Step 4)
- Helper `_get_doctor_signature_html(practitioner)` reads file from disk → base64 `<img>` tag
- Embedded in `_rx_html()` and `_lab_html()` for WeasyPrint PDF generation
- URL logic: `/files/` → public; `/private/files/` → private

---

## 23. Family Hub

- `AirTook Family Link` doctype links family members under one primary patient
- Primary patient can switch to view/act as family member in the patient portal
- `viewing_patient` param on `aira_chat`, `get_aira_history`, etc. enables guardian view
- Guardian booking: doctor sees guardian name in post-consult chat
- Family Plan (subscription): up to 5 independent patient accounts share one subscription

---

## 24. CarePoints

- CarePoints are Healthcare Service Units with `custom_is_carepoint=1`
- Staffed by users with `Care Aide` role, assigned via `custom_assigned_carepoint` on User
- Walk-in patients are looked up or created via `find_or_create_patient`
- No wallet deduction for CarePoint bookings (`custom_is_carepoint_booking=1`)
- `/carepoint` page for patient-facing CarePoint booking

---

## 25. Current Status (as of 2026-05-16)

### Working:
- Patient registration, login, onboarding
- Aira AI chat (guest + logged-in), history, conversation context, rolling summary
- Patient dashboard — vitals, appointments, prescriptions, lab requests
- Doctor dashboard — queue, patient detail, encounters, prescriptions, lab requests
- Video consultations — Agora RTC end-to-end (patient joins + doctor joins)
- Wallet top-up via Paystack
- Appointment booking with wallet deduction + Journal Entry
- Cancellation + refund + Journal Entry
- Doctor payout requests + Termii SMS
- Doctor onboarding (4-step invite flow)
- Public doctor profiles (`/doctor/<slug>`)
- Patient post-consult chat (72-hour window)
- Subscription plans (Plus/Family) with Paystack recurring
- Corporate accounts (AirTook Corporate doctype)
- LMS wellness programs (restricted to Course Creator)
- Coach applications and dashboard
- PDF prescription and lab request generation (WeasyPrint)
- Prescription and lab request QR verification pages
- Lab results viewer
- Appointment reminders, booking confirmations, cancellation SMS
- Electronic signature on prescriptions

### Fixed in the 2026-05-16 session:
- `/lab-results`, `/verify-lab-request`, `/verify-prescription` — `{% extends base_template %}` 500 error → hardcoded path
- Doctor join button never showing — API was querying old `Video Consultation Session` (Daily.co), not `AirTook Video Session` (Agora); status strings wrong; URL source wrong
- Doctor was joining as patient — `video.py` now detects practitioner user and redirects to `doctor_join_url`
- Doctor CSS 404s — `lms.bundle.css` / `erpnext-web.bundle.css` — removed `web_include_css` loop from `airtook_base.html`
- Patient onboarding stuck at sex/gender chips — `JSON.stringify()` inside `onclick="..."` created malformed HTML; fixed with `.replace(/"/g,'&quot;')`

### Known issues (not yet fixed):
- `carepoint_book_consultation` returns 417 — endpoint exists but may have a config issue; needs investigation
- Artifact preview in `patient_access.html` shows raw HTML instead of rendered content — `showArtifact()` uses `escHtml()` which escapes the HTML; needs to sanitise and render
- Aira `_openai_triage` may still have edge cases where the structured output doesn't parse cleanly on very long messages

---

## 26. Claude / Claude Code Workflow

### How this project is developed:
1. All editing happens in WSL on the host at `/home/airtook/airtook/`
2. Claude Code runs in WSL, edits files there
3. After every edit: `docker cp` syncs to the container
4. `bench restart` / `bench build` / `bench migrate` applies changes

### What Claude must do before every session:
1. Read this CLAUDE.md fully
2. Read any other relevant CLAUDE.md files (airtook_video/CLAUDE.md, airtook_ai/CLAUDE.md)
3. Read the specific files being modified before making any edits
4. Verify that field names, doctype names, and function signatures exist in the current code before referencing them

### What Claude must NOT do:
- Never create a file without reading the edit target first
- Never guess at a field name without grep-verifying it exists
- Never skip the docker cp + bench restart step
- Never commit without the user's explicit request
- Never output site_config.json contents

### Commit message format:
```
type: brief description

Types: feat | fix | refactor | docs | chore
```

---

## 27. Post-Launch / Phase 10 Pending Items

1. **Artifact rendering in patient_access.html** — prescriptions/lab PDFs preview as raw HTML; fix `showArtifact()` to safely render HTML content
2. **CarePoint 417 error** — debug `carepoint_book_consultation` to find root cause
3. **ERPNext GL integration audit** — verify every payment flow creates a correct Journal Entry in all edge cases (subscription credit spend, corporate billing)
4. **Doctor public profile SEO** — add `<meta>` description + Open Graph tags to `/doctor/<slug>`
5. **Push notifications** — `custom_push_notifications_enabled` field exists but notification delivery not wired
6. **In-app chat read receipts** — `is_read` field on AirTook Chat Message exists; unread count badge working; read-mark on open not fully tested
7. **Corporate billing PDF** — monthly invoice generation for corporate clients
8. **Subscription dunning** — handle `invoice.payment_failed` Paystack webhook (currently not handled)
9. **App lock PIN** — PIN system code exists; verify all flows tested
10. **Health journal** — `includes_journal` flag on plan config exists; feature implementation pending
11. **Remove legacy `/patient` page** — after Week 4 final cleanup; currently kept as backup
12. **Frappe Cloud production deploy** — final configuration of all API keys in Frappe Cloud Site Config dashboard

---

## 28. Running the Setup Script

After a fresh install or to repair missing doctypes/fields:

```bash
# In bench console (inside container):
bench execute airtook_core.airtook_core.api_dashboard.run_airtook_setup

# Or via API (System Manager only):
curl -X POST https://airtook.local/api/method/airtook_core.airtook_core.api_dashboard.run_airtook_setup \
  -H "X-Frappe-CSRF-Token: <token>" \
  --cookie "sid=<session>"
```

This creates all custom doctypes, custom fields, plan codes, and default settings. Safe to re-run — idempotent (checks existence before creating).

---

## 29. Marley Health (Healthcare Module) Reference

Marley Health is the Healthcare app fork used by AirTook. Reference path (read before creating new doctypes/fields):
```
/home/airtook/airtook/healthcare_ref/
```

Key Marley Health doctypes and their confirmed field names:
- **Drug Prescription** (child of Patient Encounter): `drug_name`, `dosage`, `interval`, `interval_uom`, `period`, `dosage_form` — NO `frequency` field
- **Patient Encounter Symptom** (child): `complaint`
- **Patient Encounter Diagnosis** (child): `diagnosis`
- **Patient Encounter**: notes = `encounter_comment` (Small Text)
- **Vital Signs**: `temperature`, `pulse`, `respiratory_rate`, `bp_systolic`, `bp_diastolic`, `height`, `weight`, `bmi` + custom `custom_blood_sugar`, `custom_spo2`
- **Patient**: `user_id` links to Frappe User (NOT `linked_user` or `user`)
