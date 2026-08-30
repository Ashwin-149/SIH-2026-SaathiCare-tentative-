from __future__ import annotations
import hashlib, hmac, json, os, sqlite3, secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB = DATA / "app.db"
MODEL = DATA / "risk_model.joblib"
DATA.mkdir(exist_ok=True)
SECRET = os.getenv("APP_SECRET", "sih26094-demo-secret-change-in-production")

app = FastAPI(
    title="SaathiCare AI — NHAA Prototype",
    version="2.0.0",
    description="SIH26094 prototype for continuous victim wellbeing screening and distress-risk monitoring. Not a diagnostic system.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

RISK_ORDER = {"Low": 0, "Moderate": 1, "High": 2, "Urgent": 3}
WEIGHTS = {
    "mood": 0.11, "anxiety": 0.13, "stress": 0.11, "sleep": 0.09,
    "safety": 0.15, "social": 0.07, "wellbeing": 0.08, "functioning": 0.07,
    "threat": 0.10, "court_stress": 0.05, "financial_hardship": 0.04,
}

@contextmanager
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def now(): return datetime.now(timezone.utc).isoformat()

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def token(user):
    payload = json.dumps({"id": user["id"], "role": user["role"], "exp": (datetime.now(timezone.utc) + timedelta(days=7)).timestamp()}, separators=(",", ":")).encode()
    sig = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return payload.hex() + "." + sig

def current(authorization: Optional[str]):
    try:
        if not authorization: raise ValueError()
        t = authorization.split()[1]
        raw, sig = t.split(".")
        payload = bytes.fromhex(raw)
        expected = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected): raise ValueError()
        d = json.loads(payload)
        if d["exp"] <= datetime.now(timezone.utc).timestamp(): raise ValueError()
        return d
    except Exception:
        raise HTTPException(401, "Please log in.")

def user_for(auth):
    d = current(auth)
    with conn() as c:
        u = c.execute("SELECT id,name,email,role,phone,language,created_at FROM users WHERE id=?", (d["id"],)).fetchone()
    if not u: raise HTTPException(401, "User not found")
    return dict(u)

def require_roles(auth, *roles):
    u = user_for(auth)
    if u["role"] not in roles: raise HTTPException(403, "Authorized staff access required")
    return u

def row(r): return dict(r) if r else None

def ensure_column(c, table, column, definition):
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

