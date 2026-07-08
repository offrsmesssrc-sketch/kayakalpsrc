#!/usr/bin/env python3
"""
Kaya Kalp Beauty Parlour — Cloud Web Server  (server.py)
=========================================================
Deploy this file to Render.com for online access.
• No Tkinter / no GUI — fully headless
• SQLite replaces Excel for all data storage
• Admin panel at /admin  (add beauticians, upload photos, view logs)
• Face recognition fully works on the server
• Render.com handles HTTPS automatically

Environment variables you can set in Render dashboard:
  DATA_FOLDER    – where DB + photos are stored  (default: /data)
  ADMIN_USERNAME – admin login username           (default: admin)
  ADMIN_PASSWORD – admin login password           (default: abcd@1234)
  PORT           – HTTP port                      (default: 8000)
"""

import os, json, threading, base64, sqlite3, secrets, time, io
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import numpy as np
    import cv2
    import face_recognition
    FACE_RECOGNITION_SUPPORTED = True
except ImportError:
    FACE_RECOGNITION_SUPPORTED = False
    np = None

# ═══════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════
DATA_FOLDER          = os.environ.get("DATA_FOLDER", "/data")
os.makedirs(DATA_FOLDER, exist_ok=True)

DB_FILE              = os.path.join(DATA_FOLDER, "beautyparlour.db")
KNOWN_FACES_DIR      = os.path.join(DATA_FOLDER, "faces_adm")
ENCODINGS_CACHE_FILE = os.path.join(DATA_FOLDER, "face_encodings_cache.json")
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip().strip('"').strip("'")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "abcd@1234").strip().strip('"').strip("'")

TOLERANCE        = 0.48
MODEL            = "hog"
SESSION_DURATION = 24 * 3600   # 24 hours

admin_sessions: dict = {}       # token → expiry epoch
known_encodings      = []
known_ids            = []
known_names: dict    = {}
face_lock            = threading.Lock()

# ═══════════════════════════════════════════════════════════
#  RATE LIST  (identical to beauty.py)
# ═══════════════════════════════════════════════════════════
RATE_LIST = {
    "Threading": [
        {"name": "Eye Brow",   "rate": 30},
        {"name": "Up Lips",    "rate": 20},
        {"name": "Fore Head",  "rate": 20},
        {"name": "Chin",       "rate": 10},
        {"name": "Face Side",  "rate": 50},
        {"name": "Full Side",  "rate": 100}
    ],
    "Face Waxing": [
        {"name": "Forehead Wax",    "rate": 60},
        {"name": "Chin Wax",        "rate": 45},
        {"name": "Face Side Wax",   "rate": 150},
        {"name": "Full Face Wax",   "rate": 300},
        {"name": "Up Lips Wax",     "rate": 50}
    ],
    "Bleach & De-Tan": [
        {"name": "Fruit Bleach",                 "rate": 120},
        {"name": "Oxy Bleach",                   "rate": 130},
        {"name": "Olivia Bleach",                "rate": 120},
        {"name": "Nature Gold Bleach",           "rate": 160},
        {"name": "Nature Pro Lato Bleach",       "rate": 200},
        {"name": "Vedic Line Charcoal Bleach",   "rate": 130},
        {"name": "De Tan Nature Pack",           "rate": 300},
        {"name": "O3++ De Tan Pack",             "rate": 500}
    ],
    "Facials": [
        {"name": "Gold Facial Nature",                           "rate": 500},
        {"name": "Lotus with Glow",                              "rate": 600},
        {"name": "Papaya Fruit Facial",                          "rate": 600},
        {"name": "VLCC Pearl n Diamond",                         "rate": 550},
        {"name": "VLCC Instant Glow",                            "rate": 500},
        {"name": "Nutri Glow",                                   "rate": "Ask"},
        {"name": "Shahnaz Facial (Gold)",                        "rate": 1500},
        {"name": "Lotus Gold Facial",                            "rate": "Ask"},
        {"name": "De-tan Facial",                                "rate": 500},
        {"name": "Wedding Glow",                                 "rate": "Ask"},
        {"name": "Bridal Facial",                                "rate": "Ask"},
        {"name": "Ozone Facial / Xpress Facial",                 "rate": 700},
        {"name": "O3++ Facial",                                  "rate": 2000},
        {"name": "Korean Facial (Glass)",                        "rate": 700},
        {"name": "Aroma Facial (Aloe-vera)",                     "rate": 600},
        {"name": "Vedic Facial (Vit C)",                         "rate": 600},
        {"name": "Thermo Herb Facial",                           "rate": 1000},
        {"name": "Home Remedies - Fruit Original Juice Facial",  "rate": 500}
    ],
    "Body Waxing": [
        {"name": "Full Arms - White Chocolate",  "rate": 200},
        {"name": "Full Arms - Aloe Vera",        "rate": 200},
        {"name": "Full Arms - Rica",             "rate": 400},
        {"name": "Full Legs - White Chocolate",  "rate": 500},
        {"name": "Full Legs - Aloe Vera",        "rate": 500},
        {"name": "Full Legs - Rica",             "rate": 600},
        {"name": "Half Legs - White Chocolate",  "rate": 250},
        {"name": "Half Legs - Aloe Vera",        "rate": 250},
        {"name": "Half Legs - Rica",             "rate": 300},
        {"name": "Under Arms - White Chocolate", "rate": 80},
        {"name": "Under Arms - Aloe Vera",       "rate": 80},
        {"name": "Under Arms - Rica",            "rate": 100}
    ],
    "Hair Work": [
        {"name": "Smoothening / Straightening (Glatt / Strax)", "rate": "Ask"},
        {"name": "Botox (Kera BTX+)",                           "rate": "Ask"},
        {"name": "Hair Highlights (Streax)",                    "rate": "Ask"},
        {"name": "Root Touchup",                                "rate": 500},
        {"name": "Hair Global - Short",                         "rate": 1200},
        {"name": "Hair Global - Long",                          "rate": 1800},
        {"name": "Hair Spa (Streax) - Short",                   "rate": 500},
        {"name": "Hair Spa (Streax) - Long",                    "rate": 550},
        {"name": "Hair Spa (Loreal) - Short",                   "rate": 700},
        {"name": "Hair Spa (Loreal) - Long",                    "rate": 750},
        {"name": "Keratin Kerafine",                            "rate": 3000}
    ],
    "Body Massage": [
        {"name": "Full Body Oil Massage - Baby/Olive/Coconut", "rate": 1000},
        {"name": "Full Body Cream Massage",                    "rate": 1100},
        {"name": "Foot Massage - Oil / Cream",                 "rate": 250}
    ],
    "Hair Cut": [
        {"name": "Straight Cut",       "rate": 100},
        {"name": "U-Cut",              "rate": 120},
        {"name": "Deep U Cut",         "rate": 150},
        {"name": "Front Layer Cut",    "rate": 150},
        {"name": "Three Step Cut",     "rate": 300},
        {"name": "Full Layer Cut",     "rate": 350},
        {"name": "Multi Step Cut",     "rate": 400},
        {"name": "Blunt Cut",          "rate": 300},
        {"name": "Bob Hair Cut",       "rate": 300},
        {"name": "Butterfly Hair Cut", "rate": 400}
    ],
    "Hand & Feet Care": [
        {"name": "Pedicure (Fruit / VLCC)", "rate": 350},
        {"name": "Manicure (Fruit / VLCC)", "rate": 350},
        {"name": "Pedicure + Bleach",       "rate": 550},
        {"name": "Manicure + Bleach",       "rate": 550},
        {"name": "Pedicure (Paraffin)",     "rate": "Ask"},
        {"name": "Manicure (Paraffin)",     "rate": "Ask"}
    ],
    "Other Work": [
        {"name": "Blow Dry",                          "rate": 100},
        {"name": "Hair Wash",                         "rate": 150},
        {"name": "Hair Oil Head",                     "rate": 250},
        {"name": "Ironing + Setting Spray",           "rate": 250},
        {"name": "Mehandi (Head)",                    "rate": 200},
        {"name": "Hair Style",                        "rate": "Ask"},
        {"name": "Mehandi Hand - Half",               "rate": 200},
        {"name": "Mehandi Hand - Full",               "rate": 300},
        {"name": "Party Makeup (PAC / Mrs)",          "rate": 1000},
        {"name": "HD Makeup (Forever 52 / PAC / MAC)","rate": 1500},
        {"name": "Dress Draping",                     "rate": 200},
        {"name": "Nail Extensions / Art",             "rate": "Ask"}
    ],
    "Special Offers": [
        {"name": "Glow Starter Combo - Eye Brow + Up Lips + Fore Head + Chin", "rate": 75},
        {"name": "Full Grooming Combo - Full Face Wax + Eye Brow",             "rate": 320},
        {"name": "Hand & Feet Combo - Manicure + Pedicure",                    "rate": 650},
        {"name": "Bridal Glow Consultation",                                   "rate": 0},
        {"name": "Hair Spa Day - Streax Hair Spa",                             "rate": 499},
        {"name": "Party Ready Add-on - Dress Draping + Blow Dry",             "rate": 280},
        {"name": "Premium Facial Upgrade",                                     "rate": "Ask"},
        {"name": "Student / Trainee Grooming Day",                            "rate": "Ask"}
    ]
}

RATES_FILE = os.path.join(DATA_FOLDER, "rates.json")

def load_rates():
    global RATE_LIST
    if os.path.exists(RATES_FILE):
        try:
            with open(RATES_FILE, "r", encoding="utf-8") as f:
                RATE_LIST = json.load(f)
        except Exception as e:
            print("Error loading rates.json:", e)

def save_rates():
    try:
        with open(RATES_FILE, "w", encoding="utf-8") as f:
            json.dump(RATE_LIST, f, indent=4)
    except Exception as e:
        print("Error saving rates.json:", e)

load_rates()

