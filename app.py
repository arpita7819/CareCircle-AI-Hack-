"""CareCircle - Elderly Care & Medication Management Platform (prototype).

FastAPI + SQLite. Passcode-based role access, medication schedules, dose logs,
appointments, elder consent controls, audit trail, email reminders with
missed-dose escalation, adherence insights and refill forecasting.
"""
import os
import re
import sqlite3
import smtplib
import threading
import time
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, date
from email.message import EmailMessage
from typing import List, Optional

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("CARE_DB", "carecircle.db")
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_hex(32)
SMTP_HOST = os.environ.get("SMTP_HOST")  # if unset, emails go to outbox.log
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
MAIL_FROM = os.environ.get("MAIL_FROM", "carecircle@localhost")
ESCALATION_MINUTES = int(os.environ.get("ESCALATION_MINUTES", "30"))
UPCOMING_MINUTES = int(os.environ.get("UPCOMING_MINUTES", "10"))
SCHEDULER_INTERVAL = int(os.environ.get("SCHEDULER_INTERVAL", "30"))

ROLES = ("elder", "caretaker", "family")

app = FastAPI(title="CareCircle")


# ---------------------------------------------------------------- database
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, language TEXT DEFAULT 'en',
  created_at TEXT);
CREATE TABLE IF NOT EXISTS members(
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id),
  name TEXT NOT NULL, email TEXT, role TEXT NOT NULL,
  passcode_hash TEXT NOT NULL, can_edit INTEGER DEFAULT 1,
  approved INTEGER DEFAULT 1, revoked INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS medications(
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id),
  name TEXT NOT NULL, dosage TEXT, instructions TEXT,
  times TEXT NOT NULL,            -- comma separated HH:MM
  start_date TEXT, end_date TEXT,
  pills_remaining INTEGER, pills_per_dose INTEGER DEFAULT 1,
  active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS dose_logs(
  id INTEGER PRIMARY KEY, medication_id INTEGER NOT NULL REFERENCES medications(id),
  scheduled_at TEXT NOT NULL,     -- local ISO 'YYYY-MM-DDTHH:MM'
  status TEXT DEFAULT 'pending',  -- pending|taken|skipped
  taken_at TEXT, logged_by INTEGER,
  reminded INTEGER DEFAULT 0, escalated INTEGER DEFAULT 0,
  UNIQUE(medication_id, scheduled_at));
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id),
  doctor TEXT NOT NULL, location TEXT, notes TEXT,
  at TEXT NOT NULL, reminded_day INTEGER DEFAULT 0, reminded_hour INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS checkins(
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id),
  mood INTEGER, symptoms TEXT, at TEXT, logged_by INTEGER);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, profile_id INTEGER, member_id INTEGER,
  action TEXT, detail TEXT, at TEXT);
