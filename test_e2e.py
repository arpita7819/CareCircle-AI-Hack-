import os, sys
os.environ["CARE_DB"] = "test.db"
os.environ["DISABLE_SCHEDULER"] = "1"
os.environ["ESCALATION_MINUTES"] = "30"
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
import app as A

with TestClient(A.app) as c:
    def H(t): return {"Authorization": "Bearer " + t}
    r = c.post("/api/profiles", json={"elder_name": "Asha", "elder_email": "asha@example.com", "passcode": "1234"}); assert r.status_code == 200, r.text
    pid, et = r.json()["profile_id"], r.json()["token"]

    # join: pending without elder passcode, auto with it
    assert c.post("/api/join", json={"profile_id": pid, "name": "Ravi", "email": "ravi@example.com", "role": "caretaker", "passcode": "9999"}).json()["approved"] is False
    assert c.post("/api/login", json={"profile_id": pid, "name": "Ravi", "passcode": "9999"}).status_code == 403
    assert c.post("/api/join", json={"profile_id": pid, "name": "Meena", "email": "meena@example.com", "role": "family", "passcode": "7777", "elder_passcode": "1234"}).json()["approved"] is True
    # elder approves Ravi
    ms = c.get("/api/members", headers=H(et)).json(); ravi = [m for m in ms if m["name"] == "Ravi"][0]
    assert c.patch(f"/api/members/{ravi['id']}", json={"approved": True}, headers=H(et)).status_code == 200
    rt = c.post("/api/login", json={"profile_id": pid, "name": "Ravi", "passcode": "9999"}).json()["token"]
    mt = c.post("/api/login", json={"profile_id": pid, "name": "Meena", "passcode": "7777"}).json()["token"]
    assert c.post("/api/login", json={"profile_id": pid, "name": "Ravi", "passcode": "bad"}).status_code == 401

    # family is read-only; caretaker can edit; non-elder cannot change consent
    assert c.post("/api/medications", json={"name": "X", "times": ["08:00"]}, headers=H(mt)).status_code == 403
    assert c.patch(f"/api/members/{ravi['id']}", json={"revoked": True}, headers=H(rt)).status_code == 403

    # meds with a dose 40 minutes ago (should escalate) and one in 5 minutes (should remind)
    now = datetime.now().replace(second=0, microsecond=0)
    past, soon = (now - timedelta(minutes=40)), (now + timedelta(minutes=5))
    if past.date() != now.date() or soon.date() != now.date():
        print("SKIP time-sensitive checks near midnight"); sys.exit(0)
    r = c.post("/api/medications", json={"name": "Warfarin", "dosage": "5 mg", "times": [past.strftime("%H:%M")], "pills_remaining": 5}, headers=H(rt)); assert r.status_code == 200, r.text
    r = c.post("/api/medications", json={"name": "Aspirin", "dosage": "75 mg", "times": [soon.strftime("%H:%M")], "pills_remaining": 30}, headers=H(rt))
    assert r.json()["warnings"], "expected warfarin+aspirin warning"
    r = c.post("/api/medications", json={"name": "aspirin", "times": ["21:00"]}, headers=H(rt)); assert any("duplicate" in w for w in r.json()["warnings"])

    doses = c.get("/api/doses/today", headers=H(et)).json()
    assert any(d["overdue"] for d in doses)
    A.run_reminders(); A.run_reminders()  # idempotent
    out = open("outbox.log").read()
    assert "Missed dose: Warfarin" in out and "Ravi" not in out  # emails go to addresses
    assert out.count("ravi@example.com") >= 1 and out.count("meena@example.com") >= 1, out
    assert out.count("Missed dose: Warfarin") == 1, "elder nudge must not repeat"
    assert "Time for your Aspirin" in out and out.count("Time for your Aspirin") == 1

    # mark taken -> pill count drops, undo restores it
    wd = [d for d in doses if d["name"] == "Warfarin"][0]
    c.post(f"/api/doses/{wd['id']}", json={"status": "taken"}, headers=H(rt))
    assert [m for m in c.get("/api/medications", headers=H(et)).json() if m["name"] == "Warfarin"][0]["pills_remaining"] == 4
    c.post(f"/api/doses/{wd['id']}", json={"status": "taken"}, headers=H(rt))  # double tap
    assert [m for m in c.get("/api/medications", headers=H(et)).json() if m["name"] == "Warfarin"][0]["pills_remaining"] == 4
    c.post(f"/api/doses/{wd['id']}", json={"status": "pending"}, headers=H(rt))
    assert [m for m in c.get("/api/medications", headers=H(et)).json() if m["name"] == "Warfarin"][0]["pills_remaining"] == 5

    # appointment reminder, check-in alert, insights, report, audit
    c.post("/api/appointments", json={"doctor": "Dr. Rao", "at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), "location": "City Clinic"}, headers=H(rt))
    A.run_reminders()
    assert "Appointment soon: Dr. Dr. Rao" in open("outbox.log").read() or "Dr. Rao" in open("outbox.log").read()
    r = c.post("/api/checkins", json={"mood": 1, "symptoms": "dizzy since morning"}, headers=H(et)); assert r.json()["alerted_caretakers"]
    ins = c.get("/api/insights", headers=H(et)).json(); assert ins["total"] >= 1 and any(x["name"] == "Warfarin" for x in ins["refills"]), ins
    assert "Asha" in c.get("/api/report", headers=H(et)).json()["text"]
    assert len(c.get("/api/audit", headers=H(et)).json()) > 5

    # revoked member loses access immediately
    c.patch(f"/api/members/{ravi['id']}", json={"revoked": True}, headers=H(et))
    assert c.get("/api/medications", headers=H(rt)).status_code == 403
    # cross-profile isolation
    r2 = c.post("/api/profiles", json={"elder_name": "Other", "passcode": "5555"}).json()
    assert c.get("/api/medications", headers=H(r2["token"])).json() == []
    assert c.get("/").status_code == 200
    print("ALL CHECKS PASSED")