# ═══════════════════════════════════════════════════════════
#  DATABASE  (SQLite replaces all Excel files)
# ═══════════════════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS beauticians (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                sno           INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT,
                beautician_id TEXT,
                name          TEXT,
                checkin_time  TEXT,
                checkout_time TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS services_log (
                sno             INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT,
                time            TEXT,
                beautician_id   TEXT,
                beautician_name TEXT,
                category        TEXT,
                service_name    TEXT,
                rate            REAL DEFAULT 0
            )
        """)
        conn.commit()

# ═══════════════════════════════════════════════════════════
#  FACE RECOGNITION
# ═══════════════════════════════════════════════════════════
def load_known_faces():
    global known_encodings, known_ids, known_names
    new_encodings, new_ids, new_names = [], [], {}

    try:
        with get_db() as conn:
            for row in conn.execute("SELECT id, name FROM beauticians").fetchall():
                new_names[row["id"]] = row["name"]
    except Exception as e:
        print("load_known_faces – DB error:", e)

    if not FACE_RECOGNITION_SUPPORTED:
        with face_lock:
            known_encodings, known_ids, known_names = new_encodings, new_ids, new_names
        print("Face recognition is not supported/enabled. Skipped face encoding cache.")
        return

    if not os.path.exists(KNOWN_FACES_DIR):
        with face_lock:
            known_encodings, known_ids, known_names = new_encodings, new_ids, new_names
        return

    cache = {}
    if os.path.exists(ENCODINGS_CACHE_FILE):
        try:
            with open(ENCODINGS_CACHE_FILE, "r") as f:
                cache = json.load(f)
        except Exception:
            pass

    updated_cache = {}
    for filename in os.listdir(KNOWN_FACES_DIR):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        filepath = os.path.join(KNOWN_FACES_DIR, filename)
        b_id = os.path.splitext(filename)[0].strip()
        mtime = os.path.getmtime(filepath)

        cached = cache.get(b_id)
        encoding = cached.get("encoding") if (cached and cached.get("mtime") == mtime) else None

        if encoding is None:
            try:
                img  = face_recognition.load_image_file(filepath)
                encs = face_recognition.face_encodings(img)
                encoding = list(encs[0]) if encs else None
                if encoding:
                    print(f"  Encoded face for ID: {b_id}")
                else:
                    print(f"  No face found in photo for ID: {b_id}")
            except Exception as e:
                print(f"  Error encoding {b_id}: {e}")

        if encoding:
            new_encodings.append(np.array(encoding))
            new_ids.append(b_id)
            updated_cache[b_id] = {"mtime": mtime, "encoding": encoding}

    try:
        with open(ENCODINGS_CACHE_FILE, "w") as f:
            json.dump(updated_cache, f)
    except Exception as e:
        print("Failed to save face cache:", e)

    with face_lock:
        known_encodings[:] = new_encodings
        known_ids[:] = new_ids
        known_names.clear()
        known_names.update(new_names)

# ═══════════════════════════════════════════════════════════
#  DATA LAYER  (mirrors Excel functions in beauty.py)
# ═══════════════════════════════════════════════════════════
def compute_beautician_stats(beautician_id):
    today_str           = datetime.now().strftime("%d/%m/%Y")
    current_month_year  = datetime.now().strftime("%m/%Y")
    s_today = s_month = s_total = m_today = m_month = m_total = 0
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT date, rate FROM services_log WHERE beautician_id=?",
                (str(beautician_id).strip(),)
            ).fetchall()
        for row in rows:
            d = str(row["date"] or "").strip()
            r = float(row["rate"] or 0)
            s_total += 1; m_total += r
            if d == today_str:
                s_today += 1; m_today += r
            if len(d) == 10 and d[3:] == current_month_year:
                s_month += 1; m_month += r
    except Exception as e:
        print("compute_beautician_stats error:", e)
    return {
        "services_today": s_today, "services_month": s_month, "services_total": s_total,
        "money_today": int(m_today), "money_month": int(m_month), "money_total": int(m_total)
    }

def compute_overall_stats():
    today_str        = datetime.now().strftime("%d/%m/%Y")
    monthly_earnings = {}
    total_today      = 0
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT date, rate FROM services_log").fetchall()
        for row in rows:
            d = str(row["date"] or "").strip()
            r = float(row["rate"] or 0)
            if d == today_str:
                total_today += r
            if len(d) == 10:
                my = d[3:]
                monthly_earnings[my] = monthly_earnings.get(my, 0) + r
    except Exception as e:
        print("compute_overall_stats error:", e)
    formatted = []
    try:
        for my in sorted(monthly_earnings, key=lambda x: datetime.strptime(x, "%m/%Y"), reverse=True):
            formatted.append({"month_str": datetime.strptime(my, "%m/%Y").strftime("%B %Y"),
                               "amount": int(monthly_earnings[my])})
    except Exception:
        pass
    return {"total_today": int(total_today), "monthly_breakdown": formatted}

def get_beauticians_list():
    out = []
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT id, name FROM beauticians ORDER BY name").fetchall():
                out.append({"id": row["id"], "name": row["name"],
                             "stats": compute_beautician_stats(row["id"])})
    except Exception as e:
        print("get_beauticians_list error:", e)
    return out

def log_beautician_attendance_face(beautician_id, name):
    today_str = datetime.now().strftime("%d/%m/%Y")
    now_time  = datetime.now().strftime("%H:%M:%S")
    try:
        with get_db() as conn:
            last = conn.execute(
                "SELECT sno, checkout_time FROM attendance "
                "WHERE date=? AND beautician_id=? ORDER BY sno DESC LIMIT 1",
                (today_str, str(beautician_id).strip())
            ).fetchone()
            if last is None or str(last["checkout_time"] or "").strip():
                conn.execute(
                    "INSERT INTO attendance (date, beautician_id, name, checkin_time, checkout_time) "
                    "VALUES (?,?,?,?,'')",
                    (today_str, beautician_id, name, now_time)
                )
                conn.commit()
                return True, "Checked In", now_time
            else:
                conn.execute(
                    "UPDATE attendance SET checkout_time=? WHERE sno=?",
                    (now_time, last["sno"])
                )
                conn.commit()
                return True, "Checked Out", now_time
    except Exception as e:
        print("log_beautician_attendance_face error:", e)
        return False, "Database error", ""

def log_session_transactions(beautician_id, name, services_list):
    if not services_list:
        return True
    now = datetime.now()
    try:
        with get_db() as conn:
            for item in services_list:
                rate = 0
                try: rate = float(item.get("rate", 0))
                except Exception: pass
                conn.execute(
                    "INSERT INTO services_log (date, time, beautician_id, beautician_name, "
                    "category, service_name, rate) VALUES (?,?,?,?,?,?,?)",
                    (now.strftime("%d/%m/%Y"), now.strftime("%H:%M:%S"),
                     beautician_id, name,
                     item.get("category", ""), item.get("name", ""), rate)
                )
            conn.commit()
        return True
    except Exception as e:
        print("log_session_transactions error:", e)
        return False

def log_service_transaction(beautician_id, name, category, service_name, rate):
    now = datetime.now()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO services_log (date, time, beautician_id, beautician_name, "
                "category, service_name, rate) VALUES (?,?,?,?,?,?,?)",
                (now.strftime("%d/%m/%Y"), now.strftime("%H:%M:%S"),
                 beautician_id, name, category, service_name, rate)
            )
            conn.commit()
        return True
    except Exception as e:
        print("log_service_transaction error:", e)
        return False

# ═══════════════════════════════════════════════════════════
#  SESSION MANAGEMENT
# ═══════════════════════════════════════════════════════════
def create_session():
    token = secrets.token_hex(32)
    admin_sessions[token] = time.time() + SESSION_DURATION
    return token

def valid_session(token):
    if not token:
        return False
    exp = admin_sessions.get(token)
    if exp and time.time() < exp:
        return True
    admin_sessions.pop(token, None)
    return False

def cookie_token(headers):
    for part in headers.get("Cookie", "").split(";"):
        part = part.strip()
        if part.startswith("admin_token="):
            return part[len("admin_token="):]
    return None

# ═══════════════════════════════════════════════════════════
#  HTTP HANDLER
# ═══════════════════════════════════════════════════════════
class BeautyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access log

    # ── helpers ──────────────────────────────────────────
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n:
            try: return json.loads(self.rfile.read(n).decode())
            except Exception: pass
        return {}

    def require_admin(self):
        """Return True and do nothing if authenticated; send 401 and return False otherwise."""
        if valid_session(cookie_token(self.headers)):
            return True
        self.send_json({"success": False, "error": "Unauthorized"}, 401)
        return False

    # ── GET ──────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self.send_html(HTML_TEMPLATE)

        elif path == "/api/get_rate_list":
            self.send_json(RATE_LIST)

        elif path in ("/admin", "/admin/"):
            if valid_session(cookie_token(self.headers)):
                self.send_html(ADMIN_DASHBOARD_HTML)
            else:
                self.send_html(ADMIN_LOGIN_HTML)

        elif path == "/admin/logout":
            tok = cookie_token(self.headers)
            admin_sessions.pop(tok, None)
            self.send_response(302)
            self.send_header("Location", "/admin")
            self.send_header("Set-Cookie", "admin_token=; Max-Age=0; Path=/")
            self.end_headers()

        elif path == "/admin/download_db":
            if not valid_session(cookie_token(self.headers)):
                self.send_response(302)
                self.send_header("Location", "/admin")
                self.end_headers()
                return
            if os.path.exists(DB_FILE):
                with open(DB_FILE, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="beautyparlour.db"')
                self.send_header("Content-Length", len(data))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_html("<p>Database not found.</p>", 404)

        elif path == "/favicon.ico":
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
            if os.path.exists(icon_path):
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                with open(icon_path, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    # ── POST ─────────────────────────────────────────────
    def do_POST(self):
        global ADMIN_USERNAME, ADMIN_PASSWORD, known_encodings, known_ids, known_names
        path = urlparse(self.path).path

        # ── Public beautician APIs ──
        if path == "/api/get_dashboard":
            params = self.read_json()
            b_id = params.get("beautician_id")
            if b_id:
                personal  = compute_beautician_stats(b_id)
                b_id_str  = str(b_id).strip()
                blist     = [b for b in get_beauticians_list() if b["id"] == b_id_str]
                month_str = datetime.now().strftime("%B %Y")
                overall   = {
                    "total_today": personal["money_today"],
                    "monthly_breakdown": (
                        [{"month_str": month_str, "amount": personal["money_month"]}]
                        if personal["money_month"] > 0 else []
                    )
                }
            else:
                blist   = []
                overall = {"total_today": 0, "monthly_breakdown": []}
            self.send_json({"success": True, "beauticians": blist, "overall": overall})

        elif path == "/api/get_rate_list":
            self.send_json(RATE_LIST)

        elif path == "/api/log_attendance":
            p = self.read_json()
            ok, action, t = log_beautician_attendance_face(p.get("beautician_id"), p.get("name"))
            self.send_json({"success": ok, "action": action, "time": t})

        elif path == "/api/log_service":
            p    = self.read_json()
            rate = 0
            try: rate = float(p.get("rate", 0))
            except Exception: pass
            ok = log_service_transaction(
                p.get("beautician_id"), p.get("beautician_name"),
                p.get("category"), p.get("service_name"), rate
            )
            self.send_json({"success": ok})

        elif path == "/api/log_session":
            p  = self.read_json()
            ok = log_session_transactions(
                p.get("beautician_id"), p.get("beautician_name"), p.get("services", [])
            )
            self.send_json({"success": ok})

        elif path == "/api/recognize":
            if not FACE_RECOGNITION_SUPPORTED:
                self.send_json({
                    "success": False,
                    "error": "Face recognition is disabled on this server (Render Free Tier constraints). Please use manual check-in or run locally."
                })
                return
            p       = self.read_json()
            img_b64 = p.get("image", "")
            if not img_b64:
                self.send_json({"success": False, "error": "No image data"}); return
            if "," in img_b64:
                img_b64 = img_b64.split(",", 1)[1]
            try:
                nparr  = np.frombuffer(base64.b64decode(img_b64), np.uint8)
                frame  = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.send_json({"success": False, "error": "Could not decode image"}); return
                rgb       = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locs = face_recognition.face_locations(rgb, model=MODEL)
                face_encs = face_recognition.face_encodings(rgb, face_locs)
                if not face_locs:
                    self.send_json({"success": False,
                        "error": "No face detected. Please align your face inside the camera view."}); return
                with face_lock:
                    if not known_encodings:
                        self.send_json({"success": False,
                            "error": "No beautician photos saved on server. Please upload photos in Admin panel."}); return
                    dists    = face_recognition.face_distance(known_encodings, face_encs[0])
                    best_idx = int(np.argmin(dists))
                    if dists[best_idx] >= TOLERANCE:
                        self.send_json({"success": False,
                            "error": "Face not recognized. Please verify you are registered and your photo is uploaded."}); return
                    matched_id   = known_ids[best_idx]
                    matched_name = known_names.get(matched_id, "Unknown")
                ok, action, t = log_beautician_attendance_face(matched_id, matched_name)
                if ok:
                    self.send_json({"success": True, "name": matched_name,
                                    "id": matched_id, "action": action, "time": t})
                else:
                    self.send_json({"success": False, "error": action})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        # ── Admin login ──
        elif path == "/admin/login":
            p = self.read_json()
            attempted_user = (p.get("username") or "").strip()
            attempted_pass = p.get("password") or ""
            print(f"[AUTH] Login attempt for username: '{attempted_user}'")
            if attempted_user == ADMIN_USERNAME and attempted_pass == ADMIN_PASSWORD:
                token = create_session()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie",
                    f"admin_token={token}; Max-Age={SESSION_DURATION}; Path=/; HttpOnly")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            else:
                self.send_json({"success": False, "error": "Invalid username or password"})

        # ── Admin data fetch ──
        elif path == "/admin/get_data":
            if not self.require_admin(): return
            try:
                with get_db() as conn:
                    beauticians = [dict(r) for r in
                        conn.execute("SELECT id, name FROM beauticians ORDER BY name").fetchall()]
                    attendance  = [dict(r) for r in
                        conn.execute("SELECT * FROM attendance ORDER BY sno DESC LIMIT 200").fetchall()]
                    services    = [dict(r) for r in
                        conn.execute("SELECT * FROM services_log ORDER BY sno DESC LIMIT 200").fetchall()]
                for b in beauticians:
                    b["has_photo"] = any(
                        os.path.exists(os.path.join(KNOWN_FACES_DIR, f"{b['id']}{ext}"))
                        for ext in (".jpg", ".jpeg", ".png")
                    )
                    b["stats"] = compute_beautician_stats(b["id"])
                self.send_json({"success": True, "beauticians": beauticians,
                                "attendance": attendance, "services": services,
                                "overall": compute_overall_stats(),
                                "rate_list": RATE_LIST})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        # ── Admin: add beautician ──
        elif path == "/admin/add_beautician":
            if not self.require_admin(): return
            p    = self.read_json()
            b_id = p.get("id", "").strip()
            name = p.get("name", "").strip()
            if not b_id or not name:
                self.send_json({"success": False, "error": "ID and Name are required"}); return
            try:
                with get_db() as conn:
                    conn.execute("INSERT OR REPLACE INTO beauticians (id, name) VALUES (?,?)", (b_id, name))
                    conn.commit()
                threading.Thread(target=load_known_faces, daemon=True).start()
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        # ── Admin: delete beautician ──
        elif path == "/admin/delete_beautician":
            if not self.require_admin(): return
            p    = self.read_json()
            b_id = p.get("id", "").strip()
            if not b_id:
                self.send_json({"success": False, "error": "ID required"}); return
            try:
                with get_db() as conn:
                    conn.execute("DELETE FROM beauticians WHERE id=?", (b_id,))
                    conn.execute("DELETE FROM attendance WHERE beautician_id=?", (b_id,))
                    conn.execute("DELETE FROM services_log WHERE beautician_id=?", (b_id,))
                    conn.commit()
                for ext in (".jpg", ".jpeg", ".png"):
                    p2 = os.path.join(KNOWN_FACES_DIR, f"{b_id}{ext}")
                    if os.path.exists(p2):
                        try: os.remove(p2)
                        except Exception: pass
                if os.path.exists(ENCODINGS_CACHE_FILE):
                    try:
                        with open(ENCODINGS_CACHE_FILE, "r") as f: cache = json.load(f)
                        cache.pop(b_id, None)
                        with open(ENCODINGS_CACHE_FILE, "w") as f: json.dump(cache, f)
                    except Exception: pass
                threading.Thread(target=load_known_faces, daemon=True).start()
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        # ── Admin: update rate list ──
        elif path == "/admin/update_rate_list":
            if not self.require_admin(): return
            p = self.read_json()
            new_rates = p.get("rate_list")
            if not isinstance(new_rates, dict):
                self.send_json({"success": False, "error": "Invalid rate list format"}); return
            validated = {}
            for cat, items in new_rates.items():
                if not isinstance(items, list):
                    continue
                v_items = []
                for item in items:
                    if isinstance(item, dict) and "name" in item and "rate" in item:
                        n = str(item["name"]).strip()
                        r = item["rate"]
                        if isinstance(r, (int, float)):
                            pass
                        elif str(r).strip().lower() == "ask":
                            r = "Ask"
                        else:
                            try:
                                r = float(r)
                            except ValueError:
                                r = "Ask"
                        if n:
                            v_items.append({"name": n, "rate": r})
                validated[cat] = v_items
            
            RATE_LIST.clear()
            RATE_LIST.update(validated)
            save_rates()
            self.send_json({"success": True})

        # ── Admin: reset database ──
        elif path == "/admin/reset_db":
            if not self.require_admin(): return
            try:
                with get_db() as conn:
                    conn.execute("DROP TABLE IF EXISTS beauticians")
                    conn.execute("DROP TABLE IF EXISTS attendance")
                    conn.execute("DROP TABLE IF EXISTS services_log")
                    conn.commit()
                init_db()
                with face_lock:
                    known_encodings = []
                    known_ids = []
                    known_names = {}
                if os.path.exists(KNOWN_FACES_DIR):
                    for filename in os.listdir(KNOWN_FACES_DIR):
                        p = os.path.join(KNOWN_FACES_DIR, filename)
                        if os.path.isfile(p):
                            try: os.remove(p)
                            except Exception: pass
                if os.path.exists(ENCODINGS_CACHE_FILE):
                    try: os.remove(ENCODINGS_CACHE_FILE)
                    except Exception: pass
                load_known_faces()
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        # ── Admin: upload face photo (base64 JSON) ──
        elif path == "/admin/upload_photo":
            if not self.require_admin(): return
            p        = self.read_json()
            b_id     = p.get("beautician_id", "").strip()
            photo_b64 = p.get("photo_base64", "")
            filename = p.get("filename", "photo.jpg")
            if not b_id or not photo_b64:
                self.send_json({"success": False, "error": "beautician_id and photo_base64 required"}); return
            try:
                with get_db() as conn:
                    if not conn.execute("SELECT 1 FROM beauticians WHERE id=?", (b_id,)).fetchone():
                        self.send_json({"success": False, "error": "Beautician not found"}); return
                img_bytes = base64.b64decode(photo_b64)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in (".jpg", ".jpeg", ".png"):
                    ext = ".jpg"
                for e in (".jpg", ".jpeg", ".png"):
                    old = os.path.join(KNOWN_FACES_DIR, f"{b_id}{e}")
                    if os.path.exists(old):
                        try: os.remove(old)
                        except Exception: pass
                with open(os.path.join(KNOWN_FACES_DIR, f"{b_id}{ext}"), "wb") as f:
                    f.write(img_bytes)
                threading.Thread(target=load_known_faces, daemon=True).start()
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        # ── Admin: change credentials ──
        elif path == "/admin/change_password":
            if not self.require_admin(): return
            p = self.read_json()
            new_user = p.get("username", "").strip()
            new_pass = p.get("password", "").strip()
            if not new_user or not new_pass:
                self.send_json({"success": False, "error": "Username and password required"}); return
            ADMIN_USERNAME = new_user
            ADMIN_PASSWORD = new_pass
            self.send_json({"success": True,
                "message": "Credentials updated for this session. Set ADMIN_USERNAME and ADMIN_PASSWORD env vars to make permanent."})

        else:
            self.send_response(404)
            self.end_headers()

# ═══════════════════════════════════════════════════════════
#  HTML TEMPLATE  (beautician-facing portal — same as beauty.py)
# ═══════════════════════════════════════════════════════════
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kaya Kalp Beauty Parlour</title>
    <meta name="description" content="Kaya Kalp Beauty Parlour – Beautician portal for attendance, service logging and rate list.">
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #d48a97;
            --primary-hover: #c47683;
            --accent: #e5a9b4;
            --bg-dark: #12090b;
            --bg-light: #1c1114;
            --card-bg: rgba(43, 24, 30, 0.65);
            --card-border: rgba(229, 169, 180, 0.15);
            --card-hover-border: rgba(229, 169, 180, 0.4);
            --text-color: #fceef0;
            --text-sub: #d9c5c7;
            --accent-glow: rgba(229, 169, 180, 0.25);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at top, var(--bg-light) 0%, var(--bg-dark) 100%);
            color: var(--text-color);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            justify-content: center;
        }
        .container { width: 100%; max-width: 1200px; }
        header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--card-border);
        }
        h1 {
            font-size: 34px;
            font-weight: 700;
            background: linear-gradient(135deg, #ffffff 0%, var(--accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            font-size: 13px;
            color: var(--text-sub);
            margin-top: 5px;
            letter-spacing: 2px;
            text-transform: uppercase;
        }
        .view-panel { display: none; }
        .view-panel.active { display: block; }
        .card {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
            margin-bottom: 20px;
        }
        .table-responsive { overflow-x: auto; border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; text-align: left; white-space: nowrap; }
        th {
            padding: 16px;
            color: #ffffff;
            font-weight: 600;
            border-bottom: 2px solid var(--card-border);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        td { padding: 16px; border-bottom: 1px solid var(--card-border); font-size: 15px; vertical-align: middle; }
        tr:hover td { background: rgba(229,169,180,0.04); }
        .checkbox-container { display: inline-block; position: relative; cursor: pointer; width: 22px; height: 22px; }
        .checkbox-container input { opacity: 0; width: 0; height: 0; }
        .checkmark {
            position: absolute; top: 0; left: 0;
            height: 22px; width: 22px;
            background-color: rgba(255,255,255,0.08);
            border: 1px solid var(--primary);
            border-radius: 6px;
            transition: all 0.2s;
        }
        .checkbox-container input:checked ~ .checkmark {
            background-color: var(--primary);
            border-color: var(--primary);
            box-shadow: 0 0 10px var(--primary);
        }
        .checkmark:after {
            content: "";
            position: absolute;
            display: none;
            left: 7px; top: 3px;
            width: 5px; height: 10px;
            border: solid white;
            border-width: 0 2px 2px 0;
            transform: rotate(45deg);
        }
        .checkbox-container input:checked ~ .checkmark:after { display: block; }
        .btn-proceed {
            padding: 14px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%);
            border: none;
            color: #ffffff;
            font-size: 16px;
            font-weight: 700;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 4px 12px rgba(212,138,151,0.3);
            text-align: center;
            flex: 1;
            min-width: 220px;
        }
        .btn-proceed:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(212,138,151,0.5); }
        .bottom-stats {
            margin-top: 30px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }
        .stat-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 16px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
        .stat-title { font-size: 12px; color: var(--text-sub); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; font-weight: 600; }
        .stat-value { font-size: 26px; font-weight: 700; color: #ffffff; }
        .stat-list { max-height: 180px; overflow-y: auto; margin-top: 12px; padding-right: 5px; }
        .stat-item { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(229,169,180,0.1); font-size: 14px; }
        .stat-item:last-child { border-bottom: none; }
        .rate-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; flex-wrap: wrap; gap: 15px; }
        .beautician-badge { background: rgba(212,138,151,0.15); border: 1px solid var(--primary); color: var(--accent); padding: 8px 18px; border-radius: 30px; font-weight: 600; font-size: 14px; }
        .category-tabs { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 10px; margin-bottom: 25px; scrollbar-width: thin; }
        .category-tabs::-webkit-scrollbar { height: 6px; }
        .category-tabs::-webkit-scrollbar-thumb { background: rgba(229,169,180,0.2); border-radius: 3px; }
        .category-tab {
            padding: 10px 20px;
            background: rgba(255,255,255,0.04);
            border: 1px solid var(--card-border);
            border-radius: 30px;
            color: var(--text-sub);
            cursor: pointer;
            white-space: nowrap;
            font-weight: 500;
            font-size: 14px;
            transition: all 0.2s;
        }
        .category-tab:hover { border-color: var(--card-hover-border); color: #ffffff; }
        .category-tab.active { background: var(--primary); color: #ffffff; border-color: var(--primary); box-shadow: 0 0 10px rgba(212,138,151,0.3); }
        .services-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; margin-bottom: 120px; }
        .service-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            min-height: 130px;
        }
        .service-card:hover { border-color: var(--primary); transform: translateY(-4px); box-shadow: 0 8px 20px rgba(212,138,151,0.2); }
        .service-name { font-weight: 600; font-size: 15px; line-height: 1.4; color: #ffffff; margin-bottom: 10px; }
        .service-price { font-size: 16px; color: var(--accent); font-weight: 700; }
        .session-drawer {
            position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
            width: 90%; max-width: 600px;
            background: rgba(28,13,18,0.95);
            backdrop-filter: blur(20px);
            border: 1px solid var(--primary);
            border-radius: 20px;
            padding: 18px 24px;
            box-shadow: 0 15px 40px rgba(0,0,0,0.6);
            z-index: 100;
            display: flex; flex-direction: column; gap: 12px;
        }
        .drawer-top { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--card-border); padding-bottom: 8px; }
        .drawer-title { font-weight: 700; font-size: 16px; color: #ffffff; }
        .drawer-list { max-height: 100px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
        .drawer-item { font-size: 13px; display: flex; justify-content: space-between; color: var(--text-sub); }
        .drawer-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 5px; }
        .drawer-total { font-weight: 700; font-size: 18px; color: var(--accent); }
        .btn-finish { padding: 10px 24px; background: #6bb393; color: white; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; transition: all 0.2s; box-shadow: 0 4px 10px rgba(107,179,147,0.3); }
        .btn-finish:hover { background: #5aa282; transform: translateY(-1px); }
        .btn-back { background: transparent; border: 1px solid var(--card-border); color: var(--text-sub); padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.2s; }
        .btn-back:hover { color: #ffffff; border-color: #ffffff; }
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; z-index: 1000; }
        .modal { background: #231217; border: 1px solid var(--primary); border-radius: 20px; padding: 26px; width: 90%; max-width: 400px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); text-align: center; }
        .modal-title { font-weight: 700; font-size: 18px; margin-bottom: 12px; color: #ffffff; }
        .modal-desc { font-size: 14px; color: var(--text-sub); margin-bottom: 18px; }
        .modal-input { width: 100%; padding: 12px; background: rgba(0,0,0,0.3); border: 1px solid var(--card-border); border-radius: 8px; color: #ffffff; font-size: 16px; outline: none; margin-bottom: 20px; text-align: center; font-family: inherit; }
        .modal-input:focus { border-color: var(--primary); }
        .modal-buttons { display: flex; gap: 12px; }
        .btn-modal-submit { flex: 1; padding: 12px; background: var(--primary); color: white; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
        .btn-modal-cancel { flex: 1; padding: 12px; background: transparent; border: 1px solid var(--card-border); color: var(--text-sub); border-radius: 8px; cursor: pointer; }
        .camera-wrapper { position: relative; width: 100%; max-width: 480px; margin: 0 auto 20px auto; background: #000; border-radius: 16px; overflow: hidden; border: 2px solid var(--primary); aspect-ratio: 4/3; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        #webcamVideo { width: 100%; height: 100%; object-fit: cover; }
        .scan-line { position: absolute; top: 0; left: 0; width: 100%; height: 4px; background: var(--accent); box-shadow: 0 0 15px var(--accent); animation: scanAnimation 2s linear infinite; pointer-events: none; }
        @keyframes scanAnimation { 0%{top:0%} 50%{top:100%} 100%{top:0%} }
        .status-info,.status-scanning,.status-checked-in,.status-checked-out,.status-error { border-radius: 12px; padding: 16px; text-align: center; font-size: 15px; margin-bottom: 20px; min-height: 60px; display: flex; align-items: center; justify-content: center; line-height: 1.5; font-weight: 500; }
        .status-info { background: rgba(255,255,255,0.05); border: 1px solid var(--card-border); }
        .status-scanning { background: rgba(229,169,180,0.1); border: 1px solid var(--accent); }
        .status-checked-in { background: rgba(107,179,147,0.15); border: 1px solid #6bb393; color: #a8ebd1; }
        .status-checked-out { background: rgba(212,138,151,0.15); border: 1px solid var(--primary); color: #f7cbd2; }
        .status-error { background: rgba(255,99,71,0.15); border: 1px solid #FF6347; color: #ffb3a7; }
        .toast-container { position: fixed; bottom: 140px; left: 20px; z-index: 1000; display: flex; flex-direction: column; gap: 10px; }
        .toast { background: rgba(43,24,30,0.9); border-left: 4px solid var(--primary); padding: 12px 20px; border-radius: 8px; color: #ffffff; box-shadow: 0 4px 15px rgba(0,0,0,0.4); font-weight: 500; animation: slideIn 0.3s forwards; min-width: 250px; }
        @keyframes slideIn { from{transform:translateX(-120%);opacity:0} to{transform:translateX(0);opacity:1} }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>KAYA KALP</h1>
            <div class="subtitle">Beauty Parlour Portal</div>
        </header>

        <!-- View 1: Dashboard -->
        <div id="dashboardView" class="view-panel">
            <div class="card">
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th style="width:50px;">Select</th>
                                <th>Name of Beautician</th>
                                <th>Services Today</th>
                                <th>Services Month</th>
                                <th>Services Total</th>
                                <th>Earnings Today</th>
                                <th>Earnings Month</th>
                            </tr>
                        </thead>
                        <tbody id="beauticianTableBody"></tbody>
                    </table>
                </div>
                <div style="display:flex;justify-content:center;gap:15px;flex-wrap:wrap;margin-top:20px;">
                    <button class="btn-proceed" style="margin:0;" onclick="proceedToRateList()">Proceed to Rate List</button>
                    <button class="btn-proceed" style="margin:0;background:linear-gradient(135deg,var(--accent) 0%,#d48a97 100%);color:#12090b;box-shadow:0 4px 12px var(--accent-glow);" onclick="openFaceAttendance()">Face Attendance Check</button>
                    <button class="btn-proceed" style="margin:0;background:#6c757d;" onclick="logoutBeautician()">Lock / Switch User</button>
                </div>
            </div>
            <div class="bottom-stats">
                <div class="stat-card" style="text-align:center;">
                    <div class="stat-title" id="todayStatTitle">Total Money Made Today</div>
                    <div class="stat-value" id="overallTodayTotal">Rs. 0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title" id="monthStatTitle">Monthly Combined Earnings</div>
                    <div class="stat-list" id="monthlyEarningsList"></div>
                </div>
            </div>
        </div>

        <!-- View 2: Rate List -->
        <div id="rateListView" class="view-panel">
            <div class="rate-header">
                <button class="btn-back" onclick="backToDashboard()">&#8678; Back to Dashboard</button>
                <div class="beautician-badge" id="currentBeauticianBadge">Beautician: </div>
            </div>
            <div class="category-tabs" id="categoryTabs"></div>
            <div class="services-grid" id="servicesGrid"></div>
            <div class="session-drawer" id="sessionDrawer" style="display:none;">
                <div class="drawer-top">
                    <div class="drawer-title">Current Customer Session</div>
                    <button class="btn-back" style="padding:4px 8px;font-size:11px;" onclick="clearSessionCart()">Clear</button>
                </div>
                <div class="drawer-list" id="sessionList"></div>
                <div class="drawer-actions">
                    <div class="drawer-total" id="sessionTotalDisplay">Total: Rs. 0</div>
                    <button class="btn-finish" onclick="finishSession()">Finish Customer</button>
                </div>
            </div>
        </div>

        <!-- View 3: Face Attendance -->
        <div id="faceAttendanceView" class="view-panel active">
            <div class="rate-header">
                <button class="btn-back" id="faceBackBtn" style="display:none;" onclick="closeFaceAttendance()">&#8678; Back to Dashboard</button>
                <div class="beautician-badge">Face Scanner Active</div>
            </div>
            <div class="card" style="text-align:center;max-width:600px;margin:0 auto;">
                <div class="camera-wrapper">
                    <video id="webcamVideo" autoplay playsinline muted></video>
                    <div class="scan-line"></div>
                </div>
                <div id="cameraStatus" class="status-info">Point at your face and click <strong>Scan Face</strong> to check-in.</div>
                <button class="btn-proceed" style="max-width:250px;margin:10px auto;" onclick="scanFace()">Scan Face</button>
            </div>
        </div>
    </div>

    <!-- Price Modal -->
    <div class="modal-overlay" id="priceModal">
        <div class="modal">
            <div class="modal-title" id="modalTitle">Custom Service Price</div>
            <div class="modal-desc" id="modalDesc">Enter service price in Rupees:</div>
            <input type="number" class="modal-input" id="modalPriceInput" min="0" placeholder="e.g. 500">
            <div class="modal-buttons">
                <button class="btn-modal-cancel" onclick="closePriceModal()">Cancel</button>
                <button class="btn-modal-submit" onclick="submitPriceModal()">Submit Price</button>
            </div>
        </div>
    </div>

    <div class="toast-container" id="toastContainer"></div>

    <script>
        let currentBeautician = null;
        let rateListData = null;
        let currentCategory = "";
        let sessionCart = [];
        let sessionTotal = 0;
        let pendingService = null;
        let pendingCategory = null;
        let cameraStream = null;
        let scanning = false;
        let authenticated = false;

        document.addEventListener("DOMContentLoaded", () => {
            loadDashboard();
            loadRateListData();
            startCamera();
        });

        function loadDashboard() {
            const payload = {};
            if (currentBeautician) payload.beautician_id = currentBeautician.id;
            fetch("/api/get_dashboard", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload)
            }).then(r => r.json()).then(data => {
                if (data.success) renderDashboard(data);
            }).catch(() => showToast("Error loading dashboard data."));
        }

        function loadRateListData() {
            fetch("/api/get_rate_list").then(r => r.json()).then(data => { rateListData = data; });
        }

        function renderDashboard(data) {
            const tbody = document.getElementById("beauticianTableBody");
            tbody.innerHTML = "";
            if (data.beauticians.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-sub);">No beauticians registered. Please add them in the Admin Panel at /admin.</td></tr>`;
            } else {
                data.beauticians.forEach(b => {
                    const isChecked = currentBeautician && currentBeautician.id === b.id ? "checked" : "";
                    const row = document.createElement("tr");
                    row.innerHTML = `
                        <td><label class="checkbox-container"><input type="checkbox" name="beauticianSelect" value="${b.id}" data-name="${b.name}" ${isChecked} onchange="handleSingleSelect(this)"><span class="checkmark"></span></label></td>
                        <td style="font-weight:600;color:#ffffff;">${b.name}</td>
                        <td>${b.stats.services_today}</td>
                        <td>${b.stats.services_month}</td>
                        <td>${b.stats.services_total}</td>
                        <td style="color:var(--accent);font-weight:600;">Rs. ${b.stats.money_today}</td>
                        <td style="color:var(--accent);font-weight:600;">Rs. ${b.stats.money_month}</td>
                    `;
                    tbody.appendChild(row);
                });
            }
            document.getElementById("overallTodayTotal").innerText = `Rs. ${data.overall.total_today}`;
            const list = document.getElementById("monthlyEarningsList");
            list.innerHTML = "";
            if (data.overall.monthly_breakdown.length === 0) {
                list.innerHTML = `<div style="text-align:center;color:var(--text-sub);padding:20px 0;">No transaction records found.</div>`;
            } else {
                data.overall.monthly_breakdown.forEach(item => {
                    const row = document.createElement("div");
                    row.className = "stat-item";
                    row.innerHTML = `<span style="font-weight:500;">${item.month_str}</span><span style="font-weight:700;color:var(--accent);">Rs. ${item.amount}</span>`;
                    list.appendChild(row);
                });
            }
            document.querySelector(".bottom-stats").style.display = "grid";
            if (currentBeautician) {
                document.getElementById("todayStatTitle").innerText = "Your Earnings Today";
                document.getElementById("monthStatTitle").innerText = "Your Earnings This Month";
            } else {
                document.getElementById("todayStatTitle").innerText = "Total Money Made Today";
                document.getElementById("monthStatTitle").innerText = "Monthly Combined Earnings";
            }
        }

        function handleSingleSelect(checkbox) {
            if (checkbox.checked) {
                document.getElementsByName("beauticianSelect").forEach(cb => { if (cb !== checkbox) cb.checked = false; });
            }
        }
        document.addEventListener("change", e => { if (e.target.name === "beauticianSelect") handleSingleSelect(e.target); });

        function getSelectedBeautician() {
            for (let cb of document.getElementsByName("beauticianSelect")) {
                if (cb.checked) return { id: cb.value, name: cb.getAttribute("data-name") };
            }
            return null;
        }

        function proceedToRateList() {
            const selected = getSelectedBeautician();
            if (!selected) { alert("Please select a Beautician first."); return; }
            if (!rateListData) { showToast("Rate list not loaded yet. Please retry."); loadRateListData(); return; }
            currentBeautician = selected;
            document.getElementById("currentBeauticianBadge").innerText = `Beautician: ${currentBeautician.name}`;
            document.getElementById("dashboardView").classList.remove("active");
            document.getElementById("rateListView").classList.add("active");
            resetSessionCart();
            renderCategoryTabs();
        }

        function backToDashboard() {
            if (sessionCart.length > 0 && !confirm("Discard current session and go back?")) return;
            document.getElementById("rateListView").classList.remove("active");
            document.getElementById("dashboardView").classList.add("active");
            loadDashboard();
            currentBeautician = null;
            resetSessionCart();
        }

        function renderCategoryTabs() {
            const container = document.getElementById("categoryTabs");
            container.innerHTML = "";
            const cats = Object.keys(rateListData);
            if (cats.length > 0) {
                currentCategory = cats[0];
                cats.forEach(cat => {
                    const tab = document.createElement("div");
                    tab.className = `category-tab ${cat === currentCategory ? "active" : ""}`;
                    tab.innerText = cat;
                    tab.onclick = () => {
                        document.querySelectorAll(".category-tab").forEach(t => t.classList.remove("active"));
                        tab.classList.add("active");
                        currentCategory = cat;
                        renderServices();
                    };
                    container.appendChild(tab);
                });
                renderServices();
            }
        }

        function renderServices() {
            const grid = document.getElementById("servicesGrid");
            grid.innerHTML = "";
            rateListData[currentCategory].forEach(serv => {
                const card = document.createElement("div");
                card.className = "service-card";
                card.onclick = () => handleServiceClick(serv);
                const rateText = typeof serv.rate === "number" ? `Rs. ${serv.rate}` : "Ask Price";
                card.innerHTML = `<div class="service-name">${serv.name}</div><div class="service-price">${rateText}</div>`;
                grid.appendChild(card);
            });
        }

        function handleServiceClick(service) {
            if (service.rate === "Ask") openPriceModal(service, currentCategory);
            else addLocalService(currentCategory, service.name, service.rate);
        }

        function openPriceModal(service, category) {
            pendingService = service; pendingCategory = category;
            document.getElementById("modalTitle").innerText = service.name;
            document.getElementById("modalPriceInput").value = "";
            document.getElementById("priceModal").style.display = "flex";
            document.getElementById("modalPriceInput").focus();
        }
        function closePriceModal() { document.getElementById("priceModal").style.display = "none"; pendingService = pendingCategory = null; }
        function submitPriceModal() {
            const price = parseFloat(document.getElementById("modalPriceInput").value);
            if (isNaN(price) || price < 0) { alert("Please enter a valid price."); return; }
            const sn = pendingService.name; const cat = pendingCategory;
            closePriceModal();
            addLocalService(cat, sn, price);
        }

        function addLocalService(category, name, rate) {
            sessionCart.push({category, name, rate});
            sessionTotal += rate;
            showToast(`Added: ${name} – Rs. ${rate}`);
            document.getElementById("sessionDrawer").style.display = "flex";
            const item = document.createElement("div");
            item.className = "drawer-item";
            item.innerHTML = `<span>${name}</span><span style="font-weight:600;">Rs. ${rate}</span>`;
            const list = document.getElementById("sessionList");
            list.appendChild(item);
            list.scrollTop = list.scrollHeight;
            document.getElementById("sessionTotalDisplay").innerText = `Total: Rs. ${sessionTotal}`;
        }

        function resetSessionCart() {
            sessionCart = []; sessionTotal = 0;
            document.getElementById("sessionList").innerHTML = "";
            document.getElementById("sessionDrawer").style.display = "none";
        }

        function clearSessionCart() {
            if (sessionCart.length === 0) return;
            const removed = sessionCart.pop();
            sessionTotal = Math.max(0, sessionTotal - removed.rate);
            const list = document.getElementById("sessionList");
            if (list.lastElementChild) list.lastElementChild.remove();
            document.getElementById("sessionTotalDisplay").innerText = `Total: Rs. ${sessionTotal}`;
            if (sessionCart.length === 0) document.getElementById("sessionDrawer").style.display = "none";
        }

        function finishSession() {
            if (sessionCart.length === 0) { backToDashboard(); return; }
            fetch("/api/log_session", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({beautician_id: currentBeautician.id, beautician_name: currentBeautician.name, services: sessionCart})
            }).then(r => r.json()).then(data => {
                if (data.success) { alert(`Customer bill of Rs. ${sessionTotal} logged successfully!`); backToDashboard(); }
                else alert("Failed to save session: " + (data.error || "Server error"));
            }).catch(() => alert("Failed to connect to server."));
        }

        function showToast(message) {
            const container = document.getElementById("toastContainer");
            const toast = document.createElement("div");
            toast.className = "toast";
            toast.innerText = message;
            container.appendChild(toast);
            setTimeout(() => {
                toast.style.animation = "slideIn 0.3s reverse forwards";
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        async function startCamera() {
            const video = document.getElementById("webcamVideo");
            try {
                cameraStream = await navigator.mediaDevices.getUserMedia({video:{facingMode:"user",width:{ideal:640},height:{ideal:480}},audio:false});
                video.srcObject = cameraStream;
                document.getElementById("cameraStatus").innerHTML = "Point at your face and click <strong>Scan Face</strong> to check-in or check-out.";
                document.getElementById("cameraStatus").className = "status-info";
            } catch(e) {
                document.getElementById("cameraStatus").innerHTML = "Webcam error: " + e.message;
                document.getElementById("cameraStatus").className = "status-error";
            }
        }

        function stopCamera() {
            if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
            const video = document.getElementById("webcamVideo");
            if (video) video.srcObject = null;
        }

        function openFaceAttendance() {
            document.getElementById("dashboardView").classList.remove("active");
            document.getElementById("faceAttendanceView").classList.add("active");
            startCamera();
        }

        function closeFaceAttendance() {
            stopCamera();
            document.getElementById("faceAttendanceView").classList.remove("active");
            document.getElementById("dashboardView").classList.add("active");
            loadDashboard();
        }

        function logoutBeautician() {
            authenticated = false; currentBeautician = null;
            document.getElementById("dashboardView").classList.remove("active");
            document.getElementById("faceAttendanceView").classList.add("active");
            document.getElementById("faceBackBtn").style.display = "none";
            startCamera();
        }

        async function scanFace() {
            if (scanning) return;
            const video = document.getElementById("webcamVideo");
            if (!video.srcObject) { showToast("Webcam is not started."); return; }
            scanning = true;
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
            const imageData = canvas.toDataURL("image/jpeg", 0.85);
            const statusBox = document.getElementById("cameraStatus");
            statusBox.innerHTML = "&#128269; Scanning face...";
            statusBox.className = "status-scanning";
            fetch("/api/recognize", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({image: imageData})
            }).then(r => r.json()).then(data => {
                scanning = false;
                if (data.success) {
                    const {name, action, time: timeStr} = data;
                    if (action === "Checked In") {
                        statusBox.innerHTML = `&#127800; Welcome, <strong>${name}</strong>!<br>Checked in at ${timeStr}.`;
                        statusBox.className = "status-checked-in";
                        authenticated = true;
                        currentBeautician = {id: data.id, name};
                        setTimeout(() => {
                            document.getElementById("faceAttendanceView").classList.remove("active");
                            document.getElementById("dashboardView").classList.add("active");
                            document.getElementById("faceBackBtn").style.display = "block";
                            loadDashboard(); stopCamera();
                        }, 2000);
                    } else {
                        statusBox.innerHTML = `&#128075; Goodbye, <strong>${name}</strong>!<br>Checked out at ${timeStr}.`;
                        statusBox.className = "status-checked-out";
                        authenticated = false; currentBeautician = null;
                        document.getElementById("faceBackBtn").style.display = "none";
                    }
                    showToast(`${name}: ${action}`);
                } else {
                    statusBox.innerHTML = "&#9888; " + (data.error || "Scanning failed.");
                    statusBox.className = "status-error";
                }
            }).catch(() => {
                scanning = false;
                document.getElementById("cameraStatus").innerHTML = "&#9888; Connection error.";
                document.getElementById("cameraStatus").className = "status-error";
            });
        }
    </script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════
#  ADMIN LOGIN PAGE
# ═══════════════════════════════════════════════════════════
ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kaya Kalp – Admin Login</title>
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{
            font-family:'Outfit',sans-serif;
            background:radial-gradient(circle at top,#1c1114 0%,#12090b 100%);
            min-height:100vh;display:flex;align-items:center;justify-content:center;
            color:#fceef0;
        }
        .login-card{
            background:rgba(43,24,30,0.7);
            backdrop-filter:blur(20px);
            border:1px solid rgba(229,169,180,0.2);
            border-radius:24px;
            padding:48px 40px;
            width:90%;max-width:420px;
            box-shadow:0 20px 60px rgba(0,0,0,0.6);
            text-align:center;
        }
        .logo{font-size:32px;font-weight:700;background:linear-gradient(135deg,#fff 0%,#e5a9b4 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px;}
        .subtitle{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#d9c5c7;margin-bottom:36px;}
        label{display:block;text-align:left;font-size:12px;font-weight:600;color:#d9c5c7;margin-bottom:6px;letter-spacing:0.5px;text-transform:uppercase;}
        input{
            width:100%;padding:14px 16px;
            background:rgba(0,0,0,0.3);
            border:1px solid rgba(229,169,180,0.2);
            border-radius:10px;
            color:#fff;font-size:15px;font-family:'Outfit',sans-serif;
            outline:none;margin-bottom:20px;transition:border 0.2s;
        }
        input:focus{border-color:#d48a97;}
        .btn{
            width:100%;padding:15px;
            background:linear-gradient(135deg,#d48a97 0%,#c47683 100%);
            border:none;border-radius:10px;
            color:#fff;font-size:16px;font-weight:700;font-family:'Outfit',sans-serif;
            cursor:pointer;transition:all 0.3s;
            box-shadow:0 4px 15px rgba(212,138,151,0.35);
        }
        .btn:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(212,138,151,0.5);}
        .error{color:#ffb3a7;font-size:13px;margin-top:14px;display:none;}
        .portal-link{margin-top:24px;font-size:13px;color:#d9c5c7;}
        .portal-link a{color:#e5a9b4;text-decoration:none;font-weight:600;}
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo">KAYA KALP</div>
        <div class="subtitle">Admin Panel</div>
        <label for="admin-username">Username</label>
        <input type="text" id="admin-username" placeholder="Enter username" autocomplete="username">
        <label for="admin-password">Password</label>
        <input type="password" id="admin-password" placeholder="Enter password" autocomplete="current-password">
        <button class="btn" onclick="doLogin()">Login to Admin Panel</button>
        <div class="error" id="loginError">Invalid username or password. Please try again.</div>
        <div class="portal-link"><a href="/">&#8592; Back to Beautician Portal</a></div>
    </div>
    <script>
        document.getElementById('admin-password').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });
        async function doLogin() {
            const u = document.getElementById('admin-username').value.trim();
            const p = document.getElementById('admin-password').value;
            const res = await fetch('/admin/login', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({username:u, password:p})
            });
            const data = await res.json();
            if (data.success) {
                window.location.href = '/admin';
            } else {
                document.getElementById('loginError').style.display = 'block';
            }
        }
    </script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════
#  ADMIN DASHBOARD  (full SPA panel)
# ═══════════════════════════════════════════════════════════
ADMIN_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kaya Kalp – Admin Panel</title>
    <meta name="description" content="Kaya Kalp Admin Panel – manage beauticians, attendance, and service logs.">
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root{
            --primary:#d48a97;--accent:#e5a9b4;
            --bg:#12090b;--surface:#1c1114;
            --card:rgba(43,24,30,0.7);--border:rgba(229,169,180,0.15);
            --text:#fceef0;--sub:#d9c5c7;
            --green:#6bb393;--red:#e07070;
        }
        *{box-sizing:border-box;margin:0;padding:0}
        body{font-family:'Outfit',sans-serif;background:radial-gradient(circle at top,var(--surface) 0%,var(--bg) 100%);color:var(--text);min-height:100vh;}
        /* Layout */
        .topbar{
            display:flex;align-items:center;justify-content:space-between;
            padding:16px 32px;
            background:rgba(28,13,18,0.9);
            backdrop-filter:blur(20px);
            border-bottom:1px solid var(--border);
            position:sticky;top:0;z-index:100;
        }
        .topbar-logo{font-size:22px;font-weight:700;background:linear-gradient(135deg,#fff 0%,var(--accent) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        .topbar-right{display:flex;gap:12px;align-items:center;}
        .btn-sm{padding:8px 18px;border:none;border-radius:8px;font-family:'Outfit',sans-serif;font-weight:600;font-size:13px;cursor:pointer;transition:all 0.2s;}
        .btn-primary{background:var(--primary);color:#fff;box-shadow:0 3px 10px rgba(212,138,151,0.3);}
        .btn-primary:hover{background:#c47683;transform:translateY(-1px);}
        .btn-danger{background:var(--red);color:#fff;}
        .btn-danger:hover{background:#c55;}
        .btn-ghost{background:transparent;border:1px solid var(--border);color:var(--sub);}
        .btn-ghost:hover{color:#fff;border-color:#fff;}
        .btn-success{background:var(--green);color:#fff;}
        .main{padding:32px;max-width:1400px;margin:0 auto;}
        /* Stats row */
        .stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:32px;}
        .stat-box{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px 24px;backdrop-filter:blur(12px);}
        .stat-box-label{font-size:11px;color:var(--sub);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;font-weight:600;}
        .stat-box-value{font-size:28px;font-weight:700;color:#fff;}
        /* Tabs */
        .tabs{display:flex;gap:8px;margin-bottom:24px;border-bottom:1px solid var(--border);padding-bottom:0;}
        .tab-btn{padding:12px 24px;background:transparent;border:none;border-bottom:2px solid transparent;color:var(--sub);font-family:'Outfit',sans-serif;font-size:15px;font-weight:600;cursor:pointer;transition:all 0.2s;margin-bottom:-1px;}
        .tab-btn.active{color:var(--primary);border-bottom-color:var(--primary);}
        .tab-btn:hover{color:#fff;}
        .tab-panel{display:none;}
        .tab-panel.active{display:block;}
        /* Cards */
        .card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px;backdrop-filter:blur(12px);margin-bottom:20px;}
        .card-title{font-size:18px;font-weight:700;color:#fff;margin-bottom:20px;display:flex;align-items:center;gap:10px;}
        /* Forms */
        .form-row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;}
        .form-group{display:flex;flex-direction:column;gap:6px;flex:1;min-width:180px;}
        .form-group label{font-size:12px;color:var(--sub);font-weight:600;text-transform:uppercase;letter-spacing:0.5px;}
        .form-group input, .form-group select{
            padding:11px 14px;
            background:rgba(0,0,0,0.3);
            border:1px solid var(--border);
            border-radius:10px;
            color:#fff;font-size:14px;font-family:'Outfit',sans-serif;
            outline:none;transition:border 0.2s;
        }
        .form-group input:focus, .form-group select:focus{border-color:var(--primary);}
        .form-group input[type="file"]{padding:8px 14px;cursor:pointer;}
        /* Tables */
        .table-wrap{overflow-x:auto;border-radius:10px;}
        table{width:100%;border-collapse:collapse;white-space:nowrap;}
        th{padding:12px 16px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--sub);border-bottom:1px solid var(--border);text-align:left;}
        td{padding:12px 16px;font-size:14px;border-bottom:1px solid rgba(229,169,180,0.07);vertical-align:middle;}
        tr:last-child td{border-bottom:none;}
        tr:hover td{background:rgba(229,169,180,0.04);}
        .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;}
        .badge-green{background:rgba(107,179,147,0.2);color:#6bb393;border:1px solid rgba(107,179,147,0.3);}
        .badge-red{background:rgba(224,112,112,0.2);color:#e07070;border:1px solid rgba(224,112,112,0.3);}
        .badge-blue{background:rgba(100,149,237,0.2);color:#93b8f5;border:1px solid rgba(100,149,237,0.3);}
        /* Search */
        .search-bar{width:100%;max-width:360px;padding:10px 16px;background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:30px;color:#fff;font-size:14px;font-family:'Outfit',sans-serif;outline:none;margin-bottom:16px;}
        .search-bar:focus{border-color:var(--primary);}
        /* Toast */
        .toast-container{position:fixed;bottom:30px;right:30px;z-index:9999;display:flex;flex-direction:column;gap:10px;}
        .toast{background:#231217;border-left:4px solid var(--primary);padding:14px 20px;border-radius:10px;color:#fff;box-shadow:0 8px 24px rgba(0,0,0,0.5);font-weight:500;animation:slideRight 0.3s forwards;min-width:260px;font-size:14px;}
        .toast.success{border-left-color:var(--green);}
        .toast.error{border-left-color:var(--red);}
        @keyframes slideRight{from{transform:translateX(120%);opacity:0}to{transform:translateX(0);opacity:1}}
        /* Loading */
        .loading{text-align:center;padding:40px;color:var(--sub);font-size:14px;}
        .spinner{display:inline-block;width:28px;height:28px;border:3px solid rgba(229,169,180,0.2);border-top-color:var(--primary);border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:10px;}
        @keyframes spin{to{transform:rotate(360deg)}}
        .empty{text-align:center;padding:40px;color:var(--sub);font-size:14px;}
        @media(max-width:600px){.main{padding:16px;}.topbar{padding:12px 16px;}.form-row{flex-direction:column;}}
    </style>
</head>
<body>

<div class="topbar">
    <div class="topbar-logo">&#10024; Kaya Kalp Admin</div>
    <div class="topbar-right">
        <a href="/admin/download_db" style="text-decoration:none;">
            <button class="btn-sm btn-ghost">&#8659; Download DB</button>
        </a>
        <a href="/" target="_blank" style="text-decoration:none;">
            <button class="btn-sm btn-ghost">&#128279; View Portal</button>
        </a>
        <a href="/admin/logout" style="text-decoration:none;">
            <button class="btn-sm btn-danger">Logout</button>
        </a>
    </div>
</div>

<div class="main">
    <!-- Stats Row -->
    <div class="stats-row" id="statsRow">
        <div class="stat-box"><div class="stat-box-label">Total Beauticians</div><div class="stat-box-value" id="statBeauticians">–</div></div>
        <div class="stat-box"><div class="stat-box-label">Earnings Today</div><div class="stat-box-value" id="statToday">–</div></div>
        <div class="stat-box"><div class="stat-box-label">Services Logged</div><div class="stat-box-value" id="statServices">–</div></div>
        <div class="stat-box"><div class="stat-box-label">Attendance Records</div><div class="stat-box-value" id="statAttendance">–</div></div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('beauticians', this)">&#128100; Beauticians</button>
        <button class="tab-btn" onclick="switchTab('attendance', this)">&#128336; Attendance</button>
        <button class="tab-btn" onclick="switchTab('services', this)">&#10024; Services</button>
        <button class="tab-btn" onclick="switchTab('earnings', this)">&#128176; Earnings</button>
        <button class="tab-btn" onclick="switchTab('rates', this)">📋 Rate List</button>
        <button class="tab-btn" onclick="switchTab('settings', this)">&#9881; Settings</button>
    </div>

    <!-- Tab: Beauticians -->
    <div class="tab-panel active" id="tab-beauticians">
        <div class="card">
            <div class="card-title">&#10133; Add / Update Beautician</div>
            <div class="form-row">
                <div class="form-group">
                    <label>Beautician ID</label>
                    <input type="text" id="add-id" placeholder="e.g. B001">
                </div>
                <div class="form-group">
                    <label>Full Name</label>
                    <input type="text" id="add-name" placeholder="e.g. Priya Sharma">
                </div>
                <button class="btn-sm btn-primary" onclick="addBeautician()" style="height:42px;align-self:flex-end;">Save Beautician</button>
            </div>
        </div>

        <div class="card">
            <div class="card-title">&#128247; Upload Face Photo</div>
            <div class="form-row">
                <div class="form-group">
                    <label>Select Beautician</label>
                    <select id="photo-beautician-id"><option value="">– select –</option></select>
                </div>
                <div class="form-group">
                    <label>Photo File (.jpg / .png)</label>
                    <input type="file" id="photo-file" accept=".jpg,.jpeg,.png">
                </div>
                <button class="btn-sm btn-primary" onclick="uploadPhoto()" style="height:42px;align-self:flex-end;">Upload Photo</button>
            </div>
            <p style="font-size:12px;color:var(--sub);margin-top:12px;">&#128161; Clear, well-lit front-facing photo gives the best face recognition results.</p>
        </div>

        <div class="card">
            <div class="card-title">&#128100; Registered Beauticians</div>
            <input class="search-bar" placeholder="&#128269; Search by name or ID…" oninput="filterTable('beauticiansTable', this.value)">
            <div class="table-wrap">
                <table id="beauticiansTable">
                    <thead><tr>
                        <th>ID</th><th>Name</th><th>Photo</th>
                        <th>Services Today</th><th>Earnings Today</th>
                        <th>Services Month</th><th>Earnings Month</th>
                        <th>Action</th>
                    </tr></thead>
                    <tbody id="beauticiansBody"><tr><td colspan="8" class="loading"><div class="spinner"></div><br>Loading…</td></tr></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Tab: Attendance -->
    <div class="tab-panel" id="tab-attendance">
        <div class="card">
            <div class="card-title">&#128336; Attendance Log <span style="font-size:13px;font-weight:400;color:var(--sub);">(last 200 records)</span></div>
            <input class="search-bar" placeholder="&#128269; Search by name, date or ID…" oninput="filterTable('attendanceTable', this.value)">
            <div class="table-wrap">
                <table id="attendanceTable">
                    <thead><tr><th>#</th><th>Date</th><th>Beautician ID</th><th>Name</th><th>Check-in</th><th>Check-out</th><th>Status</th></tr></thead>
                    <tbody id="attendanceBody"><tr><td colspan="7" class="loading"><div class="spinner"></div><br>Loading…</td></tr></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Tab: Services -->
    <div class="tab-panel" id="tab-services">
        <div class="card">
            <div class="card-title">&#10024; Service Transactions <span style="font-size:13px;font-weight:400;color:var(--sub);">(last 200 records)</span></div>
            <input class="search-bar" placeholder="&#128269; Search by name, category or service…" oninput="filterTable('servicesTable', this.value)">
            <div class="table-wrap">
                <table id="servicesTable">
                    <thead><tr><th>#</th><th>Date</th><th>Time</th><th>Beautician</th><th>Category</th><th>Service</th><th>Rate (Rs.)</th></tr></thead>
                    <tbody id="servicesBody"><tr><td colspan="7" class="loading"><div class="spinner"></div><br>Loading…</td></tr></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Tab: Earnings -->
    <div class="tab-panel" id="tab-earnings">
        <div class="card">
            <div class="card-title">&#128176; Monthly Earnings Breakdown</div>
            <div id="earningsContent"><div class="loading"><div class="spinner"></div><br>Loading…</div></div>
        </div>
        <div class="card">
            <div class="card-title">&#128100; Per Beautician Stats</div>
            <div id="perBeauticianStats"><div class="loading"><div class="spinner"></div><br>Loading…</div></div>
        </div>
    </div>

    <!-- Tab: Rate List -->
    <div class="tab-panel" id="tab-rates">
        <div class="card">
            <div class="card-title">📋 Manage Rate List</div>
            <p style="font-size:13px;color:var(--sub);margin-bottom:20px;">
                View and amend the rate list categories, services, and prices. Click "Save Rate List Changes" to apply.
            </p>
            <div class="form-row" style="margin-bottom:20px; align-items:flex-end;">
                <div class="form-group" style="max-width:300px;">
                    <label>New Category Name</label>
                    <input type="text" id="new-category-name" placeholder="e.g. Nail Art">
                </div>
                <button class="btn-sm btn-success" onclick="addCategory()" style="height:42px;align-self:flex-end;">+ Add Category</button>
            </div>
            
            <div id="rate-list-editor">
                <!-- Dynamically filled by javascript -->
            </div>
            
            <div style="margin-top:20px;border-top:1px solid var(--border);padding-top:20px;display:flex;justify-content:flex-end;">
                <button class="btn-sm btn-primary" onclick="saveRateList()" style="font-size:15px;padding:12px 28px;">Save Rate List Changes</button>
            </div>
        </div>
    </div>

    <!-- Tab: Settings -->
    <div class="tab-panel" id="tab-settings">
        <div class="card">
            <div class="card-title">&#128274; Change Admin Credentials</div>
            <p style="font-size:13px;color:var(--sub);margin-bottom:20px;">Changes apply immediately for this session. For permanent change, set <code>ADMIN_USERNAME</code> and <code>ADMIN_PASSWORD</code> environment variables in Render dashboard.</p>
            <div class="form-row">
                <div class="form-group">
                    <label>New Username</label>
                    <input type="text" id="new-username" placeholder="Enter new username">
                </div>
                <div class="form-group">
                    <label>New Password</label>
                    <input type="password" id="new-password" placeholder="Enter new password">
                </div>
                <button class="btn-sm btn-primary" onclick="changeCredentials()" style="height:42px;align-self:flex-end;">Update Credentials</button>
            </div>
        </div>
        <div class="card">
            <div class="card-title">&#128190; Database Backup</div>
            <p style="font-size:13px;color:var(--sub);margin-bottom:16px;">Download a full backup of the SQLite database. Keep this file safe — it contains all beautician, attendance, and service data.</p>
            <a href="/admin/download_db" style="text-decoration:none;">
                <button class="btn-sm btn-primary">&#8659; Download beautyparlour.db</button>
            </a>
        </div>
        <div class="card" style="border-color:rgba(224,112,112,0.3); background:rgba(224,112,112,0.05);">
            <div class="card-title" style="color:var(--red);">&#9888; Reset / Erase Entire Database</div>
            <p style="font-size:13px;color:var(--sub);margin-bottom:16px;">
                WARNING: This will permanently delete all registered beauticians, attendance logs, and service records. This action cannot be undone.
            </p>
            <button class="btn-sm btn-danger" onclick="resetDatabase()">&#128465; Reset Database</button>
        </div>
    </div>
</div>

<div class="toast-container" id="toastContainer"></div>

<script>
    let allData = null;
    let localRateList = {};

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // ── Tabs ─────────────────────────────────────────────────
    function switchTab(name, btn) {
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById('tab-' + name).classList.add('active');
        btn.classList.add('active');
    }

    // ── Data Load ────────────────────────────────────────────
    async function loadData() {
        const res  = await fetch('/admin/get_data', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
        allData    = await res.json();
        if (!allData.success) { showToast('Failed to load data: ' + allData.error, 'error'); return; }

        // Stats row
        document.getElementById('statBeauticians').innerText = allData.beauticians.length;
        document.getElementById('statToday').innerText = 'Rs. ' + allData.overall.total_today;
        document.getElementById('statServices').innerText = allData.services.length;
        document.getElementById('statAttendance').innerText = allData.attendance.length;

        renderBeauticians(allData.beauticians);
        renderAttendance(allData.attendance);
        renderServices(allData.services);
        renderEarnings(allData.overall, allData.beauticians);
        populatePhotoSelect(allData.beauticians);
        
        localRateList = allData.rate_list || {};
        renderRateListEditor(localRateList);
    }

    // ── Beauticians ──────────────────────────────────────────
    function renderBeauticians(list) {
        const tbody = document.getElementById('beauticiansBody');
        if (!list.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty">No beauticians registered yet.</td></tr>'; return; }
        tbody.innerHTML = list.map(b => `
            <tr>
                <td><strong>${b.id}</strong></td>
                <td>${b.name}</td>
                <td><span class="badge ${b.has_photo ? 'badge-green' : 'badge-red'}">${b.has_photo ? '&#9989; Has Photo' : '&#10060; No Photo'}</span></td>
                <td>${b.stats.services_today}</td>
                <td>Rs. ${b.stats.money_today}</td>
                <td>${b.stats.services_month}</td>
                <td>Rs. ${b.stats.money_month}</td>
                <td><button class="btn-sm btn-danger" onclick="deleteBeautician('${b.id}', '${b.name}')">Delete</button></td>
            </tr>
        `).join('');
    }

    function populatePhotoSelect(list) {
        const sel = document.getElementById('photo-beautician-id');
        sel.innerHTML = '<option value="">– select –</option>' +
            list.map(b => `<option value="${b.id}">${b.name} (${b.id})</option>`).join('');
    }

    async function addBeautician() {
        const id   = document.getElementById('add-id').value.trim();
        const name = document.getElementById('add-name').value.trim();
        if (!id || !name) { showToast('ID and Name are required', 'error'); return; }
        const res  = await fetch('/admin/add_beautician', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, name})});
        const data = await res.json();
        if (data.success) {
            showToast(`Beautician "${name}" saved successfully!`, 'success');
            document.getElementById('add-id').value = '';
            document.getElementById('add-name').value = '';
            loadData();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    }

    async function deleteBeautician(id, name) {
        if (!confirm(`Are you sure you want to delete "${name}" (ID: ${id})?\nThis will also delete their attendance logs and service records. This cannot be undone.`)) return;
        const res  = await fetch('/admin/delete_beautician', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})});
        const data = await res.json();
        if (data.success) {
            showToast(`Beautician "${name}" deleted.`, 'success');
            loadData();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    }

    async function uploadPhoto() {
        const beauticianId = document.getElementById('photo-beautician-id').value;
        const fileInput    = document.getElementById('photo-file');
        if (!beauticianId) { showToast('Please select a beautician', 'error'); return; }
        if (!fileInput.files.length) { showToast('Please select a photo file', 'error'); return; }
        const file = fileInput.files[0];
        const reader = new FileReader();
        reader.onload = async function(e) {
            const base64 = e.target.result.split(',')[1];
            const res    = await fetch('/admin/upload_photo', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({beautician_id: beauticianId, photo_base64: base64, filename: file.name})
            });
            const data = await res.json();
            if (data.success) {
                showToast('Photo uploaded! Face recognition is updating…', 'success');
                fileInput.value = '';
                loadData();
            } else {
                showToast('Upload failed: ' + data.error, 'error');
            }
        };
        reader.readAsDataURL(file);
    }

    // ── Attendance ───────────────────────────────────────────
    function renderAttendance(list) {
        const tbody = document.getElementById('attendanceBody');
        if (!list.length) { tbody.innerHTML = '<tr><td colspan="7" class="empty">No attendance records yet.</td></tr>'; return; }
        tbody.innerHTML = list.map(r => {
            const isOut = r.checkout_time && r.checkout_time.trim();
            return `<tr>
                <td>${r.sno}</td>
                <td>${r.date || '–'}</td>
                <td><strong>${r.beautician_id}</strong></td>
                <td>${r.name}</td>
                <td>${r.checkin_time || '–'}</td>
                <td>${r.checkout_time || '–'}</td>
                <td><span class="badge ${isOut ? 'badge-blue' : 'badge-green'}">${isOut ? 'Checked Out' : 'Present'}</span></td>
            </tr>`;
        }).join('');
    }

    // ── Services ─────────────────────────────────────────────
    function renderServices(list) {
        const tbody = document.getElementById('servicesBody');
        if (!list.length) { tbody.innerHTML = '<tr><td colspan="7" class="empty">No service records yet.</td></tr>'; return; }
        tbody.innerHTML = list.map(r => `
            <tr>
                <td>${r.sno}</td>
                <td>${r.date}</td>
                <td>${r.time}</td>
                <td>${r.beautician_name} <span style="color:var(--sub);font-size:12px;">(${r.beautician_id})</span></td>
                <td><span class="badge badge-blue">${r.category}</span></td>
                <td>${r.service_name}</td>
                <td style="font-weight:700;color:#e5a9b4;">Rs. ${r.rate}</td>
            </tr>
        `).join('');
    }

    // ── Earnings ─────────────────────────────────────────────
    function renderEarnings(overall, beauticians) {
        const ec = document.getElementById('earningsContent');
        if (!overall.monthly_breakdown.length) {
            ec.innerHTML = '<div class="empty">No earnings records yet.</div>';
        } else {
            ec.innerHTML = overall.monthly_breakdown.map(item => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid var(--border);">
                    <span style="font-size:16px;font-weight:500;">${item.month_str}</span>
                    <span style="font-size:20px;font-weight:700;color:#e5a9b4;">Rs. ${item.amount.toLocaleString()}</span>
                </div>
            `).join('') + `<div style="padding-top:16px;font-size:13px;color:var(--sub);">Today's total: <strong style="color:#fff;">Rs. ${overall.total_today}</strong></div>`;
        }

        const pbs = document.getElementById('perBeauticianStats');
        pbs.innerHTML = beauticians.length ? `
            <div class="table-wrap">
            <table>
                <thead><tr><th>Name</th><th>ID</th><th>Today Earnings</th><th>Month Earnings</th><th>All-time Services</th></tr></thead>
                <tbody>${beauticians.map(b => `
                    <tr>
                        <td><strong>${b.name}</strong></td>
                        <td>${b.id}</td>
                        <td style="color:#e5a9b4;font-weight:600;">Rs. ${b.stats.money_today}</td>
                        <td style="color:#e5a9b4;font-weight:600;">Rs. ${b.stats.money_month}</td>
                        <td>${b.stats.services_total}</td>
                    </tr>
                `).join('')}</tbody>
            </table></div>
        ` : '<div class="empty">No beauticians registered.</div>';
    }

    // ── Rate List Editor ─────────────────────────────────────
    function renderRateListEditor(rateList) {
        const container = document.getElementById('rate-list-editor');
        container.innerHTML = '';
        const entries = Object.entries(rateList);
        if (!entries.length) {
            container.innerHTML = '<div class="empty">Rate list is empty. Add a category above.</div>';
            return;
        }
        for (const [category, services] of entries) {
            const catDiv = document.createElement('div');
            catDiv.className = 'card';
            catDiv.style.background = 'rgba(0,0,0,0.2)';
            catDiv.style.marginBottom = '20px';
            catDiv.style.border = '1px solid rgba(229,169,180,0.1)';
            
            let html = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
                    <h3 style="color:#fff; font-size:16px; font-weight:700;">${escapeHtml(category)}</h3>
                    <button class="btn-sm btn-danger" style="padding:6px 12px;" onclick="deleteCategory('${escapeHtml(category)}')">Delete Category</button>
                </div>
                <div class="table-wrap">
                <table style="width:100%;">
                    <thead>
                        <tr>
                            <th style="width:60%;">Service Name</th>
                            <th style="width:25%;">Rate (or 'Ask')</th>
                            <th style="width:15%;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="category-services-${escapeHtml(category)}">
            `;
            
            if (!services.length) {
                html += `<tr><td colspan="3" style="text-align:center;color:var(--sub);padding:16px;">No services in this category. Click "+ Add Service" below.</td></tr>`;
            } else {
                services.forEach((s, idx) => {
                    html += `
                        <tr data-category="${escapeHtml(category)}" data-index="${idx}">
                            <td>
                                <input type="text" class="service-name-input" value="${escapeHtml(s.name)}" style="width:100%; padding:8px 12px; background:rgba(0,0,0,0.3); border:1px solid var(--border); color:#fff; border-radius:8px; outline:none; font-family:inherit;">
                            </td>
                            <td>
                                <input type="text" class="service-rate-input" value="${s.rate}" style="width:100%; padding:8px 12px; background:rgba(0,0,0,0.3); border:1px solid var(--border); color:#fff; border-radius:8px; outline:none; font-family:inherit;">
                            </td>
                            <td>
                                <button class="btn-sm btn-danger" style="padding:6px 12px; font-size:11px;" onclick="deleteService('${escapeHtml(category)}', ${idx})">Remove</button>
                            </td>
                        </tr>
                    `;
                });
            }
            
            html += `
                    </tbody>
                </table>
                </div>
                <div style="margin-top:12px;">
                    <button class="btn-sm btn-ghost" style="padding:6px 12px;" onclick="addServiceRow('${escapeHtml(category)}')">+ Add Service</button>
                </div>
            `;
            catDiv.innerHTML = html;
            container.appendChild(catDiv);
        }
    }

    function syncLocalRateListFromUI() {
        const updated = {};
        const categories = Object.keys(localRateList);
        categories.forEach(cat => {
            updated[cat] = [];
            const tbody = document.getElementById(`category-services-${cat}`);
            if (tbody) {
                const rows = tbody.querySelectorAll('tr[data-category]');
                rows.forEach(row => {
                    const nameInput = row.querySelector('.service-name-input');
                    const rateInput = row.querySelector('.service-rate-input');
                    if (nameInput && rateInput) {
                        const name = nameInput.value.trim();
                        let rateVal = rateInput.value.trim();
                        if (rateVal.toLowerCase() === 'ask') {
                            rateVal = 'Ask';
                        } else {
                            const parsed = parseFloat(rateVal);
                            if (!isNaN(parsed)) {
                                rateVal = parsed;
                            }
                        }
                        if (name) {
                            updated[cat].push({name, rate: rateVal});
                        }
                    }
                });
            }
        });
        localRateList = updated;
    }

    function addCategory() {
        const input = document.getElementById('new-category-name');
        const catName = input.value.trim();
        if (!catName) {
            showToast('Category name cannot be empty', 'error');
            return;
        }
        if (localRateList[catName]) {
            showToast('Category already exists', 'error');
            return;
        }
        syncLocalRateListFromUI();
        localRateList[catName] = [];
        input.value = '';
        renderRateListEditor(localRateList);
        showToast(`Category "${catName}" added.`, 'success');
    }

    function deleteCategory(catName) {
        if (!confirm(`Are you sure you want to delete category "${catName}"? All its services will be removed.`)) return;
        syncLocalRateListFromUI();
        delete localRateList[catName];
        renderRateListEditor(localRateList);
    }

    function addServiceRow(catName) {
        syncLocalRateListFromUI();
        if (!localRateList[catName]) localRateList[catName] = [];
        localRateList[catName].push({name: 'New Service', rate: 0});
        renderRateListEditor(localRateList);
    }

    function deleteService(catName, idx) {
        syncLocalRateListFromUI();
        if (localRateList[catName]) {
            localRateList[catName].splice(idx, 1);
            renderRateListEditor(localRateList);
        }
    }

    async function saveRateList() {
        syncLocalRateListFromUI();
        try {
            const res = await fetch('/admin/update_rate_list', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({rate_list: localRateList})
            });
            const result = await res.json();
            if (result.success) {
                showToast('Rate list updated successfully!', 'success');
                loadData();
            } else {
                showToast('Failed to update rate list: ' + result.error, 'error');
            }
        } catch(e) {
            showToast('Error saving rate list: ' + e, 'error');
        }
    }

    async function resetDatabase() {
        const confirmText = prompt("WARNING: This will delete everything in the database.\nTo confirm, please type 'RESET DATABASE' below:");
        if (confirmText !== 'RESET DATABASE') {
            showToast('Database reset cancelled or invalid confirmation text.', 'error');
            return;
        }
        if (!confirm('FINAL WARNING: Are you absolutely sure? This will delete all beauticians, logs, attendance, and photos.')) return;
        
        try {
            const res = await fetch('/admin/reset_db', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({})
            });
            const result = await res.json();
            if (result.success) {
                showToast('Database reset successfully. Reloading...', 'success');
                setTimeout(() => { window.location.reload(); }, 1500);
            } else {
                showToast('Failed to reset database: ' + result.error, 'error');
            }
        } catch (e) {
            showToast('Error resetting database: ' + e, 'error');
        }
    }

    // ── Table filter ─────────────────────────────────────────
    function filterTable(tableId, query) {
        const q = query.toLowerCase();
        document.querySelectorAll(`#${tableId} tbody tr`).forEach(row => {
            row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
        });
    }

    // ── Settings ─────────────────────────────────────────────
    async function changeCredentials() {
        const u = document.getElementById('new-username').value.trim();
        const p = document.getElementById('new-password').value;
        if (!u || !p) { showToast('Username and password cannot be empty', 'error'); return; }
        const res  = await fetch('/admin/change_password', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u, password:p})});
        const data = await res.json();
        if (data.success) { showToast(data.message, 'success'); }
        else showToast('Error: ' + data.error, 'error');
    }

    // ── Toast ────────────────────────────────────────────────
    function showToast(msg, type='') {
        const c = document.getElementById('toastContainer');
        const t = document.createElement('div');
        t.className = 'toast ' + type;
        t.innerText = msg;
        c.appendChild(t);
        setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateX(120%)'; t.style.transition = 'all 0.3s'; setTimeout(() => t.remove(), 300); }, 4000);
    }

    // ── Init ─────────────────────────────────────────────────
    loadData();
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 50)
    print("  Kaya Kalp Beauty Parlour — Cloud Server")
    print("=" * 50)
    print(f"  Data folder : {DATA_FOLDER}")
    print(f"  Database    : {DB_FILE}")
    print(f"  Faces dir   : {KNOWN_FACES_DIR}")
    print()

    print("[1/3] Initialising database …")
    init_db()
    print("      ✓ Database ready")

    print("[2/3] Loading face encodings …")
    load_known_faces()
    print(f"      ✓ {len(known_ids)} face(s) loaded")

    port = int(os.environ.get("PORT", 8000))
    print(f"[3/3] Starting HTTP server on port {port} …")
    server = ThreadingHTTPServer(("", port), BeautyHandler)
    print(f"      ✓ Server running — open http://localhost:{port}")
    print(f"      ✓ Admin panel   — http://localhost:{port}/admin")
    print()
    print("  Press Ctrl+C to stop.")
    print("=" * 50)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
