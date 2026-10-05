"""Traffic Accident Management System - Flask + SQLite backend.
Run:  python app.py   then open http://127.0.0.1:5000"""
import json, math, os, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, render_template, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, "uploads")
DB_PATH = os.path.join(BASE, "accidents.db")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB per request

# ---- Rules (change these to match your SRS) ----
SEVERITIES = ["Low", "Medium", "High"]
FAKE_KM, DUP_METERS, DUP_MINUTES, RANGE_KM = 500, 100, 10, 25
USERS = {  # demo accounts: username -> (password hash, role)
    "admin": (generate_password_hash("admin123"), "admin"),
    "user1": (generate_password_hash("user123"), "user"),
    "user2": (generate_password_hash("user123"), "user"),
}
UNITS = [  # (type, name, lat, lng): sample police stations / hospitals
    ("Police", "Connaught Place Police Stn", 28.6315, 77.2167),
    ("Police", "Hauz Khas Police Stn", 28.5494, 77.2001),
    ("Hospital", "AIIMS Trauma Centre", 28.5672, 77.2100),
    ("Hospital", "RML Hospital", 28.6258, 77.2000),
]
AUDIO_EXT = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
             "audio/wav": ".wav", "audio/mpeg": ".mp3"}


# ---------------- helpers ----------------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT, happened TEXT, lat REAL, lng REAL,
        severity TEXT, description TEXT, status TEXT DEFAULT 'Pending',
        suspicious INTEGER DEFAULT 0, approved_by TEXT,
        reporters TEXT, photos TEXT, audio TEXT, alerts TEXT);
    CREATE TABLE IF NOT EXISTS synced(cid TEXT PRIMARY KEY, report_id INTEGER);
    CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, who TEXT, role TEXT,
        action TEXT, ref TEXT, note TEXT);
    CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
        BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
        BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    """)
    conn.commit()
    conn.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def log(action, ref="", note="", who=None, role=None):
    db().execute("INSERT INTO audit(ts,who,role,action,ref,note) VALUES(?,?,?,?,?,?)",
                 (now(), who or session.get("user", "anonymous"), role or session.get("role", "-"),
                  action, str(ref), note))


def out(row):
    d = dict(row)
    for k in ("reporters", "photos", "audio", "alerts"):
        d[k] = json.loads(d[k])
    return d


def image_ext(b):  # validate by file content, not by file name
    if b[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return ".webp"
    return None


def store(data, ext):
    name = uuid.uuid4().hex + ext
    with open(os.path.join(UPLOADS, name), "wb") as fh:
        fh.write(data)
    return name


def is_mine(r):
    return any(p["name"] == session["user"] for p in r["reporters"])


def login_required(admin=False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if "user" not in session:
                return jsonify(error="Please log in"), 401
            if admin and session["role"] != "admin":  # role check lives on the server
                log("DENIED_" + request.endpoint.upper(), kw.get("rid", ""), "Non-admin attempted admin action")
                db().commit()
                return jsonify(error="Access denied: admin only"), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def alert_units(rid, lat, lng):
    """Simulated SMS to the nearest police station and hospital within range."""
    msgs = []
    for kind in ("Police", "Hospital"):
        near = min((u for u in UNITS if u[0] == kind), key=lambda u: km(lat, lng, u[2], u[3]))
        d = km(lat, lng, near[2], near[3])
        if d <= RANGE_KM:
            m = f"SMS sent to {near[1]} ({d:.1f} km)"
            msgs.append(m)
            log("ALERT_SENT", rid, m, "system", "system")
        else:
            log("NO_UNIT_IN_RANGE", rid, f"No {kind} within {RANGE_KM} km", "system", "system")
    return msgs


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="Upload too large (max 12 MB)"), 413


# ---------------- pages & auth ----------------
@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    name = str(d.get("username", ""))[:30]
    u = USERS.get(name)
    if not u or not check_password_hash(u[0], str(d.get("password", ""))):
        log("LOGIN_FAILED", "", "Bad credentials", name or "anonymous", "-")
        db().commit()
        return jsonify(error="Wrong username or password"), 401
    session.clear()
    session["user"], session["role"] = name, u[1]
    log("LOGIN")
    db().commit()
    return jsonify(user=name, role=u[1])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@login_required()
def me():
    return jsonify(user=session["user"], role=session["role"])


# ---------------- reports ----------------
@app.post("/api/reports")
@login_required()
def create_report():
    f, user = request.form, session["user"]
    try:
        happened = datetime.fromisoformat(f["when"].replace("Z", "+00:00"))
        if happened.tzinfo is None:
            happened = happened.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return jsonify(error="Invalid date"), 400
    if happened > datetime.now(timezone.utc) + timedelta(minutes=1):
        return jsonify(error="Invalid date"), 400
    try:
        lat, lng = float(f["lat"]), float(f["lng"])
    except (KeyError, ValueError):
        return jsonify(error="Valid location required"), 400
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify(error="Location out of range"), 400
    sev = f.get("severity")
    if sev not in SEVERITIES:
        return jsonify(error="Severity must be Low, Medium or High"), 400

    # same submission sent twice (e.g. offline sync retry) -> ignore the repeat
    cid = f.get("cid") or uuid.uuid4().hex
    prev = db().execute("SELECT report_id FROM synced WHERE cid=?", (cid,)).fetchone()
    if prev:
        log("DUPLICATE_SYNC_IGNORED", prev[0], "Same submission received twice")
        db().commit()
        return jsonify(id=prev[0], merged=True), 200

    # fake-report check against the reporter's device GPS
    suspicious = 0
    try:
        far = km(float(f["device_lat"]), float(f["device_lng"]), lat, lng) > FAKE_KM
    except (KeyError, ValueError):
        far = False
    if far and f.get("confirm_far") != "1":
        return jsonify(warning=f"Fake report? Location is over {FAKE_KM} km from your GPS."), 409
    suspicious = int(far)

    # validate every upload before saving anything
    files = request.files.getlist("photos")
    if len(files) > 2:
        return jsonify(error="Maximum 2 photos"), 400
    blobs = []
    for p in files:
        b = p.read()
        if not image_ext(b):
            return jsonify(error=f"Rejected: {p.filename} is not an image"), 400
        blobs.append(b)
    audio_f = request.files.get("audio")
    audio_bytes = audio_f.read() if audio_f else b""
    if audio_f and not (audio_f.mimetype or "").startswith("audio/"):
        return jsonify(error="Rejected: voice note must be an audio file"), 400

    photo_names = [store(b, image_ext(b)) for b in blobs]
    audio_name = store(audio_bytes, AUDIO_EXT.get(audio_f.mimetype, ".webm")) if audio_bytes else None
    reporter = {"name": user, "at": now()}

    # duplicate incident: within DUP_METERS and DUP_MINUTES of an existing one -> merge
    dup = None
    for r in db().execute("SELECT * FROM reports"):
        t = datetime.fromisoformat(r["happened"])
        if abs((t - happened).total_seconds()) <= DUP_MINUTES * 60 and km(r["lat"], r["lng"], lat, lng) * 1000 <= DUP_METERS:
            dup = out(r)
            break
    if dup:
        dup["reporters"].append(reporter)
        dup["photos"] += photo_names
        if audio_name:
            dup["audio"].append(audio_name)
        if SEVERITIES.index(sev) > SEVERITIES.index(dup["severity"]):
            dup["severity"] = sev
        if dup["severity"] == "High" and not dup["alerts"]:
            dup["alerts"] = alert_units(dup["id"], dup["lat"], dup["lng"])
        db().execute("UPDATE reports SET severity=?, reporters=?, photos=?, audio=?, alerts=? WHERE id=?",
                     (dup["severity"], json.dumps(dup["reporters"]), json.dumps(dup["photos"]),
                      json.dumps(dup["audio"]), json.dumps(dup["alerts"]), dup["id"]))
        rid, merged = dup["id"], True
        log("MERGED", rid, f"Duplicate report by {user} merged into #{rid}")
    else:
        cur = db().execute(
            "INSERT INTO reports(happened,lat,lng,severity,description,suspicious,reporters,photos,audio,alerts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (happened.isoformat(), lat, lng, sev, f.get("description", "").strip()[:500], suspicious,
             json.dumps([reporter]), json.dumps(photo_names), json.dumps([audio_name] if audio_name else []), "[]"))
        rid, merged = cur.lastrowid, False
        log("REPORTED", rid, sev + " severity" + (" (flagged: far from device GPS)" if suspicious else ""))
        if sev == "High":
            db().execute("UPDATE reports SET alerts=? WHERE id=?", (json.dumps(alert_units(rid, lat, lng)), rid))
    db().execute("INSERT INTO synced(cid, report_id) VALUES(?,?)", (cid, rid))
    db().commit()
    return jsonify(id=rid, merged=merged), 201


@app.get("/api/reports")
@login_required()
def list_reports():
    rows = [out(r) for r in db().execute("SELECT * FROM reports ORDER BY id DESC")]
    if session["role"] != "admin":  # users only ever receive their own reports
        rows = [r for r in rows if is_mine(r)]
    return jsonify(rows)


@app.post("/api/reports/<int:rid>/approve")
@login_required(admin=True)
def approve(rid):
    cur = db().execute("UPDATE reports SET status='Approved', approved_by=? WHERE id=?", (session["user"], rid))
    if not cur.rowcount:
        return jsonify(error="Report not found"), 404
    log("APPROVED", rid, "Approved for forwarding to police")
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/reports/<int:rid>")
@login_required(admin=True)
def delete_report(rid):
    row = db().execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
    if not row:
        return jsonify(error="Report not found"), 404
    r = out(row)
    db().execute("DELETE FROM reports WHERE id=?", (rid,))
    log("DELETED", rid, "Report removed (audit entry kept)")
    db().commit()
    for name in r["photos"] + r["audio"]:
        try:
            os.remove(os.path.join(UPLOADS, name))
        except OSError:
            pass
    return jsonify(ok=True)


@app.get("/api/audit")
@login_required(admin=True)
def audit():
    return jsonify([dict(r) for r in db().execute("SELECT * FROM audit ORDER BY id DESC LIMIT 500")])


@app.get("/uploads/<name>")
@login_required()
def media(name):
    if session["role"] != "admin":
        ok = any(name in r["photos"] + r["audio"] and is_mine(r)
                 for r in map(out, db().execute("SELECT * FROM reports")))
        if not ok:
            return jsonify(error="Access denied"), 403
    return send_from_directory(UPLOADS, name)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