"""


def init_db():
    with db() as c:
        c.executescript(SCHEMA)


def now():
    return datetime.now().replace(second=0, microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def log(c, profile_id, member_id, action, detail=""):
    c.execute("INSERT INTO audit(profile_id,member_id,action,detail,at) VALUES(?,?,?,?,?)",
              (profile_id, member_id, action, detail, iso(now())))


# -------------------------------------------------------------------- auth
def hash_pw(p):
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def check_pw(p, h):
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def make_token(m):
    return jwt.encode({"mid": m["id"], "pid": m["profile_id"], "role": m["role"],
                       "exp": datetime.utcnow() + timedelta(hours=12)},
                      JWT_SECRET, algorithm="HS256")


class Me(BaseModel):
    id: int
    profile_id: int
    role: str
    name: str
    can_edit: bool


def current_member(authorization: Optional[str] = Header(None)) -> Me:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    try:
        data = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    with db() as c:
        m = c.execute("SELECT * FROM members WHERE id=?", (data["mid"],)).fetchone()
    if not m or m["revoked"] or not m["approved"]:
        raise HTTPException(403, "Access revoked or not yet approved by the elder")
    return Me(id=m["id"], profile_id=m["profile_id"], role=m["role"], name=m["name"],
              can_edit=bool(m["can_edit"]) or m["role"] == "elder")


def need_edit(me: Me = Depends(current_member)) -> Me:
    if not me.can_edit:
        raise HTTPException(403, "Read-only access")
    return me


def need_elder(me: Me = Depends(current_member)) -> Me:
    if me.role != "elder":
        raise HTTPException(403, "Only the elder can do this")
    return me


# ------------------------------------------------------------------ models
class ProfileIn(BaseModel):
    elder_name: str = Field(min_length=1)
    elder_email: Optional[str] = None
    passcode: str = Field(min_length=4)
    language: str = "en"


class JoinIn(BaseModel):
    profile_id: int
    name: str = Field(min_length=1)
    email: Optional[str] = None
    role: str
    passcode: str = Field(min_length=4)           # the passcode this member will use
    elder_passcode: Optional[str] = None          # elder passcode or invite -> auto-approve


class LoginIn(BaseModel):
    profile_id: int
    name: str
    passcode: str


class MedIn(BaseModel):
    name: str = Field(min_length=1)
    dosage: Optional[str] = None
    instructions: Optional[str] = None
    times: List[str]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    pills_remaining: Optional[int] = None
    pills_per_dose: int = 1


class ApptIn(BaseModel):
    doctor: str = Field(min_length=1)
    location: Optional[str] = None
    notes: Optional[str] = None
    at: str


class CheckinIn(BaseModel):
    mood: int = Field(ge=1, le=5)
    symptoms: Optional[str] = None


class MemberUpdate(BaseModel):
    can_edit: Optional[bool] = None
    approved: Optional[bool] = None
    revoked: Optional[bool] = None


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def clean_times(times):
    out = sorted({t.strip() for t in times})
    if not out or any(not TIME_RE.match(t) for t in out):
        raise HTTPException(422, "times must be HH:MM (24h)")
    return out


# --------------------------------------------------------------------- auth api
@app.post("/api/profiles")
def create_profile(p: ProfileIn):
    with db() as c:
        cur = c.execute("INSERT INTO profiles(name,email,language,created_at) VALUES(?,?,?,?)",
                        (p.elder_name, p.elder_email, p.language, iso(now())))
        pid = cur.lastrowid
        c.execute("INSERT INTO members(profile_id,name,email,role,passcode_hash,created_at)"
                  " VALUES(?,?,?,?,?,?)",
                  (pid, p.elder_name, p.elder_email, "elder", hash_pw(p.passcode), iso(now())))
        mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        log(c, pid, mid, "profile_created", p.elder_name)
        m = c.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    return {"profile_id": pid, "token": make_token(m)}


@app.post("/api/join")
def join(j: JoinIn):
    """Caretaker/family join. They stay 'pending' until the elder approves,
    unless they present the elder's passcode (in-person trust)."""
    if j.role not in ("caretaker", "family"):
        raise HTTPException(422, "role must be caretaker or family")
    with db() as c:
        elder = c.execute("SELECT * FROM members WHERE profile_id=? AND role='elder'",
                          (j.profile_id,)).fetchone()
        if not elder:
            raise HTTPException(404, "Profile not found")
        if c.execute("SELECT 1 FROM members WHERE profile_id=? AND lower(name)=lower(?)",
                     (j.profile_id, j.name)).fetchone():
            raise HTTPException(409, "A member with that name already exists")
        approved = 1 if (j.elder_passcode and check_pw(j.elder_passcode, elder["passcode_hash"])) else 0
        can_edit = 1 if j.role == "caretaker" else 0
        c.execute("INSERT INTO members(profile_id,name,email,role,passcode_hash,can_edit,approved,created_at)"
                  " VALUES(?,?,?,?,?,?,?,?)",
                  (j.profile_id, j.name, j.email, j.role, hash_pw(j.passcode),
                   can_edit, approved, iso(now())))
        log(c, j.profile_id, None, "member_joined",
            f"{j.name} ({j.role}) {'auto-approved' if approved else 'awaiting approval'}")
    return {"approved": bool(approved),
            "message": "Joined." if approved else "Waiting for the elder to approve your access."}


