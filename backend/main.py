from __future__ import annotations
import hashlib, hmac, json, os, secrets, sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import joblib
import numpy as np
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]; DATA = ROOT / "data"; DB = DATA / "app.db"; MODEL = DATA / "risk_model.joblib"
DATA.mkdir(exist_ok=True); SECRET = os.getenv("APP_SECRET", "sih26094-demo-secret-change-in-production")
app = FastAPI(title="SaathiCare API", version="1.0.0", description="Demo-only mental health screening risk-estimation API. Not a diagnostic system.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@contextmanager
def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    try: yield c; c.commit()
    finally: c.close()

def init_db():
    with conn() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, role TEXT DEFAULT 'survivor', phone TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS checkins(id INTEGER PRIMARY KEY, user_id INTEGER, mood INTEGER, anxiety INTEGER, stress INTEGER, sleep INTEGER, safety INTEGER, social INTEGER, wellbeing INTEGER, journal TEXT, risk TEXT, probability REAL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, user_id INTEGER, checkin_id INTEGER, status TEXT DEFAULT 'Open', created_at TEXT);
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, user_id INTEGER, author TEXT, body TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, title TEXT, category TEXT, contact TEXT, description TEXT, active INTEGER DEFAULT 1);''')

def now(): return datetime.now(timezone.utc).isoformat()
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def token(user):
    payload=json.dumps({"id":user["id"],"role":user["role"],"exp":(datetime.now(timezone.utc)+timedelta(days=7)).timestamp()},separators=(",",":")).encode(); sig=hmac.new(SECRET.encode(),payload,hashlib.sha256).hexdigest(); return payload.hex()+"."+sig
def current(authorization: str | None):
    try:
        t=authorization.split()[1]; raw,sig=t.split("."); payload=bytes.fromhex(raw); assert hmac.compare_digest(sig,hmac.new(SECRET.encode(),payload,hashlib.sha256).hexdigest()); d=json.loads(payload); assert d["exp"]>datetime.now(timezone.utc).timestamp(); return d
    except Exception: raise HTTPException(401,"Please log in.")
def user_for(auth):
    d=current(auth)
    with conn() as c: u=c.execute("SELECT id,name,email,role,phone,created_at FROM users WHERE id=?",(d["id"],)).fetchone()
    if not u: raise HTTPException(401,"User not found")
    return dict(u)
def counselor(auth):
    u=user_for(auth)
    if u["role"] != "counselor": raise HTTPException(403,"Counselor access required")
    return u
def row(r): return dict(r) if r else None

class Register(BaseModel): name:str=Field(min_length=2); email:str; password:str=Field(min_length=6); phone:str=""
class Login(BaseModel): email:str; password:str
class Checkin(BaseModel): mood:int=Field(ge=1,le=5); anxiety:int=Field(ge=1,le=5); stress:int=Field(ge=1,le=5); sleep:int=Field(ge=1,le=5); safety:int=Field(ge=1,le=5); social:int=Field(ge=1,le=5); wellbeing:int=Field(ge=1,le=5); journal:str=""
class Note(BaseModel): body:str=Field(min_length=1,max_length=3000)
class ProfileUpdate(BaseModel): name:str=Field(min_length=2); phone:str=""
class Resource(BaseModel): title:str=Field(min_length=2); category:str; contact:str=""; description:str=""

@app.on_event("startup")
def startup():
    if not MODEL.exists():
        from backend.train_model import train; train()
    init_db()
    with conn() as c:
        if not c.execute("SELECT 1 FROM users WHERE email='counselor@saathicare.demo'").fetchone():
            c.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES (?,?,?,?,?,?)",("Dr. Ananya Rao","counselor@saathicare.demo",hash_pw("Demo@123"),"counselor","",now()))
            c.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES (?,?,?,?,?,?)",("Asha Demo","asha@saathicare.demo",hash_pw("Demo@123"),"survivor","9000000000",now()))
        if not c.execute("SELECT 1 FROM resources").fetchone():
            c.executemany("INSERT INTO resources(title,category,contact,description) VALUES (?,?,?,?)", [("Tele-MANAS","24/7 mental health support","14416 or 1-800-891-4416","National tele-mental-health support service."),("Emergency services","Immediate safety","112","For immediate danger or urgent emergency assistance."),("Grounding practice","Self-care","","5-4-3-2-1 senses exercise for a difficult moment.")])

@app.get("/health")
def health(): return {"status":"ok","disclaimer":"Demo screening only; not medical diagnosis."}
@app.post("/auth/register")
def register(x:Register):
    try:
        with conn() as c:
            cur=c.execute("INSERT INTO users(name,email,password,phone,created_at) VALUES (?,?,?,?,?)",(x.name,x.email.lower(),hash_pw(x.password),x.phone,now())); u={"id":cur.lastrowid,"name":x.name,"email":x.email,"role":"survivor","phone":x.phone}
        return {"token":token(u),"user":u}
    except sqlite3.IntegrityError: raise HTTPException(409,"That email is already registered.")
@app.post("/auth/login")
def login(x:Login):
    with conn() as c: u=c.execute("SELECT * FROM users WHERE email=? AND password=?",(x.email.lower(),hash_pw(x.password))).fetchone()
    if not u: raise HTTPException(401,"Incorrect email or password.")
    u=dict(u); u.pop("password"); return {"token":token(u),"user":u}
@app.get("/me")
def me(authorization:str|None=Header(None)): return user_for(authorization)
@app.patch("/me")
def update_me(x:ProfileUpdate,authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: c.execute("UPDATE users SET name=?,phone=? WHERE id=?",(x.name,x.phone,u["id"]))
    return user_for(authorization)

def prediction(x:Checkin):
    pack=joblib.load(MODEL); vals=np.array([[getattr(x,k) for k in pack["features"]]]); probs=pack["model"].predict_proba(vals)[0]; index=int(probs.argmax()); return pack["labels"][index], float(probs[index]), {pack["labels"][i]:round(float(v)*100,1) for i,v in enumerate(probs)}
@app.post("/checkins")
def create_checkin(x:Checkin, authorization:str|None=Header(None)):
    u=user_for(authorization); risk,prob,distribution=prediction(x)
    with conn() as c:
        cur=c.execute("INSERT INTO checkins(user_id,mood,anxiety,stress,sleep,safety,social,wellbeing,journal,risk,probability,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(u["id"],x.mood,x.anxiety,x.stress,x.sleep,x.safety,x.social,x.wellbeing,x.journal,risk,prob,now())); cid=cur.lastrowid
        if risk=="High": c.execute("INSERT INTO alerts(user_id,checkin_id,created_at) VALUES (?,?,?)",(u["id"],cid,now()))
    return {"id":cid,"risk":risk,"probability":round(prob*100,1),"distribution":distribution,"message":"This is a screening risk estimate, not a diagnosis."}
@app.get("/checkins/me")
def my_checkins(authorization:str|None=Header(None)):
    u=user_for(authorization)
    with conn() as c: rs=c.execute("SELECT id,risk,probability,created_at,mood,anxiety,stress,sleep,safety,social,wellbeing,journal FROM checkins WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    return [row(x) for x in rs]
@app.get("/dashboard")
def dashboard(authorization:str|None=Header(None)):
    counselor(authorization)
    with conn() as c:
        total=c.execute("SELECT count(*) FROM users WHERE role='survivor'").fetchone()[0]; counts={k:c.execute("SELECT count(*) FROM checkins WHERE id IN (SELECT max(id) FROM checkins GROUP BY user_id) AND risk=?",(k,)).fetchone()[0] for k in ["Low","Moderate","High"]}
        alerts=c.execute("SELECT a.id,a.status,a.created_at,u.id user_id,u.name,u.email,c.risk,c.probability FROM alerts a JOIN users u ON u.id=a.user_id JOIN checkins c ON c.id=a.checkin_id ORDER BY a.id DESC LIMIT 8").fetchall()
    return {"total_users":total,"risk_counts":counts,"recent_alerts":[row(x) for x in alerts]}
@app.get("/alerts")
def alert_list(status:str="",authorization:str|None=Header(None)):
    counselor(authorization)
    with conn() as c:
        rs=c.execute("SELECT a.id,a.status,a.created_at,u.id user_id,u.name,u.email,c.risk,c.probability FROM alerts a JOIN users u ON u.id=a.user_id JOIN checkins c ON c.id=a.checkin_id WHERE (?='' OR a.status=?) ORDER BY CASE a.status WHEN 'Open' THEN 0 ELSE 1 END,a.id DESC",(status,status)).fetchall()
    return [row(x) for x in rs]
@app.get("/users")
def users(q:str="", authorization:str|None=Header(None)):
    counselor(authorization); like=f"%{q}%"
    with conn() as c: rs=c.execute("SELECT u.id,u.name,u.email,u.phone,u.created_at,(SELECT risk FROM checkins WHERE user_id=u.id ORDER BY id DESC LIMIT 1) risk,(SELECT created_at FROM checkins WHERE user_id=u.id ORDER BY id DESC LIMIT 1) last_checkin FROM users u WHERE u.role='survivor' AND (u.name LIKE ? OR u.email LIKE ?) ORDER BY u.id DESC",(like,like)).fetchall()
    return [row(x) for x in rs]
@app.get("/users/{uid}")
def profile(uid:int,authorization:str|None=Header(None)):
    counselor(authorization)
    with conn() as c:
        u=c.execute("SELECT id,name,email,phone,created_at FROM users WHERE id=? AND role='survivor'",(uid,)).fetchone()
        if not u: raise HTTPException(404,"User not found")
        checks=c.execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall(); notes=c.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
    return {"user":row(u),"checkins":[row(x) for x in checks],"notes":[row(x) for x in notes]}
@app.post("/users/{uid}/notes")
def add_note(uid:int,x:Note,authorization:str|None=Header(None)):
    u=counselor(authorization)
    with conn() as c: cur=c.execute("INSERT INTO notes(user_id,author,body,created_at) VALUES (?,?,?,?)",(uid,u["name"],x.body,now()))
    return {"id":cur.lastrowid,"message":"Note saved"}
@app.patch("/alerts/{aid}/resolve")
def resolve(aid:int,authorization:str|None=Header(None)):
    counselor(authorization)
    with conn() as c: c.execute("UPDATE alerts SET status='Resolved' WHERE id=?",(aid,))
    return {"message":"Alert resolved"}
@app.get("/resources")
def resources(authorization:str|None=Header(None)):
    with conn() as c: rs=c.execute("SELECT * FROM resources WHERE active=1 ORDER BY category,title").fetchall()
    return [row(x) for x in rs]
@app.post("/resources")
def create_resource(x:Resource,authorization:str|None=Header(None)):
    counselor(authorization)
    with conn() as c: cur=c.execute("INSERT INTO resources(title,category,contact,description) VALUES (?,?,?,?)",(x.title,x.category,x.contact,x.description))
    return {"id":cur.lastrowid,"message":"Resource added"}
@app.delete("/resources/{rid}")
def archive_resource(rid:int,authorization:str|None=Header(None)):
    counselor(authorization)
    with conn() as c: c.execute("UPDATE resources SET active=0 WHERE id=?",(rid,))
    return {"message":"Resource archived"}
