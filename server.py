#!/usr/bin/env python3
"""FairwayConnect API + static server.

Zero-dependency backend: Python stdlib http.server + sqlite3.
Run:  python3 server.py          (serves on PORT env or 4173)
Data: fairway.db (created and seeded on first run)
"""

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "public")
DB_PATH = os.path.join(ROOT, "fairway.db")
PORT = int(os.environ.get("PORT", "4173"))

PALETTE = ["#0a6e3a", "#b8552f", "#3457a3", "#7b3aa3", "#1f8a8a",
           "#a33457", "#8a6d1f", "#555555", "#2f6f8a", "#6b8e23"]

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

# ---------------------------------------------------------------- database

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL, salt TEXT NOT NULL, color TEXT NOT NULL,
  headline TEXT DEFAULT '', location TEXT DEFAULT '', home_course TEXT DEFAULT '',
  postal_code TEXT DEFAULT '',
  handicap REAL DEFAULT 36, rounds INTEGER DEFAULT 0, best INTEGER,
  about TEXT DEFAULT '', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS endorsements (
  skill_id INTEGER NOT NULL REFERENCES skills(id), user_id INTEGER NOT NULL REFERENCES users(id),
  UNIQUE(skill_id, user_id)
);
CREATE TABLE IF NOT EXISTS experience (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  icon TEXT, title TEXT, org TEXT, period TEXT, descr TEXT
);
CREATE TABLE IF NOT EXISTS courses_played (
  user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  text TEXT NOT NULL, scorecard TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
  post_id INTEGER NOT NULL REFERENCES posts(id), user_id INTEGER NOT NULL REFERENCES users(id),
  UNIQUE(post_id, user_id)
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
  user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
  reporter_id INTEGER NOT NULL REFERENCES users(id), reason TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS blocks (
  blocker_id INTEGER NOT NULL REFERENCES users(id), blocked_id INTEGER NOT NULL REFERENCES users(id),
  UNIQUE(blocker_id, blocked_id)
);
CREATE TABLE IF NOT EXISTS connections (
  a INTEGER NOT NULL REFERENCES users(id), b INTEGER NOT NULL REFERENCES users(id),
  UNIQUE(a, b)
);
CREATE TABLE IF NOT EXISTS invites (
  from_id INTEGER NOT NULL REFERENCES users(id), to_id INTEGER NOT NULL REFERENCES users(id),
  UNIQUE(from_id, to_id)
);
CREATE TABLE IF NOT EXISTS teetimes (
  id INTEGER PRIMARY KEY, host_id INTEGER NOT NULL REFERENCES users(id),
  icon TEXT DEFAULT '⛳', title TEXT NOT NULL, course TEXT NOT NULL, when_text TEXT NOT NULL,
  postal_code TEXT DEFAULT '', descr TEXT DEFAULT '', spots INTEGER DEFAULT 1,
  tags TEXT DEFAULT '[]', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS teetime_requests (
  teetime_id INTEGER NOT NULL REFERENCES teetimes(id), user_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE(teetime_id, user_id)
);
CREATE TABLE IF NOT EXISTS calendar_entries (
  user_id INTEGER NOT NULL REFERENCES users(id),
  teetime_id INTEGER NOT NULL REFERENCES teetimes(id),
  created_at REAL NOT NULL,
  UNIQUE(user_id, teetime_id)
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, from_id INTEGER NOT NULL REFERENCES users(id),
  to_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL,
  created_at REAL NOT NULL, read INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  icon TEXT, text TEXT NOT NULL, link TEXT, created_at REAL NOT NULL, read INTEGER DEFAULT 0
);
"""


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def seed(conn):
    """Seed demo golfers so a fresh install isn't a ghost town. Demo password: golf1234."""
    now = time.time()
    H = 3600

    def add_user(name, email, headline, location, home, hcp, rounds, best, about,
                 skills, xp, courses, color):
        salt = secrets.token_hex(16)
        cur = conn.execute(
            "INSERT INTO users (name,email,pass_hash,salt,color,headline,location,home_course,"
            "handicap,rounds,best,about,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, email, hash_pw("golf1234", salt), salt, color, headline, location, home,
             hcp, rounds, best, about, now))
        uid = cur.lastrowid
        for s in skills:
            conn.execute("INSERT INTO skills (user_id,name) VALUES (?,?)", (uid, s))
        for icon, title, org, period, descr in xp:
            conn.execute("INSERT INTO experience (user_id,icon,title,org,period,descr) "
                         "VALUES (?,?,?,?,?,?)", (uid, icon, title, org, period, descr))
        for c in courses:
            conn.execute("INSERT INTO courses_played (user_id,name) VALUES (?,?)", (uid, c))
        return uid

    maria = add_user("Maria Santos", "maria@demo.fairwayconnect.app",
        "PGA Teaching Professional · Short Game Specialist", "Half Moon Bay, CA",
        "Half Moon Bay Golf Links", 0.8, 1240, 66,
        "Class A PGA professional. I help amateurs stop blading wedges. 500+ students taught.",
        ["Wedge Play", "Putting", "Teaching"],
        [("🎓", "Head Teaching Professional", "Half Moon Bay Golf Links", "2019 – Present",
          "Run the academy. Short game schools every month.")],
        ["Half Moon Bay", "Pebble Beach", "Cypress Point", "Olympic Club"], PALETTE[1])

    dev = add_user("Dev Patel", "dev@demo.fairwayconnect.app",
        "Scratch Golfer · +1.2 · Amateur circuit grinder", "Oakland, CA",
        "Metropolitan Golf Links", -1.2, 312, 63,
        "Mid-am competitor. Qualified for the US Mid-Am twice. Data nerd about strokes gained.",
        ["Ball Striking", "Strokes Gained Analysis", "Pressure Putting"],
        [("🏆", "Competitor", "NorCal Amateur Circuit", "2018 – Present",
          "Two-time club champion at Metro Links.")],
        ["Metropolitan", "Pasatiempo", "Spyglass Hill", "TPC Harding"], PALETTE[2])

    grace = add_user("Grace Kim", "grace@demo.fairwayconnect.app",
        "Golf Course Architect · Walked 400+ courses", "Portland, OR",
        "Bandon Trails", 8.9, 520, 74,
        "I design and restore golf courses. Ask me why your muni's 7th green is unfair.",
        ["Course Design", "Links Golf", "Walking 36 a Day"],
        [("📐", "Principal Architect", "Kim Golf Design", "2017 – Present",
          "Restorations and new builds across the Pacific Northwest.")],
        ["Bandon Dunes", "St. Andrews", "Royal Melbourne", "Sand Hills"], PALETTE[3])

    tommy = add_user("Tommy Okafor", "tommy@demo.fairwayconnect.app",
        "Caddie · Looper of the Year 2025 · Pebble Beach", "Monterey, CA",
        "Pebble Beach Golf Links", 4.1, 880, 69,
        "15 years on the bag at Pebble. I've read every break on these greens twice.",
        ["Green Reading", "Club Selection", "Keeping Players Calm"],
        [("🎒", "Senior Caddie", "Pebble Beach Golf Links", "2011 – Present",
          "Caddie Hall of Fame nominee. 2,000+ loops.")],
        ["Pebble Beach", "Spyglass Hill", "Spanish Bay", "Cypress Point"], PALETTE[4])

    hannah = add_user("Hannah Lindqvist", "hannah@demo.fairwayconnect.app",
        "Club Fitter & Equipment Geek · TrackMan certified", "San Jose, CA",
        "Cinnabar Hills GC", 6.7, 290, 71,
        "If your driver shaft is wrong, I will find out. 3,000+ fittings done.",
        ["Club Fitting", "Launch Monitor Data", "Swing Diagnostics"],
        [("🔧", "Master Fitter", "Pure Strike Golf Lab", "2020 – Present",
          "TrackMan & GC Quad certified. Tour-level fitting studio.")],
        ["Cinnabar Hills", "CordeValle", "Pasatiempo"], PALETTE[5])

    sam = add_user("Sam Whitfield", "sam@demo.fairwayconnect.app",
        "Golf Travel Writer · 61 countries, 1 swing thought", "Austin, TX",
        "Lions Municipal", 14.2, 410, 79,
        "I write about the world's great (and terrible) golf courses. Hot take machine.",
        ["Golf Writing", "Travel Logistics", "Hot Takes"],
        [("✍️", "Senior Writer", "The Fried Egg... roll", "2021 – Present",
          "Course reviews, travel guides, architecture deep dives.")],
        ["St. Andrews", "Ballybunion", "Cape Kidnappers", "Lions Municipal"], PALETTE[6])

    ray = add_user("Ray Donnelly", "ray@demo.fairwayconnect.app",
        "Superintendent · Keeper of the Greens · Turf science PhD", "Sacramento, CA",
        "Del Paso CC", 10.5, 150, 77,
        "I keep greens rolling at 11. Please fix your ball marks. PLEASE.",
        ["Agronomy", "Green Speed Management", "Ball Mark Forensics"],
        [("🌱", "Superintendent", "Del Paso Country Club", "2016 – Present",
          "Host site, 2024 NorCal Amateur.")],
        ["Del Paso", "Augusta National (work trip!)", "Pinehurst No. 2"], PALETTE[7])

    everyone = [maria, dev, grace, tommy, hannah, sam, ray]

    def add_post(uid, hours_ago, text, scorecard=None, liked_by=(), comments=()):
        cur = conn.execute(
            "INSERT INTO posts (user_id,text,scorecard,created_at) VALUES (?,?,?,?)",
            (uid, text, json.dumps(scorecard) if scorecard else None, now - hours_ago * H))
        pid = cur.lastrowid
        for lu in liked_by:
            conn.execute("INSERT INTO likes (post_id,user_id) VALUES (?,?)", (pid, lu))
        for cu, ctext, choff in comments:
            conn.execute("INSERT INTO comments (post_id,user_id,text,created_at) VALUES (?,?,?,?)",
                         (pid, cu, ctext, now - choff * H))

    add_post(dev, 2,
        "Card from yesterday's round at Pasatiempo. Drove it beautifully, putted like I was "
        "using a rake. Strokes gained putting: -3.1. Time to live on the practice green.",
        {"course": "Pasatiempo GC", "score": 68, "par": 70, "fairways": "11/14", "putts": 33},
        liked_by=[maria, tommy, grace, sam],
        comments=[(tommy, "A 68 and you're complaining?? Some of us carry bags for a living 😂", 1.5),
                  (maria, "Come see me. One hour on lag putting drills and that -3.1 disappears.", 1)])

    add_post(maria, 5,
        "PSA for every amateur I've ever taught: your 56° wedge is not a shovel. Soft hands, "
        "ball middle of stance, trust the bounce. That's the whole lesson. That'll be $150.",
        liked_by=[dev, grace, tommy, hannah, sam, ray],
        comments=[(sam, "Printing this out and taping it to my bag.", 4)])

    add_post(grace, 26,
        "Hot take from a course architect: your home course's 'hardest hole' is probably just a "
        "badly designed hole. Difficulty ≠ quality. A great hole gives the bogey golfer a path "
        "AND tempts the scratch player into a mistake.",
        liked_by=[dev, maria, sam, ray, hannah],
        comments=[(dev, "Metro's 14th in shambles reading this.", 20),
                  (ray, "Counterpoint: some of you just can't hit a 6 iron.", 18)])

    add_post(tommy, 30,
        "Looped 36 today at Pebble. Player on the morning bag made his first ever birdie on 7. "
        "The yell he let out scared the sea otters. This is why I do this job. 🌊⛳",
        liked_by=[maria, dev, grace, hannah, sam, ray])

    add_post(ray, 50,
        "We aerated the greens this week. Yes, I know. Yes, it's necessary. No, I will not "
        "apologize. Your putts will be pure in 3 weeks and you'll thank me. Sincerely, every "
        "superintendent on earth.",
        liked_by=[grace, tommy])

    add_post(hannah, 75,
        "Fitting stat of the week: golfer came in playing X-stiff shafts because his buddy said "
        "regular flex is 'for seniors.' Swing speed: 87 mph. We put him in regular. Instantly "
        "+18 yards and a draw. Ego is the most expensive thing in your bag.",
        liked_by=[maria, dev, sam, ray],
        comments=[(maria, "Preach. Ego costs more than any lesson.", 70)])

    # demo users know each other
    pairs = [(maria, tommy), (maria, dev), (dev, tommy), (grace, sam), (hannah, maria), (ray, grace)]
    for a, b in pairs:
        conn.execute("INSERT INTO connections (a,b) VALUES (?,?)", (min(a, b), max(a, b)))

    def add_teetime(host, icon, title, course, when_text, descr, spots, tags):
        conn.execute(
            "INSERT INTO teetimes (host_id,icon,title,course,when_text,descr,spots,tags,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (host, icon, title, course, when_text, descr, spots, json.dumps(tags), now))

    add_teetime(dev, "🌅", "Dawn Patrol Foursome — need 1", "Harding Park GC",
        "Sat Jun 13, 6:42 AM",
        "Walking, fast pace, mild trash talk. Handicaps 0–15 preferred. We putt everything out.",
        1, ["Walking", "Competitive"])
    add_teetime(maria, "🏖️", "Half Moon Bay twilight + range beers", "Half Moon Bay — Old Course",
        "Sun Jun 14, 3:30 PM",
        "Casual 9 (maybe 18 if the fog holds off). All skill levels. I will fix one swing flaw "
        "per player, free.", 2, ["Casual", "All levels"])
    add_teetime(grace, "⛰️", "Pasatiempo architecture walk & play", "Pasatiempo GC",
        "Fri Jun 19, 9:00 AM",
        "Play 18 while I point out every brilliant MacKenzie decision you've been three-putting "
        "over. Nerds welcome.", 3, ["Educational", "Walking"])

    conn.commit()


def init_db():
    fresh = not os.path.exists(DB_PATH)
    conn = db()
    conn.executescript(SCHEMA)
    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "postal_code" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN postal_code TEXT DEFAULT ''")
    teetime_columns = {r["name"] for r in conn.execute("PRAGMA table_info(teetimes)")}
    if "postal_code" not in teetime_columns:
        conn.execute("ALTER TABLE teetimes ADD COLUMN postal_code TEXT DEFAULT ''")
    # Upgrade databases created before hosts could accept or decline tee-time requests.
    request_columns = {r["name"] for r in conn.execute("PRAGMA table_info(teetime_requests)")}
    if "status" not in request_columns:
        conn.execute(
            "ALTER TABLE teetime_requests ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
    if fresh or conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        seed(conn)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- helpers

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def user_brief(row):
    return {"id": row["id"], "name": row["name"], "color": row["color"],
            "headline": row["headline"], "homeCourse": row["home_course"],
            "zipCode": row["postal_code"], "handicap": row["handicap"]}


COURSE_CACHE = {}


def haversine_miles(lat1, lon1, lat2, lon2):
    radius = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_json(url, data=None, timeout=12):
    req = Request(url, data=data, headers={
        "Accept": "application/json",
        "User-Agent": "FairwayConnectPilot/1.0",
    })
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        raise ApiError(502, "Course lookup is temporarily unavailable — try again shortly")


def lookup_golf_courses(postal_code, radius_miles=15):
    cache_key = (postal_code, radius_miles)
    cached = COURSE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 86400:
        return cached[1]

    place_data = fetch_json(f"https://api.zippopotam.us/us/{postal_code}")
    places = place_data.get("places") or []
    if not places:
        raise ApiError(404, "ZIP code not found")
    place = places[0]
    lat, lon = float(place["latitude"]), float(place["longitude"])
    radius_meters = round(radius_miles * 1609.344)
    query = (
        f'[out:json][timeout:20];('
        f'nwr["leisure"="golf_course"](around:{radius_meters},{lat},{lon});'
        f');out center tags;')
    osm = None
    for endpoint in (
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.nchc.org.tw/api/interpreter"):
        try:
            osm = fetch_json(endpoint, urlencode({"data": query}).encode(), timeout=25)
            break
        except ApiError:
            continue
    if osm is None:
        raise ApiError(502, "Course lookup is temporarily unavailable — try again shortly")
    courses = []
    seen = set()
    for element in osm.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        center = element.get("center") or element
        if not name or "lat" not in center or "lon" not in center:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        courses.append({
            "name": name,
            "distanceMiles": round(haversine_miles(lat, lon, center["lat"], center["lon"]), 1),
            "city": tags.get("addr:city", ""),
            "state": tags.get("addr:state", place.get("state abbreviation", "")),
        })
    courses.sort(key=lambda c: (c["distanceMiles"], c["name"]))
    result = {
        "zipCode": postal_code,
        "radiusMiles": radius_miles,
        "location": f'{place.get("place name", "")}, {place.get("state abbreviation", "")}'.strip(", "),
        "courses": courses[:30],
    }
    COURSE_CACHE[cache_key] = (time.time(), result)
    return result


def get_user(conn, uid):
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise ApiError(404, "Golfer not found")
    return row


def blocked_ids(conn, uid):
    """Users I blocked or who blocked me — invisible both ways."""
    rows = conn.execute(
        "SELECT blocked_id AS x FROM blocks WHERE blocker_id=? "
        "UNION SELECT blocker_id FROM blocks WHERE blocked_id=?", (uid, uid)).fetchall()
    return {r["x"] for r in rows}


def are_connected(conn, a, b):
    return conn.execute("SELECT 1 FROM connections WHERE a=? AND b=?",
                        (min(a, b), max(a, b))).fetchone() is not None


def notify(conn, uid, icon, text, link=None):
    conn.execute("INSERT INTO notifications (user_id,icon,text,link,created_at) VALUES (?,?,?,?,?)",
                 (uid, icon, text, link, time.time()))


def post_json(conn, uid, row, hidden):
    likes = conn.execute("SELECT COUNT(*) c FROM likes WHERE post_id=?", (row["id"],)).fetchone()["c"]
    liked = conn.execute("SELECT 1 FROM likes WHERE post_id=? AND user_id=?",
                         (row["id"], uid)).fetchone() is not None
    comments = []
    for c in conn.execute(
            "SELECT comments.id AS cid, comments.text, comments.created_at, comments.user_id, "
            "users.name, users.color, users.headline FROM comments "
            "JOIN users ON users.id = comments.user_id "
            "WHERE post_id=? ORDER BY comments.created_at", (row["id"],)):
        if c["user_id"] in hidden:
            continue
        comments.append({
            "id": c["cid"], "text": c["text"], "createdAt": c["created_at"],
            "author": {"id": c["user_id"], "name": c["name"], "color": c["color"],
                       "headline": c["headline"]}})
    return {
        "id": row["id"], "text": row["text"], "createdAt": row["created_at"],
        "scorecard": json.loads(row["scorecard"]) if row["scorecard"] else None,
        "author": {"id": row["user_id"], "name": row["name"], "color": row["color"],
                   "headline": row["headline"]},
        "likes": likes, "likedByMe": liked, "comments": comments,
        "mine": row["user_id"] == uid,
    }


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep stdout clean

    # ---- plumbing

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON body")

    def auth(self, conn):
        header = self.headers.get("Authorization") or ""
        token = header[7:] if header.startswith("Bearer ") else None
        if not token:
            raise ApiError(401, "Sign in required")
        row = conn.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
        if not row:
            raise ApiError(401, "Session expired — sign in again")
        return row["user_id"]

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def handle_api(self, method):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]  # ['api', ...]
        query = parse_qs(url.query)
        conn = db()
        try:
            result = self.route(conn, method, parts[1:], query)
            conn.commit()
            self.send_json(result if result is not None else {"ok": True})
        except ApiError as e:
            self.send_json({"error": e.message}, e.status)
        except Exception as e:  # don't leak stack traces
            self.send_json({"error": "Server error: %s" % e.__class__.__name__}, 500)
        finally:
            conn.close()

    # ---- routing

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.handle_api("GET")
        self.serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self.handle_api("POST")
        self.send_json({"error": "Not found"}, 404)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            return self.handle_api("DELETE")
        self.send_json({"error": "Not found"}, 404)

    def route(self, conn, method, p, query):
        # p is the path after /api/, e.g. ['posts', '3', 'like']
        if method == "POST" and p == ["signup"]:
            return self.r_signup(conn)
        if method == "POST" and p == ["login"]:
            return self.r_login(conn)
        if method == "POST" and p == ["logout"]:
            uid = self.auth(conn)
            token = self.headers.get("Authorization")[7:]
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            return {"ok": True}

        uid = self.auth(conn)

        if method == "GET":
            if p == ["me"]:
                return self.r_profile(conn, uid, uid)
            if p == ["badges"]:
                return self.r_badges(conn, uid)
            if p == ["feed"]:
                return self.r_feed(conn, uid)
            if p == ["users"]:
                return self.r_users(conn, uid, query)
            if len(p) == 2 and p[0] == "users":
                return self.r_profile(conn, uid, int(p[1]))
            if p == ["network"]:
                return self.r_network(conn, uid)
            if p == ["teetimes"]:
                return self.r_teetimes(conn, uid)
            if p == ["calendar"]:
                return self.r_calendar(conn, uid)
            if p == ["courses"]:
                return self.r_courses(query)
            if p == ["threads"]:
                return self.r_threads(conn, uid)
            if len(p) == 2 and p[0] == "threads":
                return self.r_thread(conn, uid, int(p[1]))
            if p == ["notifications"]:
                return self.r_notifications(conn, uid)

        if method == "POST":
            if p == ["posts"]:
                return self.r_create_post(conn, uid)
            if len(p) == 3 and p[0] == "posts":
                pid = int(p[1])
                if p[2] == "like":
                    return self.r_like(conn, uid, pid)
                if p[2] == "comments":
                    return self.r_comment(conn, uid, pid)
                if p[2] == "report":
                    return self.r_report(conn, uid, pid)
            if len(p) == 3 and p[0] == "users":
                other = int(p[1])
                if p[2] == "connect":
                    return self.r_connect(conn, uid, other)
                if p[2] == "decline":
                    conn.execute("DELETE FROM invites WHERE from_id=? AND to_id=?", (other, uid))
                    return {"ok": True}
                if p[2] == "endorse":
                    return self.r_endorse(conn, uid, other)
                if p[2] == "block":
                    return self.r_block(conn, uid, other)
            if p == ["teetimes"]:
                return self.r_create_teetime(conn, uid)
            if len(p) == 3 and p[0] == "teetimes" and p[2] == "join":
                return self.r_join_teetime(conn, uid, int(p[1]))
            if len(p) == 3 and p[0] == "teetimes" and p[2] == "calendar":
                return self.r_add_to_calendar(conn, uid, int(p[1]))
            if len(p) == 5 and p[0] == "teetimes" and p[2] == "requests":
                if p[4] not in ("accept", "decline"):
                    raise ApiError(404, "Unknown endpoint")
                return self.r_review_teetime_request(
                    conn, uid, int(p[1]), int(p[3]), p[4])
            if len(p) == 2 and p[0] == "threads":
                return self.r_send_message(conn, uid, int(p[1]))

        if method == "DELETE":
            if len(p) == 2 and p[0] == "posts":
                pid = int(p[1])
                row = conn.execute("SELECT user_id FROM posts WHERE id=?", (pid,)).fetchone()
                if not row:
                    raise ApiError(404, "Post not found")
                if row["user_id"] != uid:
                    raise ApiError(403, "You can only delete your own posts")
                for table in ("likes", "comments", "reports"):
                    conn.execute(f"DELETE FROM {table} WHERE post_id=?", (pid,))
                conn.execute("DELETE FROM posts WHERE id=?", (pid,))
                return {"ok": True}
            if len(p) == 3 and p[0] == "teetimes" and p[2] == "calendar":
                return self.r_remove_from_calendar(conn, uid, int(p[1]))

        raise ApiError(404, "Unknown endpoint")

    # ---- auth

    def r_signup(self, conn):
        b = self.read_body()
        name = (b.get("name") or "").strip()
        email = (b.get("email") or "").strip().lower()
        password = b.get("password") or ""
        postal_code = (b.get("zipCode") or "").strip()
        if not name or len(name) > 60:
            raise ApiError(400, "Please enter your name")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ApiError(400, "Please enter a valid email")
        if len(password) < 8:
            raise ApiError(400, "Password must be at least 8 characters")
        if postal_code and not re.match(r"^\d{5}$", postal_code):
            raise ApiError(400, "ZIP code must be 5 digits")
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise ApiError(409, "An account with that email already exists")
        salt = secrets.token_hex(16)
        color = PALETTE[sum(name.encode()) % len(PALETTE)]
        try:
            handicap = float(b.get("handicap")) if b.get("handicap") not in (None, "") else 36.0
        except (TypeError, ValueError):
            handicap = 36.0
        cur = conn.execute(
            "INSERT INTO users (name,email,pass_hash,salt,color,headline,home_course,postal_code,"
            "handicap,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, email, hash_pw(password, salt), salt, color,
             (b.get("headline") or "Golfer").strip()[:120],
             (b.get("homeCourse") or "").strip()[:80], postal_code, handicap, time.time()))
        uid = cur.lastrowid
        for s in ("Driving", "Putting", "Course Management"):
            conn.execute("INSERT INTO skills (user_id,name) VALUES (?,?)", (uid, s))
        return self.make_session(conn, uid)

    def r_login(self, conn):
        b = self.read_body()
        email = (b.get("email") or "").strip().lower()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or hash_pw(b.get("password") or "", row["salt"]) != row["pass_hash"]:
            raise ApiError(401, "Wrong email or password")
        return self.make_session(conn, row["id"])

    def make_session(self, conn, uid):
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (token,user_id,created_at) VALUES (?,?,?)",
                     (token, uid, time.time()))
        return {"token": token, "user": user_brief(get_user(conn, uid))}

    # ---- reads

    def r_badges(self, conn, uid):
        invites = conn.execute("SELECT COUNT(*) c FROM invites WHERE to_id=?", (uid,)).fetchone()["c"]
        unread_msgs = conn.execute(
            "SELECT COUNT(DISTINCT from_id) c FROM messages WHERE to_id=? AND read=0", (uid,)).fetchone()["c"]
        unread_notifs = conn.execute(
            "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND read=0", (uid,)).fetchone()["c"]
        me = get_user(conn, uid)
        return {"invites": invites, "messages": unread_msgs, "notifications": unread_notifs,
                "me": user_brief(me)}

    def r_feed(self, conn, uid):
        hidden = blocked_ids(conn, uid)
        rows = conn.execute(
            "SELECT posts.*, users.name, users.color, users.headline FROM posts "
            "JOIN users ON users.id = posts.user_id ORDER BY posts.created_at DESC LIMIT 100"
        ).fetchall()
        connections = conn.execute(
            "SELECT COUNT(*) c FROM connections WHERE a=? OR b=?", (uid, uid)).fetchone()["c"]
        me = get_user(conn, uid)
        return {
            "posts": [post_json(conn, uid, r, hidden) for r in rows if r["user_id"] not in hidden],
            "me": {**user_brief(me), "rounds": me["rounds"], "connections": connections},
            "suggestions": self.suggestions(conn, uid, hidden),
        }

    def suggestions(self, conn, uid, hidden, limit=3):
        rows = conn.execute(
            "SELECT * FROM users WHERE id != ? "
            "AND id NOT IN (SELECT b FROM connections WHERE a=?) "
            "AND id NOT IN (SELECT a FROM connections WHERE b=?) "
            "AND id NOT IN (SELECT to_id FROM invites WHERE from_id=?) "
            "AND id NOT IN (SELECT from_id FROM invites WHERE to_id=?) "
            "ORDER BY created_at LIMIT 20", (uid, uid, uid, uid, uid)).fetchall()
        return [user_brief(r) for r in rows if r["id"] not in hidden][:limit]

    def r_users(self, conn, uid, query):
        hidden = blocked_ids(conn, uid)
        q = (query.get("q") or [""])[0].strip().lower()
        rows = conn.execute("SELECT * FROM users WHERE id != ?", (uid,)).fetchall()
        out = []
        for r in rows:
            if r["id"] in hidden:
                continue
            if q and q not in r["name"].lower() and q not in r["headline"].lower() \
                    and q not in r["home_course"].lower():
                continue
            out.append(user_brief(r))
        return {"users": out[:20]}

    def r_profile(self, conn, uid, target):
        hidden = blocked_ids(conn, uid)
        if target != uid and target in hidden:
            raise ApiError(404, "Golfer not found")
        u = get_user(conn, target)
        skills = []
        for s in conn.execute("SELECT * FROM skills WHERE user_id=?", (target,)):
            count = conn.execute("SELECT COUNT(*) c FROM endorsements WHERE skill_id=?",
                                 (s["id"],)).fetchone()["c"]
            mine = conn.execute("SELECT 1 FROM endorsements WHERE skill_id=? AND user_id=?",
                                (s["id"], uid)).fetchone() is not None
            skills.append({"id": s["id"], "name": s["name"], "endorsements": count,
                           "endorsedByMe": mine})
        xp = [{"icon": x["icon"], "title": x["title"], "org": x["org"], "period": x["period"],
               "desc": x["descr"]}
              for x in conn.execute("SELECT * FROM experience WHERE user_id=?", (target,))]
        courses = [c["name"] for c in
                   conn.execute("SELECT name FROM courses_played WHERE user_id=?", (target,))]
        if are_connected(conn, uid, target):
            status = "connected"
        elif conn.execute("SELECT 1 FROM invites WHERE from_id=? AND to_id=?",
                          (uid, target)).fetchone():
            status = "pending"
        elif conn.execute("SELECT 1 FROM invites WHERE from_id=? AND to_id=?",
                          (target, uid)).fetchone():
            status = "invited-me"
        else:
            status = "none"
        connections = conn.execute(
            "SELECT COUNT(*) c FROM connections WHERE a=? OR b=?", (target, target)).fetchone()["c"]
        return {
            **user_brief(u),
            "location": u["location"], "about": u["about"], "rounds": u["rounds"],
            "best": u["best"], "skills": skills, "experience": xp, "courses": courses,
            "status": "self" if target == uid else status, "connections": connections,
        }

    def r_network(self, conn, uid):
        hidden = blocked_ids(conn, uid)
        conn_ids = [r["x"] for r in conn.execute(
            "SELECT b AS x FROM connections WHERE a=? UNION SELECT a FROM connections WHERE b=?",
            (uid, uid))]
        invites = [r["from_id"] for r in
                   conn.execute("SELECT from_id FROM invites WHERE to_id=?", (uid,))]
        sent = [r["to_id"] for r in
                conn.execute("SELECT to_id FROM invites WHERE from_id=?", (uid,))]
        others = conn.execute("SELECT * FROM users WHERE id != ?", (uid,)).fetchall()

        def briefs(ids):
            return [user_brief(get_user(conn, i)) for i in ids if i not in hidden]

        return {
            "connections": briefs(conn_ids),
            "invites": briefs(invites),
            "suggestions": [
                {**user_brief(r), "pending": r["id"] in sent}
                for r in others
                if r["id"] not in hidden and r["id"] not in conn_ids and r["id"] not in invites],
        }

    def r_teetimes(self, conn, uid):
        hidden = blocked_ids(conn, uid)
        out = []
        for t in conn.execute(
                "SELECT teetimes.*, users.name AS host_name FROM teetimes "
                "JOIN users ON users.id = teetimes.host_id ORDER BY teetimes.created_at DESC"):
            if t["host_id"] in hidden:
                continue
            taken = conn.execute(
                "SELECT COUNT(*) c FROM teetime_requests WHERE teetime_id=? AND status='accepted'",
                (t["id"],)).fetchone()["c"]
            request = conn.execute(
                "SELECT status FROM teetime_requests WHERE teetime_id=? AND user_id=?",
                (t["id"], uid)).fetchone()
            calendar_added = conn.execute(
                "SELECT 1 FROM calendar_entries WHERE user_id=? AND teetime_id=?",
                (uid, t["id"])).fetchone() is not None
            requests = []
            if t["host_id"] == uid:
                for r in conn.execute(
                        "SELECT tr.status, users.id, users.name, users.color, users.headline, "
                        "users.home_course, users.postal_code, users.handicap "
                        "FROM teetime_requests tr "
                        "JOIN users ON users.id=tr.user_id "
                        "WHERE tr.teetime_id=? AND tr.status IN ('pending','accepted') "
                        "ORDER BY CASE tr.status WHEN 'pending' THEN 0 ELSE 1 END, users.name",
                        (t["id"],)):
                    requests.append({**user_brief(r), "status": r["status"]})
            out.append({
                "id": t["id"], "icon": t["icon"], "title": t["title"], "course": t["course"],
                "when": t["when_text"], "postalCode": t["postal_code"],
                "desc": t["descr"], "tags": json.loads(t["tags"]),
                "spotsLeft": max(0, t["spots"] - taken),
                "host": {"id": t["host_id"], "name": t["host_name"]},
                "mine": t["host_id"] == uid,
                "requestStatus": request["status"] if request else None,
                "calendarAdded": calendar_added,
                "requests": requests,
            })
        return {"teetimes": out, "myZip": get_user(conn, uid)["postal_code"]}

    def r_calendar(self, conn, uid):
        rows = conn.execute(
            "SELECT t.*, u.name AS host_name FROM calendar_entries ce "
            "JOIN teetimes t ON t.id=ce.teetime_id "
            "JOIN users u ON u.id=t.host_id "
            "WHERE ce.user_id=? ORDER BY t.when_text, t.created_at", (uid,)).fetchall()
        return {"events": [{
            "id": t["id"], "icon": t["icon"], "title": t["title"],
            "course": t["course"], "when": t["when_text"],
            "postalCode": t["postal_code"], "hostName": t["host_name"],
            "mine": t["host_id"] == uid,
        } for t in rows]}

    def r_courses(self, query):
        postal_code = (query.get("zip") or [""])[0].strip()
        if not re.match(r"^\d{5}$", postal_code):
            raise ApiError(400, "Enter a valid 5-digit ZIP code")
        try:
            radius = int((query.get("radius") or ["15"])[0])
        except ValueError:
            raise ApiError(400, "Choose a valid search distance")
        if radius not in (5, 10, 15, 20, 25, 30, 40, 50):
            raise ApiError(400, "Choose a search distance from 5 to 50 miles")
        return lookup_golf_courses(postal_code, radius)

    def r_threads(self, conn, uid):
        hidden = blocked_ids(conn, uid)
        partners = [r["x"] for r in conn.execute(
            "SELECT to_id AS x FROM messages WHERE from_id=? "
            "UNION SELECT from_id FROM messages WHERE to_id=?", (uid, uid))]
        threads = []
        for p in partners:
            if p in hidden:
                continue
            last = conn.execute(
                "SELECT * FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) "
                "ORDER BY created_at DESC LIMIT 1", (uid, p, p, uid)).fetchone()
            unread = conn.execute(
                "SELECT COUNT(*) c FROM messages WHERE from_id=? AND to_id=? AND read=0",
                (p, uid)).fetchone()["c"]
            threads.append({"with": user_brief(get_user(conn, p)),
                            "last": last["text"], "lastAt": last["created_at"],
                            "unread": unread > 0})
        threads.sort(key=lambda t: -t["lastAt"])
        return {"threads": threads}

    def r_thread(self, conn, uid, other):
        if other in blocked_ids(conn, uid):
            raise ApiError(404, "Golfer not found")
        conn.execute("UPDATE messages SET read=1 WHERE from_id=? AND to_id=?", (other, uid))
        msgs = conn.execute(
            "SELECT * FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) "
            "ORDER BY created_at", (uid, other, other, uid)).fetchall()
        return {"with": user_brief(get_user(conn, other)),
                "messages": [{"from": m["from_id"], "text": m["text"],
                              "createdAt": m["created_at"]} for m in msgs]}

    def r_notifications(self, conn, uid):
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
            (uid,)).fetchall()
        conn.execute("UPDATE notifications SET read=1 WHERE user_id=?", (uid,))
        return {"notifications": [
            {"icon": r["icon"], "text": r["text"], "link": r["link"],
             "createdAt": r["created_at"], "unread": not r["read"]} for r in rows]}

    # ---- writes

    def r_create_post(self, conn, uid):
        b = self.read_body()
        text = (b.get("text") or "").strip()
        if not text:
            raise ApiError(400, "Write something first — even a bogey story counts")
        if len(text) > 3000:
            raise ApiError(400, "Post is too long")
        scorecard = b.get("scorecard")
        if scorecard is not None:
            if not isinstance(scorecard, dict):
                raise ApiError(400, "Bad scorecard")
            scorecard = {k: str(scorecard.get(k, ""))[:40]
                         for k in ("course", "score", "par", "fairways", "putts")}
        conn.execute("INSERT INTO posts (user_id,text,scorecard,created_at) VALUES (?,?,?,?)",
                     (uid, text, json.dumps(scorecard) if scorecard else None, time.time()))
        return {"ok": True}

    def r_like(self, conn, uid, pid):
        if not conn.execute("SELECT 1 FROM posts WHERE id=?", (pid,)).fetchone():
            raise ApiError(404, "Post not found")
        if conn.execute("SELECT 1 FROM likes WHERE post_id=? AND user_id=?",
                        (pid, uid)).fetchone():
            conn.execute("DELETE FROM likes WHERE post_id=? AND user_id=?", (pid, uid))
        else:
            conn.execute("INSERT INTO likes (post_id,user_id) VALUES (?,?)", (pid, uid))
        likes = conn.execute("SELECT COUNT(*) c FROM likes WHERE post_id=?", (pid,)).fetchone()["c"]
        liked = conn.execute("SELECT 1 FROM likes WHERE post_id=? AND user_id=?",
                             (pid, uid)).fetchone() is not None
        return {"likes": likes, "likedByMe": liked}

    def r_comment(self, conn, uid, pid):
        b = self.read_body()
        text = (b.get("text") or "").strip()
        if not text or len(text) > 1000:
            raise ApiError(400, "Comment can't be empty")
        post = conn.execute("SELECT user_id FROM posts WHERE id=?", (pid,)).fetchone()
        if not post:
            raise ApiError(404, "Post not found")
        conn.execute("INSERT INTO comments (post_id,user_id,text,created_at) VALUES (?,?,?,?)",
                     (pid, uid, text, time.time()))
        if post["user_id"] != uid:
            me = get_user(conn, uid)
            notify(conn, post["user_id"], "💬",
                   f"{me['name']} commented on your post.", "#/feed")
        return {"ok": True}

    def r_report(self, conn, uid, pid):
        b = self.read_body()
        if not conn.execute("SELECT 1 FROM posts WHERE id=?", (pid,)).fetchone():
            raise ApiError(404, "Post not found")
        conn.execute("INSERT INTO reports (post_id,reporter_id,reason,created_at) VALUES (?,?,?,?)",
                     (pid, uid, (b.get("reason") or "")[:500], time.time()))
        return {"ok": True}

    def r_connect(self, conn, uid, other):
        if other == uid:
            raise ApiError(400, "You can't pair up with yourself")
        get_user(conn, other)
        if other in blocked_ids(conn, uid):
            raise ApiError(404, "Golfer not found")
        if are_connected(conn, uid, other):
            return {"status": "connected"}
        me = get_user(conn, uid)
        if conn.execute("SELECT 1 FROM invites WHERE from_id=? AND to_id=?",
                        (other, uid)).fetchone():
            # they already invited me -> accept
            conn.execute("DELETE FROM invites WHERE from_id=? AND to_id=?", (other, uid))
            conn.execute("INSERT INTO connections (a,b) VALUES (?,?)",
                         (min(uid, other), max(uid, other)))
            notify(conn, other, "🤝",
                   f"{me['name']} accepted your foursome invitation.", f"#/profile/{uid}")
            return {"status": "connected"}
        conn.execute("INSERT OR IGNORE INTO invites (from_id,to_id) VALUES (?,?)", (uid, other))
        notify(conn, other, "🤝",
               f"{me['name']} sent you a foursome invitation.", "#/network")
        return {"status": "pending"}

    def r_endorse(self, conn, uid, other):
        b = self.read_body()
        skill = conn.execute("SELECT * FROM skills WHERE id=? AND user_id=?",
                             (b.get("skillId"), other)).fetchone()
        if not skill:
            raise ApiError(404, "Skill not found")
        if other == uid:
            raise ApiError(400, "Endorsing yourself? Bold. No.")
        conn.execute("INSERT OR IGNORE INTO endorsements (skill_id,user_id) VALUES (?,?)",
                     (skill["id"], uid))
        me = get_user(conn, uid)
        notify(conn, other, "🏌️",
               f"{me['name']} endorsed you for {skill['name']}.", f"#/profile/{other}")
        return {"ok": True}

    def r_block(self, conn, uid, other):
        if other == uid:
            raise ApiError(400, "You can't block yourself")
        get_user(conn, other)
        conn.execute("INSERT OR IGNORE INTO blocks (blocker_id,blocked_id) VALUES (?,?)",
                     (uid, other))
        conn.execute("DELETE FROM invites WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)",
                     (uid, other, other, uid))
        conn.execute("DELETE FROM connections WHERE a=? AND b=?",
                     (min(uid, other), max(uid, other)))
        return {"ok": True}

    def r_create_teetime(self, conn, uid):
        b = self.read_body()
        title = (b.get("title") or "").strip()
        course = (b.get("course") or "").strip()
        when = (b.get("when") or "").strip()
        postal_code = (b.get("zipCode") or "").strip()
        if not title or not course or not when or not re.match(r"^\d{5}$", postal_code):
            raise ApiError(400, "Title, ZIP code, course, and date/time are required")
        try:
            spots = max(1, min(3, int(b.get("spots") or 1)))
        except (TypeError, ValueError):
            spots = 1
        tags = [str(t)[:20] for t in (b.get("tags") or [])][:4]
        cur = conn.execute(
            "INSERT INTO teetimes (host_id,icon,title,course,when_text,postal_code,descr,spots,tags,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, (b.get("icon") or "⛳")[:4], title[:80], course[:80], when[:60], postal_code,
             (b.get("desc") or "").strip()[:500], spots, json.dumps(tags), time.time()))
        conn.execute(
            "INSERT INTO calendar_entries (user_id,teetime_id,created_at) VALUES (?,?,?)",
            (uid, cur.lastrowid, time.time()))
        return {"ok": True, "teetimeId": cur.lastrowid}

    def r_join_teetime(self, conn, uid, tid):
        t = conn.execute("SELECT * FROM teetimes WHERE id=?", (tid,)).fetchone()
        if not t:
            raise ApiError(404, "Tee time not found")
        if t["host_id"] == uid:
            raise ApiError(400, "That's your own listing")
        existing = conn.execute(
            "SELECT status FROM teetime_requests WHERE teetime_id=? AND user_id=?",
            (tid, uid)).fetchone()
        if existing and existing["status"] == "accepted":
            raise ApiError(409, "Your spot is already confirmed")
        if existing and existing["status"] == "pending":
            return {"status": "pending"}
        taken = conn.execute(
            "SELECT COUNT(*) c FROM teetime_requests WHERE teetime_id=? AND status='accepted'",
            (tid,)).fetchone()["c"]
        if taken >= t["spots"]:
            raise ApiError(409, "This tee time is full")
        conn.execute(
            "INSERT INTO teetime_requests (teetime_id,user_id,status) VALUES (?,?,'pending') "
            "ON CONFLICT(teetime_id,user_id) DO UPDATE SET status='pending'",
            (tid, uid))
        me = get_user(conn, uid)
        notify(conn, t["host_id"], "📋",
               f"{me['name']} requested a spot in \"{t['title']}\".", "#/teetimes")
        return {"ok": True}

    def r_review_teetime_request(self, conn, uid, tid, requester, action):
        t = conn.execute("SELECT * FROM teetimes WHERE id=?", (tid,)).fetchone()
        if not t:
            raise ApiError(404, "Tee time not found")
        if t["host_id"] != uid:
            raise ApiError(403, "Only the host can review requests")
        req = conn.execute(
            "SELECT status FROM teetime_requests WHERE teetime_id=? AND user_id=?",
            (tid, requester)).fetchone()
        if not req or req["status"] != "pending":
            raise ApiError(404, "Pending request not found")
        golfer = get_user(conn, requester)
        if action == "accept":
            taken = conn.execute(
                "SELECT COUNT(*) c FROM teetime_requests "
                "WHERE teetime_id=? AND status='accepted'", (tid,)).fetchone()["c"]
            if taken >= t["spots"]:
                raise ApiError(409, "This tee time is already full")
            conn.execute(
                "UPDATE teetime_requests SET status='accepted' "
                "WHERE teetime_id=? AND user_id=?", (tid, requester))
            notify(conn, requester, "✅",
                   f"Your spot in \"{t['title']}\" was confirmed.", "#/teetimes")
            return {"status": "accepted", "golfer": golfer["name"]}
        conn.execute(
            "UPDATE teetime_requests SET status='declined' "
            "WHERE teetime_id=? AND user_id=?", (tid, requester))
        notify(conn, requester, "📋",
               f"Your request for \"{t['title']}\" was declined.", "#/teetimes")
        return {"status": "declined", "golfer": golfer["name"]}

    def r_add_to_calendar(self, conn, uid, tid):
        t = conn.execute("SELECT * FROM teetimes WHERE id=?", (tid,)).fetchone()
        if not t:
            raise ApiError(404, "Tee time not found")
        accepted = conn.execute(
            "SELECT 1 FROM teetime_requests WHERE teetime_id=? AND user_id=? AND status='accepted'",
            (tid, uid)).fetchone()
        if t["host_id"] != uid and not accepted:
            raise ApiError(403, "Only confirmed golfers can add this tee time")
        conn.execute(
            "INSERT OR IGNORE INTO calendar_entries (user_id,teetime_id,created_at) VALUES (?,?,?)",
            (uid, tid, time.time()))
        return {"ok": True, "status": "added"}

    def r_remove_from_calendar(self, conn, uid, tid):
        conn.execute(
            "DELETE FROM calendar_entries WHERE user_id=? AND teetime_id=?", (uid, tid))
        return {"ok": True, "status": "removed"}

    def r_send_message(self, conn, uid, other):
        b = self.read_body()
        text = (b.get("text") or "").strip()
        if not text or len(text) > 2000:
            raise ApiError(400, "Message can't be empty")
        get_user(conn, other)
        if other in blocked_ids(conn, uid):
            raise ApiError(404, "Golfer not found")
        conn.execute("INSERT INTO messages (from_id,to_id,text,created_at) VALUES (?,?,?,?)",
                     (uid, other, text, time.time()))
        return {"ok": True}

    # ---- static files

    def serve_static(self):
        path = urlparse(self.path).path
        if path == "/":
            path = "/index.html"
        full = os.path.realpath(os.path.join(PUBLIC, path.lstrip("/")))
        if os.path.isdir(full) and full.startswith(PUBLIC):
            if not path.endswith("/"):  # /dallas -> /dallas/ so relative URLs resolve
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            full = os.path.join(full, "index.html")
        if not full.startswith(PUBLIC) or not os.path.isfile(full):
            full = os.path.join(PUBLIC, "index.html")  # SPA fallback
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"FairwayConnect running on http://localhost:{PORT}")
    server.serve_forever()