@app.post("/api/login")
def login(l: LoginIn):
    with db() as c:
        m = c.execute("SELECT * FROM members WHERE profile_id=? AND lower(name)=lower(?)",
                      (l.profile_id, l.name)).fetchone()
    if not m or not check_pw(l.passcode, m["passcode_hash"]):
        raise HTTPException(401, "Wrong name or passcode")
    if m["revoked"]:
        raise HTTPException(403, "Access was revoked by the elder")
    if not m["approved"]:
        raise HTTPException(403, "Still waiting for the elder to approve you")
    with db() as c:
        log(c, m["profile_id"], m["id"], "login", "")
    return {"token": make_token(m), "role": m["role"], "name": m["name"],
            "profile_id": m["profile_id"]}


@app.get("/api/me")
def me_info(me: Me = Depends(current_member)):
    with db() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (me.profile_id,)).fetchone()
    return {**me.model_dump(), "elder_name": p["name"], "language": p["language"]}


# ----------------------------------------------------------- consent / members
@app.get("/api/members")
def members(me: Me = Depends(current_member)):
    with db() as c:
        rows = c.execute("SELECT id,name,email,role,can_edit,approved,revoked FROM members"
                         " WHERE profile_id=? ORDER BY id", (me.profile_id,)).fetchall()
    return [dict(r) for r in rows]


@app.patch("/api/members/{mid}")
def update_member(mid: int, u: MemberUpdate, me: Me = Depends(need_elder)):
    with db() as c:
        m = c.execute("SELECT * FROM members WHERE id=? AND profile_id=?",
                      (mid, me.profile_id)).fetchone()
        if not m:
            raise HTTPException(404, "Not found")
        if m["role"] == "elder":
            raise HTTPException(400, "Cannot change the elder")
        for field, val in u.model_dump(exclude_none=True).items():
            c.execute(f"UPDATE members SET {field}=? WHERE id=?", (int(val), mid))
            log(c, me.profile_id, me.id, "consent_change", f"{m['name']}: {field}={val}")
    return {"ok": True}


