# CareCircle: Elderly Care & Medication Management Platform

A shared care ecosystem where the **elder stays in control** and caretakers and family stay informed.

## Run it

```bash
pip install fastapi uvicorn bcrypt pyjwt
python3 -m uvicorn app:app --port 8000
# open http://localhost:8000
```

Emails are written to `outbox.log` by default (great for demos). For real email, set:

```bash
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASS=app-password MAIL_FROM=you@gmail.com
```

Other settings: `ESCALATION_MINUTES` (default 30), `UPCOMING_MINUTES` (10), `SCHEDULER_INTERVAL` (30 s), `JWT_SECRET`.

Tests: `python3 test_e2e.py`

## Demo script (2 minutes)

1. Create an elder profile (note the profile number).
2. Join as a caretaker with the elder's passcode (instant) or without it (pending until the elder approves under **Family & access**).
3. As caretaker, add *Warfarin 08:00* then *Aspirin*: an interaction warning appears.
4. Add a dose time a few minutes ago, then wait for the scheduler (or call `POST /api/debug/run-reminders`) and check `outbox.log`: the elder is reminded, and after 30 minutes the caretaker and family are emailed.
5. In **Family & access**, make a relative view-only or revoke them. The change takes effect immediately and appears in **Activity**.

## Feature map vs. the challenge

| Requirement | Where |
|---|---|
| Shared profile, passcode access | `/api/profiles`, `/api/join`, `/api/login`; bcrypt-hashed passcodes, JWT sessions |
| View / add / edit / manage schedules | `/api/medications`, role-based `can_edit` |
| Track adherence | one-tap Taken / Undo, `/api/insights` |
| Monitor appointments | `/api/appointments` |
| Email reminders (upcoming, missed, appointments) | `run_reminders()` scheduler thread |
| **Elders at the centre** | Elder approves, restricts or revokes each member; full audit trail |

## Beyond a basic reminder app

- **Missed-dose escalation:** elder first, then caretakers and family after 30 minutes. Each email is sent once.
- **Elder-first UI:** large text, one-tap Taken, text-size toggle, English/Hindi labels, voice input (🎤) and read-aloud.
- **Adherence insights:** 7-day score, "you often miss the 21:00 dose" patterns, printable doctor report.
- **Refill forecasting:** pill counts drop as doses are taken; alerts go out when stock is low.
- **Interaction and duplicate warnings:** a small built-in list for the demo; swap `interaction_warnings()` for RxNorm or OpenFDA in production.
- **Daily check-in:** a low mood or a worrying symptom alerts caretakers.

## Known limits (prototype)

- Times use the server's local timezone; a production version should store a timezone per profile.
- The interaction list is a tiny demo set, not medical advice.
- SQLite and an in-process scheduler are fine for a demo; use Postgres and a job queue (BullMQ, Celery) to scale.
- Add rate limiting on login and HTTPS before real use.

## Ideas to add next

Prescription photo to schedule (OCR or an LLM), WhatsApp or SMS reminders, a PWA with push notifications, and per-language email templates.

## Deploy to Google Cloud Run

```bash
gcloud run deploy carecircle --source . --region asia-south1 --allow-unauthenticated \
  --no-cpu-throttling --min-instances 1 --max-instances 1 \
  --set-env-vars JWT_SECRET=$(openssl rand -hex 32)
```

`--no-cpu-throttling` and `--min-instances 1` keep the reminder scheduler running. SQLite lives in the container's `/tmp`, so data resets on redeploy; use Cloud SQL for persistence.