class Register(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str
    password: str = Field(min_length=6)
    phone: str = ""
    language: str = "English"

class Login(BaseModel): email: str; password: str

class ProfileUpdate(BaseModel): name: str = Field(min_length=2, max_length=100); phone: str = ""; language: str = "English"

class Checkin(BaseModel):
    mood: int = Field(ge=1, le=5)
    anxiety: int = Field(ge=1, le=5)
    stress: int = Field(ge=1, le=5)
    sleep: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    social: int = Field(ge=1, le=5)
    wellbeing: int = Field(ge=1, le=5)
    functioning: int = Field(ge=1, le=5)
    threat: int = Field(ge=1, le=5)
    court_stress: int = Field(ge=1, le=5)
    financial_hardship: int = Field(ge=1, le=5)
    journal: str = Field(default="", max_length=5000)
    source: str = "mobile"

class Note(BaseModel): body: str = Field(min_length=1, max_length=3000)
class Intervention(BaseModel): category: str; action: str; owner: str = "Counsellor"; status: str = "Recommended"
class Followup(BaseModel): due_date: str; channel: str = "In-app"; purpose: str = "Wellbeing follow-up"
class Event(BaseModel): event_type: str; title: str; description: str = ""; event_date: str = ""
class CourtEvent(BaseModel): title: str; event_date: str; status: str = "Scheduled"; notes: str = ""
class CompensationUpdate(BaseModel): status: str; amount: float = 0; updated_at: str = ""
class RehabUpdate(BaseModel): category: str; status: str; notes: str = ""
class AlertUpdate(BaseModel): status: str
class Journal(BaseModel): body: str = Field(min_length=1, max_length=5000); mood: str = ""
class Chat(BaseModel): message: str = Field(min_length=1, max_length=1000); language: str = "English"

QUESTION_BANK = [
    {"id":"mood_1","section":"Mood","text":"How difficult has your mood felt today?","type":"scale","weight":"mood"},
    {"id":"mood_2","section":"Mood","text":"How much have you lost interest in things you normally enjoy?","type":"scale","weight":"mood"},
    {"id":"anx_1","section":"Anxiety","text":"How worried or on-edge have you felt recently?","type":"scale","weight":"anxiety"},
    {"id":"anx_2","section":"Anxiety","text":"How difficult has it been to settle your thoughts?","type":"scale","weight":"anxiety"},
    {"id":"sleep_1","section":"Sleep","text":"How disrupted has your sleep been?","type":"scale","weight":"sleep"},
    {"id":"sleep_2","section":"Sleep","text":"How rested do you feel after sleeping?","type":"scale","weight":"sleep"},
    {"id":"support_1","section":"Social Support","text":"How connected to supportive people do you feel?","type":"scale","weight":"social"},
    {"id":"support_2","section":"Social Support","text":"How isolated have you felt?","type":"scale","weight":"social"},
    {"id":"threat_1","section":"Safety & Threat","text":"Have you experienced threats or intimidation since registering the complaint?","type":"yesno","weight":"threat","sensitive":True},
    {"id":"threat_2","section":"Safety & Threat","text":"Has anyone pressured you to withdraw or change your complaint?","type":"yesno","weight":"threat","sensitive":True},
    {"id":"threat_3","section":"Safety & Threat","text":"How safe do you feel where you currently live?","type":"scale","weight":"safety","sensitive":True},
    {"id":"court_1","section":"Court Experience","text":"How stressful is your next or recent court hearing?","type":"scale","weight":"court_stress"},
    {"id":"court_2","section":"Court Experience","text":"Have repeated hearings made it harder to maintain your routine?","type":"scale","weight":"court_stress"},
    {"id":"rehab_1","section":"Recovery & Support","text":"How difficult is your current financial situation?","type":"scale","weight":"financial_hardship"},
    {"id":"rehab_2","section":"Recovery & Support","text":"How difficult has it been to access rehabilitation or support services?","type":"scale","weight":"financial_hardship"},
    {"id":"function_1","section":"Daily Functioning","text":"How difficult has it been to complete normal daily activities?","type":"scale","weight":"functioning"},
    {"id":"function_2","section":"Daily Functioning","text":"How difficult has it been to concentrate?","type":"scale","weight":"functioning"},
    {"id":"well_1","section":"Wellbeing","text":"How overwhelmed have you felt?","type":"scale","weight":"wellbeing"},
    {"id":"well_2","section":"Wellbeing","text":"How hopeful do you feel about the next few days?","type":"scale","weight":"wellbeing"},
    {"id":"safety_1","section":"Safety","text":"Do you currently feel physically safe?","type":"scale","weight":"safety","sensitive":True},
]


def init_db():
    with conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, role TEXT DEFAULT 'survivor', phone TEXT, language TEXT DEFAULT 'English', created_at TEXT);
        CREATE TABLE IF NOT EXISTS checkins(id INTEGER PRIMARY KEY, user_id INTEGER, mood INTEGER, anxiety INTEGER, stress INTEGER, sleep INTEGER, safety INTEGER, social INTEGER, wellbeing INTEGER, functioning INTEGER DEFAULT 3, threat INTEGER DEFAULT 3, court_stress INTEGER DEFAULT 3, financial_hardship INTEGER DEFAULT 3, journal TEXT, risk TEXT, probability REAL, score INTEGER DEFAULT 0, baseline REAL DEFAULT 0, trend TEXT DEFAULT 'STABLE', contributors TEXT DEFAULT '[]', source TEXT DEFAULT 'mobile', created_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, user_id INTEGER, checkin_id INTEGER, severity TEXT DEFAULT 'HIGH', title TEXT, reason TEXT, status TEXT DEFAULT 'NEW', created_at TEXT, updated_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(checkin_id) REFERENCES checkins(id));
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, user_id INTEGER, author TEXT, body TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, title TEXT, category TEXT, contact TEXT, description TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS victim_profiles(user_id INTEGER PRIMARY KEY, case_id TEXT UNIQUE, district TEXT, state TEXT, preferred_name TEXT, consent INTEGER DEFAULT 1, privacy_mode INTEGER DEFAULT 1, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, case_id TEXT UNIQUE, stage TEXT DEFAULT 'Investigation', status TEXT DEFAULT 'Active', registered_at TEXT, assigned_counsellor TEXT, district TEXT, state TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS case_events(id INTEGER PRIMARY KEY, case_id INTEGER, event_type TEXT, title TEXT, description TEXT, event_date TEXT, created_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS interventions(id INTEGER PRIMARY KEY, case_id INTEGER, category TEXT, action TEXT, owner TEXT, status TEXT, created_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY, case_id INTEGER, due_date TEXT, channel TEXT, purpose TEXT, status TEXT DEFAULT 'Upcoming', created_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS court_events(id INTEGER PRIMARY KEY, case_id INTEGER, title TEXT, event_date TEXT, status TEXT, notes TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS compensation(id INTEGER PRIMARY KEY, case_id INTEGER UNIQUE, status TEXT, amount REAL DEFAULT 0, updated_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS rehabilitation(id INTEGER PRIMARY KEY, case_id INTEGER, category TEXT, status TEXT, notes TEXT, updated_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS journal_entries(id INTEGER PRIMARY KEY, user_id INTEGER, body TEXT, mood TEXT, analysis TEXT, created_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, target TEXT, created_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
        ''')
        # migrate the original MVP if it is reused
        for col, definition in [("functioning","INTEGER DEFAULT 3"),("threat","INTEGER DEFAULT 3"),("court_stress","INTEGER DEFAULT 3"),("financial_hardship","INTEGER DEFAULT 3"),("score","INTEGER DEFAULT 0"),("baseline","REAL DEFAULT 0"),("trend","TEXT DEFAULT 'STABLE'"),("contributors","TEXT DEFAULT '[]'"),("source","TEXT DEFAULT 'mobile'")]:
            ensure_column(c, "checkins", col, definition)
        ensure_column(c, "users", "language", "TEXT DEFAULT 'English'")
        if not c.execute("SELECT 1 FROM users WHERE email=?", ("counselor@saathicare.demo",)).fetchone():
            c.execute("INSERT INTO users(name,email,password,role,phone,language,created_at) VALUES (?,?,?,?,?,?,?)", ("Dr. Ananya Rao","counselor@saathicare.demo",hash_pw("Demo@123"),"counselor","","English",now()))
        if not c.execute("SELECT 1 FROM users WHERE email=?", ("asha@saathicare.demo",)).fetchone():
            c.execute("INSERT INTO users(name,email,password,role,phone,language,created_at) VALUES (?,?,?,?,?,?,?)", ("Asha Demo","asha@saathicare.demo",hash_pw("Demo@123"),"survivor","9000000000","Hindi",now()))
        if not c.execute("SELECT 1 FROM resources").fetchone():
            c.executemany("INSERT INTO resources(title,category,contact,description) VALUES (?,?,?,?)", [
                ("Tele-MANAS","Counselling","14416","National tele-mental-health support pathway. Verify current availability before deployment."),
                ("Emergency services","Immediate safety","112","Configured demo resource for urgent danger; verify locally before real deployment."),
                ("Legal aid information","Legal support","","Information and referral pathway for authorized support staff."),
                ("Grounding practice","Self-guided","","A simple 5-4-3-2-1 sensory grounding exercise."),
            ])
        seed_demo(c)


def seed_demo(c):
    # create profiles/cases for existing survivors and several synthetic demo cases
    names = [
        ("Asha Demo","asha@saathicare.demo","9000000000","Hindi","ATC-10435","Warangal","Telangana","Trial / Court","Worsening"),
        ("Meera Demo","meera@saathicare.demo","9000000001","English","ATC-10428","Hyderabad","Telangana","Rehabilitation","Improving"),
        ("Kiran Demo","kiran@saathicare.demo","9000000002","Telugu","ATC-10431","Nizamabad","Telangana","Investigation","Stable"),
        ("Ravi Demo","ravi@saathicare.demo","9000000003","Hindi","ATC-10442","Adilabad","Telangana","Trial / Court","High"),
        ("Sita Demo","sita@saathicare.demo","9000000004","English","ATC-10447","Karimnagar","Telangana","Investigation","Urgent"),
    ]
    for name,email,phone,lang,caseid,district,state,stage,trajectory in names:
        u=c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone()
        if not u:
            cur=c.execute("INSERT INTO users(name,email,password,role,phone,language,created_at) VALUES (?,?,?,?,?,?,?)",(name,email,hash_pw("Demo@123"),"survivor",phone,lang,now()))
            uid=cur.lastrowid
        else: uid=u[0]
        c.execute("INSERT OR IGNORE INTO victim_profiles(user_id,case_id,district,state,preferred_name,consent,privacy_mode) VALUES (?,?,?,?,?,?,?)",(uid,caseid,district,state,name.split()[0],1,1))
        c.execute("INSERT OR IGNORE INTO cases(user_id,case_id,stage,status,registered_at,assigned_counsellor,district,state) VALUES (?,?,?,?,?,?,?,?)",(uid,caseid,stage,"Active",now(),"Dr. Ananya Rao",district,state))
        case=c.execute("SELECT id FROM cases WHERE user_id=?",(uid,)).fetchone()[0]
        if not c.execute("SELECT 1 FROM case_events WHERE case_id=?",(case,)).fetchone():
            events=[
                ("COMPLAINT","Complaint registered","Case entered through an approved intake channel."),
                ("INVESTIGATION","Investigation update","Case investigation milestone recorded."),
                ("COURT","Court hearing scheduled","Upcoming/recent hearing associated with the case."),
                ("COMPENSATION","Compensation review","Compensation status updated."),
                ("REHABILITATION","Support planning","Rehabilitation/support planning checkpoint."),
            ]
            for et,t,d in events: c.execute("INSERT INTO case_events(case_id,event_type,title,description,event_date,created_at) VALUES (?,?,?,?,?,?)",(case,et,t,d,datetime.now(timezone.utc).date().isoformat(),now()))
        if not c.execute("SELECT 1 FROM compensation WHERE case_id=?",(case,)).fetchone():
            c.execute("INSERT INTO compensation(case_id,status,amount,updated_at) VALUES (?,?,?,?)",(case,"Payment Pending" if trajectory in ("High","Urgent","Worsening") else "Received",25000,now()))
        if not c.execute("SELECT 1 FROM rehabilitation WHERE case_id=?",(case,)).fetchone():
            c.execute("INSERT INTO rehabilitation(case_id,category,status,notes,updated_at) VALUES (?,?,?,?,?)",(case,"Counselling","Pending" if trajectory in ("High","Urgent","Worsening") else "Provided","Demo record",now()))
        if not c.execute("SELECT 1 FROM court_events WHERE case_id=?",(case,)).fetchone():
            c.execute("INSERT INTO court_events(case_id,title,event_date,status,notes) VALUES (?,?,?,?,?)",(case,"Next hearing / review",(datetime.now(timezone.utc)+timedelta(days=5)).date().isoformat(),"Scheduled","Demo event"))
        # Seed risk histories only once
        if not c.execute("SELECT 1 FROM checkins WHERE user_id=?",(uid,)).fetchone():
            if trajectory=="Improving": vals=[68,62,57,51,45]
            elif trajectory=="Stable": vals=[49,51,50,52,51]
            elif trajectory=="Worsening": vals=[44,51,58,67,78]
            elif trajectory=="High": vals=[59,65,70,75,80]
            else: vals=[61,68,76,84,90]
            for i,score in enumerate(vals):
                scale=max(1,min(5,round(score/20)))
                if trajectory=="Improving": scale=max(1,scale-1)
                vals_payload={k:scale for k in WEIGHTS}
                vals_payload["safety"]=min(5,scale+1 if trajectory in ("High","Urgent","Worsening") else scale)
                vals_payload["threat"]=min(5,scale+1 if trajectory in ("High","Urgent","Worsening") else scale)
                result=compute_risk(vals_payload, previous=[])
                dt=(datetime.now(timezone.utc)-timedelta(days=4-i)).isoformat()
                c.execute("INSERT INTO checkins(user_id,mood,anxiety,stress,sleep,safety,social,wellbeing,functioning,threat,court_stress,financial_hardship,journal,risk,probability,score,baseline,trend,contributors,source,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(uid,vals_payload["mood"],vals_payload["anxiety"],vals_payload["stress"],vals_payload["sleep"],vals_payload["safety"],vals_payload["social"],vals_payload["wellbeing"],vals_payload["functioning"],vals_payload["threat"],vals_payload["court_stress"],vals_payload["financial_hardship"],"","Urgent" if score>=75 else "High" if score>=55 else "Moderate" if score>=30 else "Low",result["confidence"],score,50,result["trend"],json.dumps(result["contributors"]),"demo",dt))
        latest=c.execute("SELECT id,score,risk FROM checkins WHERE user_id=? ORDER BY id DESC LIMIT 1",(uid,)).fetchone()
        if trajectory in ("High","Urgent","Worsening") and not c.execute("SELECT 1 FROM alerts WHERE user_id=?",(uid,)).fetchone():
            sev="URGENT" if trajectory=="Urgent" else "HIGH"
            c.execute("INSERT INTO alerts(user_id,checkin_id,severity,title,reason,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",(uid,latest[0],sev,"Early warning — human review recommended","Recent wellbeing indicators are elevated compared with the synthetic demo baseline; review safety and support needs.","NEW",now(),now()))


def model_predict(values):
    if not MODEL.exists():
        from backend.train_model import train; train()
    pack=joblib.load(MODEL)
    vals=np.array([[values[k] for k in pack["features"]]])
    probs=pack["model"].predict_proba(vals)[0]
    return {pack["labels"][i]: round(float(v)*100,1) for i,v in enumerate(probs)}


def compute_risk(values, previous=None):
    previous=previous or []
    section_scores={k: round((values.get(k,3)-1)/4*100,1) for k in WEIGHTS}
    score=round(sum(section_scores[k]*WEIGHTS[k] for k in WEIGHTS))
    # safety and threat are intentionally allowed to pull the score upward when elevated
    if values.get("safety",3)>=5: score=min(100,score+8)
    if values.get("threat",3)>=5: score=min(100,score+7)
    score=max(0,min(100,score))
    # model is supporting signal, not a clinical label
    dist=model_predict(values)
    ml_risk=max(dist, key=lambda k: ["Low","Moderate","High","Urgent"].index(k))
    if score<30: risk="Low"
    elif score<55: risk="Moderate"
    elif score<75: risk="High"
    else: risk="Urgent"
    prev_scores=[float(x) for x in previous]
    baseline=round(sum(prev_scores[-5:])/len(prev_scores[-5:]),1) if prev_scores else float(score)
    diff=score-baseline
    if diff>=20: trend="RAPIDLY WORSENING"
    elif diff>=8: trend="WORSENING"
    elif diff<=-10: trend="IMPROVING"
    elif len(prev_scores)>=3 and max(prev_scores[-3:])-min(prev_scores[-3:])>=15: trend="FLUCTUATING"
    else: trend="STABLE"
    contributors=sorted([{"factor":k.replace('_',' ').title(),"score":section_scores[k],"weight":round(WEIGHTS[k]*100)} for k in WEIGHTS],key=lambda x:x["score"]*x["weight"],reverse=True)[:5]
    return {"score":score,"risk":risk,"baseline":baseline,"baseline_change":round(diff,1),"trend":trend,"confidence":round(max(dist.values()),1),"model_distribution":dist,"contributors":contributors,"ml_supporting_risk":ml_risk}


def get_history(uid):
    with conn() as c:
        rs=c.execute("SELECT score,created_at FROM checkins WHERE user_id=? ORDER BY id",(uid,)).fetchall()
    return [r[0] for r in rs]


def audit(uid, action, target=""):
    with conn() as c: c.execute("INSERT INTO audit_logs(user_id,action,target,created_at) VALUES (?,?,?,?)",(uid,action,target,now()))


def case_for_user(uid):
    with conn() as c:
        x=c.execute("SELECT * FROM cases WHERE user_id=?",(uid,)).fetchone()
    if not x: raise HTTPException(404,"Case not found")
    return dict(x)

@app.on_event("startup")
def startup():
    if not MODEL.exists():
        from backend.train_model import train; train()
    init_db()

@app.get("/health")
def health(): return {"status":"ok","version":"2.0.0","disclaimer":"AI outputs are screening/risk estimates, not medical diagnoses."}

@app.post("/auth/register")
def register(x:Register):
    try:
        with conn() as c:
            cur=c.execute("INSERT INTO users(name,email,password,phone,language,created_at) VALUES (?,?,?,?,?,?)",(x.name,x.email.lower(),hash_pw(x.password),x.phone,x.language,now()))
            uid=cur.lastrowid; caseid="ATC-"+str(secrets.randbelow(90000)+10000)
            c.execute("INSERT INTO victim_profiles(user_id,case_id,district,state,preferred_name) VALUES (?,?,?,?,?)",(uid,caseid,"Demo District","Demo State",x.name.split()[0]))
            c.execute("INSERT INTO cases(user_id,case_id,stage,status,registered_at,assigned_counsellor,district,state) VALUES (?,?,?,?,?,?,?,?)",(uid,caseid,"Complaint Registered","Active",now(),"Unassigned","Demo District","Demo State"))
            u={"id":uid,"name":x.name,"email":x.email.lower(),"role":"survivor","phone":x.phone,"language":x.language}
        return {"token":token(u),"user":u}
    except sqlite3.IntegrityError: raise HTTPException(409,"That email is already registered.")

@app.post("/auth/login")
def login(x:Login):
    with conn() as c: u=c.execute("SELECT * FROM users WHERE email=? AND password=?",(x.email.lower(),hash_pw(x.password))).fetchone()
    if not u: raise HTTPException(401,"Incorrect email or password.")
    u=dict(u); u.pop("password"); audit(u["id"],"LOGIN","session"); return {"token":token(u),"user":u}

@app.get("/me")
def me(authorization:str|None=Header(None)): return user_for(authorization)

@app.patch("/me")
def update_me(x:ProfileUpdate,authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: c.execute("UPDATE users SET name=?,phone=?,language=? WHERE id=?",(x.name,x.phone,x.language,u["id"]))
    audit(u["id"],"PROFILE_UPDATE","self"); return user_for(authorization)

@app.get("/questions")
def questions(authorization:str|None=Header(None)):
    user_for(authorization)
    return {"questions":QUESTION_BANK,"total":len(QUESTION_BANK),"adaptive":True}

@app.get("/case/me")
def my_case(authorization:str|None=Header(None)):
    u=user_for(authorization); case=case_for_user(u["id"])
    with conn() as c:
        profile=c.execute("SELECT * FROM victim_profiles WHERE user_id=?",(u["id"],)).fetchone()
        events=c.execute("SELECT * FROM case_events WHERE case_id=? ORDER BY event_date,id",(case["id"],)).fetchall()
        court=c.execute("SELECT * FROM court_events WHERE case_id=? ORDER BY event_date",(case["id"],)).fetchall()
        comp=c.execute("SELECT * FROM compensation WHERE case_id=?",(case["id"],)).fetchone()
        rehab=c.execute("SELECT * FROM rehabilitation WHERE case_id=? ORDER BY id DESC",(case["id"],)).fetchall()
        interventions=c.execute("SELECT * FROM interventions WHERE case_id=? ORDER BY id DESC",(case["id"],)).fetchall()
        followups=c.execute("SELECT * FROM followups WHERE case_id=? ORDER BY due_date",(case["id"],)).fetchall()
    return {"case":case,"profile":row(profile),"events":[row(x) for x in events],"court":[row(x) for x in court],"compensation":row(comp),"rehabilitation":[row(x) for x in rehab],"interventions":[row(x) for x in interventions],"followups":[row(x) for x in followups]}

@app.post("/checkins")
def create_checkin(x:Checkin,authorization:str|None=Header(None)):
    u=user_for(authorization); values=x.model_dump(exclude={"journal","source"}); previous=get_history(u["id"]); result=compute_risk(values,previous)
    with conn() as c:
        cur=c.execute("INSERT INTO checkins(user_id,mood,anxiety,stress,sleep,safety,social,wellbeing,functioning,threat,court_stress,financial_hardship,journal,risk,probability,score,baseline,trend,contributors,source,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(u["id"],x.mood,x.anxiety,x.stress,x.sleep,x.safety,x.social,x.wellbeing,x.functioning,x.threat,x.court_stress,x.financial_hardship,x.journal,result["risk"],result["confidence"]/100,result["score"],result["baseline"],result["trend"],json.dumps(result["contributors"]),x.source,now()))
        cid=cur.lastrowid
        # Early warning and safety rules
        alert=None
        if result["risk"] in ("High","Urgent") or x.threat>=5 or x.safety>=5 or result["trend"]=="RAPIDLY WORSENING":
            severity="URGENT" if result["risk"]=="Urgent" or x.safety>=5 else "HIGH"
            title="Urgent safety review" if severity=="URGENT" else "Early warning — human review recommended"
            reason="Elevated distress indicators, safety/threat signals, or rapid change from personal baseline."
            # avoid duplicate open alerts in the same 24h
            existing=c.execute("SELECT id FROM alerts WHERE user_id=? AND status IN ('NEW','ACKNOWLEDGED','REVIEWING') AND created_at>=?",(u["id"],(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat())).fetchone()
            if not existing:
                cur2=c.execute("INSERT INTO alerts(user_id,checkin_id,severity,title,reason,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",(u["id"],cid,severity,title,reason,"NEW",now(),now())); alert=cur2.lastrowid
    audit(u["id"],"CHECKIN_SUBMITTED",str(cid))
    recommendations=[]
    if result["risk"] in ("High","Urgent"): recommendations += ["Counsellor review","Wellbeing follow-up"]
    if x.threat>=4: recommendations.append("Safety/protection support review")
    if x.financial_hardship>=4: recommendations.append("Compensation / financial assistance review")
    if x.court_stress>=4: recommendations.append("Court-related support check-in")
    if x.sleep>=4: recommendations.append("Sleep and coping support")
    return {**result,"checkin_id":cid,"alert_id":alert,"recommendations":recommendations,"message":"AI-generated screening/risk estimate only; not a medical diagnosis."}

@app.get("/checkins/me")
def my_checkins(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: rs=c.execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    out=[]
    for r in rs:
        d=dict(r); d["contributors"]=json.loads(d.get("contributors") or "[]"); out.append(d)
    return out

@app.get("/risk/current")
def current_risk(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: r=c.execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
    if not r: return {"score":0,"risk":"NO DATA","trend":"STABLE","message":"Complete your first check-in."}
    d=dict(r); d["contributors"]=json.loads(d.get("contributors") or "[]"); return d

@app.get("/risk/history")
def risk_history(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: rs=c.execute("SELECT id,score,risk,baseline,trend,created_at FROM checkins WHERE user_id=? ORDER BY id",(u["id"],)).fetchall()
    return [row(x) for x in rs]

@app.get("/alerts")
def alert_list(status:str="",authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    q="SELECT a.*,u.name,u.email,c.score,c.risk,c.trend,cp.case_id,cp.stage FROM alerts a JOIN users u ON u.id=a.user_id JOIN checkins c ON c.id=a.checkin_id LEFT JOIN cases cp ON cp.user_id=a.user_id"
    args=[]
    if status: q+=" WHERE a.status=?"; args.append(status)
    q+=" ORDER BY CASE a.severity WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,a.id DESC"
    with conn() as c: rs=c.execute(q,args).fetchall()
    return [row(x) for x in rs]

@app.patch("/alerts/{aid}")
def update_alert(aid:int,x:AlertUpdate,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    allowed={"NEW","ACKNOWLEDGED","REVIEWING","CONTACTED","FOLLOW-UP","RESOLVED"}
    if x.status not in allowed: raise HTTPException(400,"Invalid alert status")
    with conn() as c: c.execute("UPDATE alerts SET status=?,updated_at=? WHERE id=?",(x.status,now(),aid))
    audit(u["id"],"ALERT_STATUS",str(aid)); return {"message":"Alert updated"}

@app.get("/users")
def users(q:str="",authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    like=f"%{q}%"
    with conn() as c:
        rs=c.execute("SELECT u.id,u.name,u.email,u.phone,u.language,cp.case_id,cp.stage,cp.district,cp.state,(SELECT score FROM checkins WHERE user_id=u.id ORDER BY id DESC LIMIT 1) score,(SELECT risk FROM checkins WHERE user_id=u.id ORDER BY id DESC LIMIT 1) risk,(SELECT trend FROM checkins WHERE user_id=u.id ORDER BY id DESC LIMIT 1) trend,(SELECT created_at FROM checkins WHERE user_id=u.id ORDER BY id DESC LIMIT 1) last_checkin FROM users u LEFT JOIN cases cp ON cp.user_id=u.id WHERE u.role='survivor' AND (u.name LIKE ? OR u.email LIKE ? OR cp.case_id LIKE ?) ORDER BY CASE risk WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Moderate' THEN 2 ELSE 3 END,u.id DESC",(like,like,like)).fetchall()
    return [row(x) for x in rs]

@app.get("/users/{uid}")
def profile(uid:int,authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        u=c.execute("SELECT id,name,email,phone,language,created_at FROM users WHERE id=? AND role='survivor'",(uid,)).fetchone()
        if not u: raise HTTPException(404,"User not found")
        cp=c.execute("SELECT * FROM cases WHERE user_id=?",(uid,)).fetchone()
        checks=c.execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
        notes=c.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
        alerts=c.execute("SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
    return {"user":row(u),"case":row(cp),"checkins":[row(x) for x in checks],"notes":[row(x) for x in notes],"alerts":[row(x) for x in alerts]}

@app.post("/users/{uid}/notes")
def add_note(uid:int,x:Note,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c: cur=c.execute("INSERT INTO notes(user_id,author,body,created_at) VALUES (?,?,?,?)",(uid,u["name"],x.body,now()))
    audit(u["id"],"NOTE_ADDED",str(uid)); return {"id":cur.lastrowid,"message":"Note saved"}

@app.get("/dashboard")
def dashboard(authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        total=c.execute("SELECT count(*) FROM users WHERE role='survivor'").fetchone()[0]
        latest="SELECT * FROM checkins WHERE id IN (SELECT max(id) FROM checkins GROUP BY user_id)"
        counts={k:c.execute(f"SELECT count(*) FROM ({latest}) WHERE risk=?",(k,)).fetchone()[0] for k in ["Low","Moderate","High","Urgent"]}
        open_alerts=c.execute("SELECT count(*) FROM alerts WHERE status!='RESOLVED'").fetchone()[0]
        due=c.execute("SELECT count(*) FROM followups WHERE status!='Completed'").fetchone()[0]
        recent=c.execute("SELECT a.*,u.name,c.score,c.risk,c.trend,cp.case_id,cp.stage FROM alerts a JOIN users u ON u.id=a.user_id JOIN checkins c ON c.id=a.checkin_id LEFT JOIN cases cp ON cp.user_id=a.user_id ORDER BY a.id DESC LIMIT 8").fetchall()
    return {"total_users":total,"risk_counts":counts,"open_alerts":open_alerts,"followups_due":due,"recent_alerts":[row(x) for x in recent]}

@app.get("/analytics/summary")
def analytics_summary(authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        stages=[row(x) for x in c.execute("SELECT stage,count(*) count FROM cases GROUP BY stage").fetchall()]
        districts=[row(x) for x in c.execute("SELECT district,count(*) count FROM cases GROUP BY district ORDER BY count DESC").fetchall()]
        interventions=[row(x) for x in c.execute("SELECT status,count(*) count FROM interventions GROUP BY status").fetchall()]
        alerts=[row(x) for x in c.execute("SELECT severity,count(*) count FROM alerts GROUP BY severity").fetchall()]
        workload=[row(x) for x in c.execute("SELECT assigned_counsellor,count(*) count FROM cases GROUP BY assigned_counsellor").fetchall()]
    return {"stages":stages,"districts":districts,"interventions":interventions,"alerts":alerts,"workload":workload,"data_notice":"Synthetic demo aggregates."}

@app.get("/case/{caseid}")
def case_detail(caseid:str,authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT * FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        uid=cp["user_id"]
        u=c.execute("SELECT id,name,email,phone,language FROM users WHERE id=?",(uid,)).fetchone()
        checks=c.execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id",(uid,)).fetchall()
        events=c.execute("SELECT * FROM case_events WHERE case_id=? ORDER BY event_date,id",(cp["id"],)).fetchall()
        alerts=c.execute("SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
        notes=c.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
        ints=c.execute("SELECT * FROM interventions WHERE case_id=? ORDER BY id DESC",(cp["id"],)).fetchall()
        fus=c.execute("SELECT * FROM followups WHERE case_id=? ORDER BY due_date",(cp["id"],)).fetchall()
        court=c.execute("SELECT * FROM court_events WHERE case_id=? ORDER BY event_date",(cp["id"],)).fetchall()
        comp=c.execute("SELECT * FROM compensation WHERE case_id=?",(cp["id"],)).fetchone()
        rehab=c.execute("SELECT * FROM rehabilitation WHERE case_id=? ORDER BY id DESC",(cp["id"],)).fetchall()
    return {"case":row(cp),"user":row(u),"checkins":[row(x) for x in checks],"events":[row(x) for x in events],"alerts":[row(x) for x in alerts],"notes":[row(x) for x in notes],"interventions":[row(x) for x in ints],"followups":[row(x) for x in fus],"court":[row(x) for x in court],"compensation":row(comp),"rehabilitation":[row(x) for x in rehab]}

@app.post("/case/{caseid}/events")
def add_event(caseid:str,x:Event,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT id FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        c.execute("INSERT INTO case_events(case_id,event_type,title,description,event_date,created_at) VALUES (?,?,?,?,?,?)",(cp[0],x.event_type,x.title,x.description,x.event_date or datetime.now(timezone.utc).date().isoformat(),now()))
    audit(u["id"],"CASE_EVENT_ADDED",caseid); return {"message":"Event added"}

@app.post("/case/{caseid}/interventions")
def add_intervention(caseid:str,x:Intervention,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT id FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        cur=c.execute("INSERT INTO interventions(case_id,category,action,owner,status,created_at) VALUES (?,?,?,?,?,?)",(cp[0],x.category,x.action,x.owner,x.status,now()))
    audit(u["id"],"INTERVENTION_RECORDED",caseid); return {"id":cur.lastrowid,"message":"Intervention recorded"}

@app.post("/case/{caseid}/followups")
def add_followup(caseid:str,x:Followup,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT id FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        cur=c.execute("INSERT INTO followups(case_id,due_date,channel,purpose,created_at) VALUES (?,?,?,?,?)",(cp[0],x.due_date,x.channel,x.purpose,now()))
    audit(u["id"],"FOLLOWUP_SCHEDULED",caseid); return {"id":cur.lastrowid,"message":"Follow-up scheduled"}

@app.get("/interventions")
def interventions_api(authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        rs=c.execute("SELECT i.*,cp.case_id FROM interventions i JOIN cases cp ON cp.id=i.case_id ORDER BY i.id DESC").fetchall()
    return [row(x) for x in rs]

@app.get("/followups")
def followups_api(authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        rs=c.execute("SELECT f.*,cp.case_id FROM followups f JOIN cases cp ON cp.id=f.case_id ORDER BY f.due_date").fetchall()
    return [row(x) for x in rs]

@app.get("/court")
def court(authorization:str|None=Header(None)):
    u=user_for(authorization)
    if u["role"]=="survivor":
        cp=case_for_user(u["id"]); args=(cp["id"],); q="SELECT * FROM court_events WHERE case_id=? ORDER BY event_date"
    else:
        q="SELECT ce.*,cp.case_id FROM court_events ce JOIN cases cp ON cp.id=ce.case_id ORDER BY ce.event_date"; args=()
    with conn() as c: rs=c.execute(q,args).fetchall()
    return [row(x) for x in rs]

@app.post("/case/{caseid}/court")
def add_court(caseid:str,x:CourtEvent,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT id FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        cur=c.execute("INSERT INTO court_events(case_id,title,event_date,status,notes) VALUES (?,?,?,?,?)",(cp[0],x.title,x.event_date,x.status,x.notes))
    audit(u["id"],"COURT_EVENT_ADDED",caseid); return {"id":cur.lastrowid,"message":"Court event added"}

@app.get("/compensation")
def compensation(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c:
        if u["role"]=="survivor": rs=c.execute("SELECT co.*,cp.case_id FROM compensation co JOIN cases cp ON cp.id=co.case_id WHERE cp.user_id=?",(u["id"],)).fetchall()
        else: rs=c.execute("SELECT co.*,cp.case_id FROM compensation co JOIN cases cp ON cp.id=co.case_id").fetchall()
    return [row(x) for x in rs]

@app.patch("/case/{caseid}/compensation")
def update_comp(caseid:str,x:CompensationUpdate,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT id FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        c.execute("INSERT INTO compensation(case_id,status,amount,updated_at) VALUES (?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET status=excluded.status,amount=excluded.amount,updated_at=excluded.updated_at",(cp[0],x.status,x.amount,x.updated_at or now()))
    audit(u["id"],"COMPENSATION_UPDATED",caseid); return {"message":"Compensation updated"}

@app.get("/rehabilitation")
def rehabilitation(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c:
        if u["role"]=="survivor": rs=c.execute("SELECT r.*,cp.case_id FROM rehabilitation r JOIN cases cp ON cp.id=r.case_id WHERE cp.user_id=?",(u["id"],)).fetchall()
        else: rs=c.execute("SELECT r.*,cp.case_id FROM rehabilitation r JOIN cases cp ON cp.id=r.case_id ORDER BY r.id DESC").fetchall()
    return [row(x) for x in rs]

@app.post("/case/{caseid}/rehabilitation")
def update_rehab(caseid:str,x:RehabUpdate,authorization:str|None=Header(None)):
    u=require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c:
        cp=c.execute("SELECT id FROM cases WHERE case_id=?",(caseid,)).fetchone()
        if not cp: raise HTTPException(404,"Case not found")
        c.execute("INSERT INTO rehabilitation(case_id,category,status,notes,updated_at) VALUES (?,?,?,?,?)",(cp[0],x.category,x.status,x.notes,now()))
    audit(u["id"],"REHABILITATION_UPDATED",caseid); return {"message":"Rehabilitation record added"}

@app.get("/journal")
def journals(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: rs=c.execute("SELECT * FROM journal_entries WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    return [row(x) for x in rs]

@app.post("/journal")
def add_journal(x:Journal,authorization:str|None=Header(None)):
    u=user_for(authorization)
    body=x.body.lower()
    themes=[]
    for key,words in {"sleep":['sleep','night','tired'],"anxiety":['worry','worried','anxious','fear'],"safety":['unsafe','threat','afraid'],"isolation":['alone','isolated'],"hope":['hope','better','good']}.items():
        if any(w in body for w in words): themes.append(key)
    analysis="Themes noticed: "+(", ".join(themes) if themes else "no strong theme detected")+". This is a language signal, not a diagnosis."
    with conn() as c: cur=c.execute("INSERT INTO journal_entries(user_id,body,mood,analysis,created_at) VALUES (?,?,?,?,?)",(u["id"],x.body,x.mood,analysis,now()))
    audit(u["id"],"JOURNAL_CREATED",str(cur.lastrowid)); return {"id":cur.lastrowid,"analysis":analysis}

@app.post("/saathi/chat")
def saathi_chat(x:Chat,authorization:str|None=Header(None)):
    u=user_for(authorization); m=x.message.lower()
    if any(k in m for k in ["unsafe","threat","danger","afraid"]): reply="I’m sorry this feels unsafe. You can open Safety Center and choose a trusted person or configured support pathway. If there is immediate danger, move toward a safer place and contact verified local emergency support."
    elif any(k in m for k in ["court","hearing"]): reply="Court-related stress can be difficult. Your Case Journey shows upcoming hearings, and you can request a wellbeing follow-up from the support team."
    elif any(k in m for k in ["compensation","money","payment"]): reply="I can help you find your compensation status in the Case Journey. If a payment is delayed, an authorized support worker can review the case."
    elif any(k in m for k in ["sad","anxious","stress","worried","tired"]): reply="Thank you for sharing that. You can take a short check-in now so SaathiCare can compare today's indicators with your personal trend."
    else: reply="I’m here to help you navigate SaathiCare. You can check in, view your case journey, find support, or ask to speak with a counsellor."
    return {"reply":reply,"language":x.language,"assistant":"Saathi AI","notice":"Conversational prototype; not a clinician."}

@app.get("/resources")
def resources(authorization:str|None=Header(None)):
    user_for(authorization)
    with conn() as c: rs=c.execute("SELECT * FROM resources WHERE active=1 ORDER BY category,title").fetchall()
    return [row(x) for x in rs]

@app.get("/audit")
def audit_logs(authorization:str|None=Header(None)):
    require_roles(authorization,"counselor","district","state","national","admin")
    with conn() as c: rs=c.execute("SELECT a.*,u.name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100").fetchall()
    return [row(x) for x in rs]

@app.get("/notifications")
def notifications(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c:
        alerts=c.execute("SELECT title,reason,severity,created_at,status FROM alerts WHERE user_id=? ORDER BY id DESC LIMIT 5",(u["id"],)).fetchall()
    return [{"type":"alert","title":x["title"],"message":x["reason"],"severity":x["severity"],"created_at":x["created_at"],"status":x["status"]} for x in alerts]