@app.get("/api/audit")
def audit(me: Me = Depends(current_member)):
    with db() as c:
        rows = c.execute("""SELECT a.at,a.action,a.detail,m.name AS who FROM audit a
            LEFT JOIN members m ON m.id=a.member_id WHERE a.profile_id=?
            ORDER BY a.id DESC LIMIT 100""", (me.profile_id,)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ medications
def med_row(r):
    d = dict(r)
    d["times"] = r["times"].split(",")
    return d


@app.get("/api/medications")
def list_meds(me: Me = Depends(current_member)):
    with db() as c:
        rows = c.execute("SELECT * FROM medications WHERE profile_id=? AND active=1 ORDER BY name",
                         (me.profile_id,)).fetchall()
    out = []
    for r in rows:
        d = med_row(r)
        d["days_left"] = days_left(r)
        out.append(d)
    return out


def days_left(r):
    if r["pills_remaining"] is None:
        return None
    per_day = max(1, len(r["times"].split(",")) * (r["pills_per_dose"] or 1))
    return r["pills_remaining"] // per_day


@app.post("/api/medications")
def add_med(m: MedIn, me: Me = Depends(need_edit)):
    times = clean_times(m.times)
    with db() as c:
        warnings = interaction_warnings(c, me.profile_id, m.name)
        cur = c.execute("""INSERT INTO medications(profile_id,name,dosage,instructions,times,
            start_date,end_date,pills_remaining,pills_per_dose) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (me.profile_id, m.name, m.dosage, m.instructions, ",".join(times),
                         m.start_date or date.today().isoformat(), m.end_date,
                         m.pills_remaining, m.pills_per_dose))
        log(c, me.profile_id, me.id, "med_added", f"{m.name} {m.dosage or ''} at {','.join(times)}")
    return {"id": cur.lastrowid, "warnings": warnings}


@app.put("/api/medications/{mid}")
def edit_med(mid: int, m: MedIn, me: Me = Depends(need_edit)):
    times = clean_times(m.times)
    with db() as c:
        if not c.execute("SELECT 1 FROM medications WHERE id=? AND profile_id=?",
                         (mid, me.profile_id)).fetchone():
            raise HTTPException(404, "Not found")
        c.execute("""UPDATE medications SET name=?,dosage=?,instructions=?,times=?,start_date=?,
            end_date=?,pills_remaining=?,pills_per_dose=? WHERE id=?""",
                  (m.name, m.dosage, m.instructions, ",".join(times), m.start_date, m.end_date,
                   m.pills_remaining, m.pills_per_dose, mid))
        log(c, me.profile_id, me.id, "med_edited", m.name)
    return {"ok": True}


@app.delete("/api/medications/{mid}")
def delete_med(mid: int, me: Me = Depends(need_edit)):
    with db() as c:
        r = c.execute("SELECT name FROM medications WHERE id=? AND profile_id=?",
                      (mid, me.profile_id)).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        c.execute("UPDATE medications SET active=0 WHERE id=?", (mid,))
        log(c, me.profile_id, me.id, "med_removed", r["name"])
    return {"ok": True}


# Small built-in interaction/duplicate list for the demo. Swap for RxNorm/OpenFDA in production.
INTERACTIONS = [
    ({"warfarin"}, {"aspirin", "ibuprofen", "naproxen"}, "Bleeding risk is higher."),
    ({"lisinopril", "enalapril", "ramipril"}, {"spironolactone", "potassium"},
     "Blood potassium can rise too high."),
    ({"metformin"}, {"alcohol"}, "Risk of lactic acidosis."),
    ({"sildenafil"}, {"nitroglycerin", "isosorbide"}, "Blood pressure can drop dangerously."),
    ({"simvastatin"}, {"clarithromycin", "erythromycin"}, "Higher risk of muscle damage."),
    ({"ibuprofen", "naproxen", "diclofenac"}, {"aspirin"}, "Stomach bleeding risk is higher."),
]


def interaction_warnings(c, profile_id, new_name):
    new = new_name.lower().strip()
    existing = [r["name"].lower().strip() for r in c.execute(
        "SELECT name FROM medications WHERE profile_id=? AND active=1", (profile_id,))]
    out = []
    if new in existing:
        out.append(f"{new_name} is already on the list - possible duplicate.")
    for a, b, msg in INTERACTIONS:
        for e in existing:
            if (new in a and e in b) or (new in b and e in a):
                out.append(f"{new_name} + {e}: {msg} Ask a doctor or pharmacist.")
    return out


@app.get("/api/interaction-check")
def check(name: str, me: Me = Depends(current_member)):
    with db() as c:
        return {"warnings": interaction_warnings(c, me.profile_id, name)}


# -------------------------------------------------------------------- dose logs
def ensure_doses(c, profile_id, day: date):
    """Materialise pending dose rows for a given day."""
    meds = c.execute("SELECT * FROM medications WHERE profile_id=? AND active=1",
                     (profile_id,)).fetchall()
    for m in meds:
        if m["start_date"] and day.isoformat() < m["start_date"]:
            continue
        if m["end_date"] and day.isoformat() > m["end_date"]:
            continue
        for t in m["times"].split(","):
            c.execute("INSERT OR IGNORE INTO dose_logs(medication_id,scheduled_at) VALUES(?,?)",
                      (m["id"], f"{day.isoformat()}T{t}"))


@app.get("/api/doses/today")
def doses_today(me: Me = Depends(current_member)):
    today = date.today()
    with db() as c:
        ensure_doses(c, me.profile_id, today)
        rows = c.execute("""SELECT d.id,d.scheduled_at,d.status,d.taken_at,m.name,m.dosage,
            m.instructions FROM dose_logs d JOIN medications m ON m.id=d.medication_id
            WHERE m.profile_id=? AND m.active=1 AND d.scheduled_at LIKE ?
            ORDER BY d.scheduled_at""", (me.profile_id, today.isoformat() + "%")).fetchall()
    cur = iso(now())
    out = []
    for r in rows:
        d = dict(r)
        d["overdue"] = r["status"] == "pending" and r["scheduled_at"] < cur
        out.append(d)
    return out


class DoseUpdate(BaseModel):
    status: str  # taken|skipped|pending


@app.post("/api/doses/{did}")
def mark_dose(did: int, u: DoseUpdate, me: Me = Depends(need_edit)):
    if u.status not in ("taken", "skipped", "pending"):
        raise HTTPException(422, "bad status")
    with db() as c:
        d = c.execute("""SELECT d.*,m.profile_id,m.name,m.pills_per_dose,m.pills_remaining
            FROM dose_logs d JOIN medications m ON m.id=d.medication_id WHERE d.id=?""",
                      (did,)).fetchone()
        if not d or d["profile_id"] != me.profile_id:
            raise HTTPException(404, "Not found")
        c.execute("UPDATE dose_logs SET status=?,taken_at=?,logged_by=? WHERE id=?",
                  (u.status, iso(now()) if u.status == "taken" else None, me.id, did))
        # adjust pill count only on a real state change into/out of 'taken'
        if d["pills_remaining"] is not None:
            delta = 0
            if u.status == "taken" and d["status"] != "taken":
                delta = -(d["pills_per_dose"] or 1)
            elif u.status != "taken" and d["status"] == "taken":
                delta = d["pills_per_dose"] or 1
            if delta:
                c.execute("UPDATE medications SET pills_remaining=MAX(0,pills_remaining+?) WHERE id=?",
                          (delta, d["medication_id"]))
        log(c, me.profile_id, me.id, f"dose_{u.status}", f"{d['name']} @ {d['scheduled_at']}")
    return {"ok": True}


# ----------------------------------------------------------------- appointments
@app.get("/api/appointments")
def list_appts(me: Me = Depends(current_member)):
    with db() as c:
        rows = c.execute("SELECT * FROM appointments WHERE profile_id=? AND at>=? ORDER BY at",
                         (me.profile_id, iso(now() - timedelta(hours=2)))).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/appointments")
def add_appt(a: ApptIn, me: Me = Depends(need_edit)):
    try:
        datetime.strptime(a.at, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(422, "at must be YYYY-MM-DDTHH:MM")
    with db() as c:
        cur = c.execute("INSERT INTO appointments(profile_id,doctor,location,notes,at) VALUES(?,?,?,?,?)",
                        (me.profile_id, a.doctor, a.location, a.notes, a.at))
        log(c, me.profile_id, me.id, "appt_added", f"{a.doctor} {a.at}")
    return {"id": cur.lastrowid}


@app.delete("/api/appointments/{aid}")
def del_appt(aid: int, me: Me = Depends(need_edit)):
    with db() as c:
        cur = c.execute("DELETE FROM appointments WHERE id=? AND profile_id=?", (aid, me.profile_id))
        if not cur.rowcount:
            raise HTTPException(404, "Not found")
        log(c, me.profile_id, me.id, "appt_removed", str(aid))
    return {"ok": True}


# --------------------------------------------------------------------- check-ins
@app.post("/api/checkins")
def add_checkin(ci: CheckinIn, me: Me = Depends(need_edit)):
    with db() as c:
        c.execute("INSERT INTO checkins(profile_id,mood,symptoms,at,logged_by) VALUES(?,?,?,?,?)",
                  (me.profile_id, ci.mood, ci.symptoms, iso(now()), me.id))
        log(c, me.profile_id, me.id, "checkin", f"mood {ci.mood}")
        concerning = ci.mood <= 2 or bool(ci.symptoms and re.search(
            r"chest|breath|dizz|faint|fall|fell|confus|severe", ci.symptoms, re.I))
        if concerning:
            names = notify_group(c, me.profile_id, ["caretaker", "family"],
                                 "Health check-in needs attention",
                                 f"Mood {ci.mood}/5. Symptoms: {ci.symptoms or 'none noted'}.")
    return {"ok": True, "alerted_caretakers": bool(concerning)}


@app.get("/api/checkins")
def list_checkins(me: Me = Depends(current_member)):
    with db() as c:
        rows = c.execute("SELECT mood,symptoms,at FROM checkins WHERE profile_id=?"
                         " ORDER BY id DESC LIMIT 14", (me.profile_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------- insights
@app.get("/api/insights")
def insights(days: int = 7, me: Me = Depends(current_member)):
    since = iso(now() - timedelta(days=days))
    cur = iso(now())
    with db() as c:
        rows = c.execute("""SELECT d.scheduled_at,d.status,m.name FROM dose_logs d
            JOIN medications m ON m.id=d.medication_id
            WHERE m.profile_id=? AND d.scheduled_at>=? AND d.scheduled_at<=?""",
                         (me.profile_id, since, cur)).fetchall()
        meds = c.execute("SELECT * FROM medications WHERE profile_id=? AND active=1",
                         (me.profile_id,)).fetchall()
    total = len(rows)
    taken = sum(1 for r in rows if r["status"] == "taken")
    missed_by_slot = {}
    for r in rows:
        if r["status"] != "taken":
            slot = r["scheduled_at"][11:16]
            missed_by_slot[slot] = missed_by_slot.get(slot, 0) + 1
    patterns = [f"The {s} dose was missed {n} times in the last {days} days."
                for s, n in sorted(missed_by_slot.items(), key=lambda x: -x[1]) if n >= 2]
    refills = []
    for m in meds:
        dl = days_left(m)
        if dl is not None and dl <= 7:
            refills.append({"name": m["name"], "days_left": dl,
                            "run_out_on": (date.today() + timedelta(days=dl)).isoformat()})
    return {"days": days, "total": total, "taken": taken,
            "score": round(100 * taken / total) if total else None,
            "patterns": patterns, "refills": refills}


@app.get("/api/report")
def report(me: Me = Depends(current_member)):
    """Plain-text summary a doctor can read."""
    ins = insights(30, me)
    with db() as c:
        p = c.execute("SELECT name FROM profiles WHERE id=?", (me.profile_id,)).fetchone()
        meds = c.execute("SELECT * FROM medications WHERE profile_id=? AND active=1",
                         (me.profile_id,)).fetchall()
        cks = c.execute("SELECT mood,symptoms,at FROM checkins WHERE profile_id=? ORDER BY id DESC LIMIT 10",
                        (me.profile_id,)).fetchall()
    lines = [f"Medication report for {p['name']} - {date.today().isoformat()}", "",
             "Current medications:"]
    lines += [f"- {m['name']} {m['dosage'] or ''} at {m['times'].replace(',', ', ')}" for m in meds]
    lines += ["", f"30-day adherence: {ins['score']}% ({ins['taken']}/{ins['total']} doses)" if ins["total"]
              else "30-day adherence: no data yet"]
    lines += ins["patterns"]
    if cks:
        lines += ["", "Recent check-ins:"] + [f"- {k['at']}: mood {k['mood']}/5 {k['symptoms'] or ''}" for k in cks]
    return {"text": "\n".join(lines)}


# ----------------------------------------------------------------------- email
def send_mail(to, subject, body):
    if not to:
        return False
    if SMTP_HOST:
        try:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = MAIL_FROM, to, subject
            msg.set_content(body)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASS or "")
                s.send_message(msg)
            return True
        except Exception as e:  # keep scheduler alive
            print("SMTP error:", e)
    with open("outbox.log", "a") as f:
        f.write(f"[{iso(now())}] TO: {to}\nSUBJECT: {subject}\n{body}\n{'-' * 50}\n")
    return True


def notify_group(c, profile_id, roles, subject, body):
    q = f"SELECT name,email FROM members WHERE profile_id=? AND revoked=0 AND approved=1 AND role IN ({','.join('?' * len(roles))})"
    sent = []
    for m in c.execute(q, (profile_id, *roles)).fetchall():
        if m["email"] and send_mail(m["email"], subject, body):
            sent.append(m["name"])
    return sent


# -------------------------------------------------------------------- scheduler
def run_reminders():
    """One scheduler tick. Safe to call repeatedly (idempotent flags)."""
    t = now()
    cur = iso(t)
    with db() as c:
        for p in c.execute("SELECT id,name,email FROM profiles").fetchall():
            ensure_doses(c, p["id"], t.date())
            doses = c.execute("""SELECT d.*,m.name AS med,m.dosage FROM dose_logs d
                JOIN medications m ON m.id=d.medication_id
                WHERE m.profile_id=? AND m.active=1 AND d.status='pending'
                AND d.scheduled_at LIKE ?""", (p["id"], t.date().isoformat() + "%")).fetchall()
            for d in doses:
                sched = datetime.strptime(d["scheduled_at"], "%Y-%m-%dT%H:%M")
                mins_until = (sched - t).total_seconds() / 60
                overdue = -mins_until
                label = f"{d['med']} {d['dosage'] or ''}".strip()
                # 1. upcoming dose -> elder
                if not d["reminded"] and -1 <= mins_until <= UPCOMING_MINUTES:
                    send_mail(p["email"], f"Time for your {d['med']}",
                              f"Hello {p['name']}, it's time for {label} at {d['scheduled_at'][11:]}.")
                    c.execute("UPDATE dose_logs SET reminded=1 WHERE id=?", (d["id"],))
                # 2. missed -> elder gentle nudge after 10 min
                if d["reminded"] and not d["escalated"] and overdue >= 10 and overdue < ESCALATION_MINUTES:
                    pass
                # 3. escalate to caretakers/family after ESCALATION_MINUTES
                if not d["escalated"] and overdue >= ESCALATION_MINUTES:
                    send_mail(p["email"], f"Missed dose: {d['med']}",
                              f"{p['name']}, you haven't confirmed {label} (due {d['scheduled_at'][11:]}).")
                    notify_group(c, p["id"], ["caretaker", "family"],
                                 f"{p['name']} missed a dose",
                                 f"{p['name']} has not confirmed {label}, due at {d['scheduled_at'][11:]}. "
                                 f"Please check in.")
                    c.execute("UPDATE dose_logs SET escalated=1 WHERE id=?", (d["id"],))
                    log(c, p["id"], None, "escalated", f"{label} @ {d['scheduled_at']}")
            # appointments
            for a in c.execute("SELECT * FROM appointments WHERE profile_id=? AND at>?",
                               (p["id"], cur)).fetchall():
                at = datetime.strptime(a["at"], "%Y-%m-%dT%H:%M")
                hrs = (at - t).total_seconds() / 3600
                where = f" at {a['location']}" if a["location"] else ""
                if not a["reminded_day"] and hrs <= 24:
                    notify_group(c, p["id"], ["elder", "caretaker", "family"],
                                 f"Appointment tomorrow: Dr. {a['doctor']}",
                                 f"{p['name']} sees {a['doctor']} on {a['at'].replace('T', ' ')}{where}.")
                    c.execute("UPDATE appointments SET reminded_day=1 WHERE id=?", (a["id"],))
                if not a["reminded_hour"] and hrs <= 2:
                    notify_group(c, p["id"], ["elder", "caretaker"],
                                 f"Appointment soon: Dr. {a['doctor']}",
                                 f"Reminder: {a['doctor']} at {a['at'][11:]}{where}.")
                    c.execute("UPDATE appointments SET reminded_hour=1 WHERE id=?", (a["id"],))
            # refill alerts (once per day per med, tracked via audit)
            for m in c.execute("SELECT * FROM medications WHERE profile_id=? AND active=1",
                               (p["id"],)).fetchall():
                dl = days_left(m)
                key = f"refill {m['name']} {date.today().isoformat()}"
                if dl is not None and dl <= 5 and not c.execute(
                        "SELECT 1 FROM audit WHERE profile_id=? AND action='refill_alert' AND detail=?",
                        (p["id"], key)).fetchone():
                    notify_group(c, p["id"], ["caretaker", "family"],
                                 f"Refill needed: {m['name']}",
                                 f"{m['name']} will run out in about {dl} day(s).")
                    log(c, p["id"], None, "refill_alert", key)


def scheduler_loop():
    while True:
        try:
            run_reminders()
        except Exception as e:
            print("scheduler error:", e)
        time.sleep(SCHEDULER_INTERVAL)


@app.on_event("startup")
def startup():
    init_db()
    if os.environ.get("DISABLE_SCHEDULER") != "1":
        threading.Thread(target=scheduler_loop, daemon=True).start()


@app.post("/api/debug/run-reminders")
def debug_run(me: Me = Depends(need_elder)):
    run_reminders()
    return {"ok": True}


# ------------------------------------------------------------------------ static
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))
