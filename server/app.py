#!/usr/bin/env python3
"""Club Escapade accounts, comments and ratings server.

Standard library only (Python 3.9+), so it runs on a 32-bit Raspberry Pi 2
with nothing to install beyond python3. Data lives in one SQLite file.

In production Caddy serves the site's files and HTTPS, and passes /api/*
to this server on 127.0.0.1:8080. See server/README.md.

    python3 server/app.py serve --dev      # local testing: site + API on :8080
    python3 server/app.py add-user NAME    # create an account, prints its PIN
    python3 server/app.py make-admin NAME  # let NAME delete any comment
    python3 server/app.py ban NAME         # block NAME and hide their posts
    python3 server/app.py allow-hidden NAME  # let NAME see games/hidden/
    python3 server/app.py --help           # everything else
"""

import argparse
import getpass
import hashlib
import hmac
import http.cookies
import http.server
import json
import os
import posixpath
import re
import secrets
import sqlite3
import sys
import threading
import time
import unicodedata
from urllib.parse import quote, unquote, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "data", "club.db")

COOKIE = "ce_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_BODY = 4096
MAX_COMMENT = 1000
# Flash game saves (see saves.js). A typical save is a few KB.
MAX_SAVES_BODY = 2 * 1024 * 1024        # one upload
MAX_SAVE_KEY = 300                      # one save's name
MAX_SAVE_VALUE = 512 * 1024             # one save
MAX_SAVES_TOTAL = 10 * 1024 * 1024      # everything one user has saved
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{3,20}")
PIN_LENGTH = 6  # log-ins use a 6-digit PIN; keep in step with PIN_LENGTH in pinpad.js
PIN_RE = re.compile(r"[0-9]{%d}" % PIN_LENGTH)
# Wrong-PIN limits, per 15 minutes. A short PIN is only safe because guesses
# are slow: 5 per account means years to try all 6-digit PINs. The per-address
# limit is high because a whole school usually shares one public IP.
PIN_FAILS_PER_USER = 5
PIN_FAILS_PER_IP = 100
GAME_ID = r"([a-z0-9-]{1,64})"

# scrypt cost. n=2**14 takes roughly half a second per login on a Pi 2 and
# about 16 MB of memory. Raise n on faster hardware; old hashes keep working.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

CONFIG = {"db": DEFAULT_DB, "dev": False}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id        INTEGER PRIMARY KEY,
    username  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password  TEXT NOT NULL,
    created   INTEGER NOT NULL,
    is_admin  INTEGER NOT NULL DEFAULT 0,
    banned    INTEGER NOT NULL DEFAULT 0,
    timeout_until INTEGER NOT NULL DEFAULT 0, -- can't use the site until then
    screen_name TEXT,                          -- what others see; NULL: the username
    proper_name TEXT NOT NULL DEFAULT '',      -- legal/formal name; admins only
    invite_code TEXT,                          -- set until the student joins
    hidden_games INTEGER NOT NULL DEFAULT 0,   -- may see games/hidden/
    grade_level INTEGER NOT NULL DEFAULT 1     -- 1-5; mature games need at least theirs
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id       INTEGER PRIMARY KEY,
    game     TEXT NOT NULL,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body     TEXT NOT NULL,
    created  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_by_game ON comments(game, id);
CREATE TABLE IF NOT EXISTS ratings (
    game     TEXT NOT NULL,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stars    INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    updated  INTEGER NOT NULL,
    PRIMARY KEY (game, user_id)
);
CREATE TABLE IF NOT EXISTS saves (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    updated  INTEGER NOT NULL,
    PRIMARY KEY (user_id, key)
);
-- Games each person has unlocked by pressing Play (see play.html).
CREATE TABLE IF NOT EXISTS unlocks (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game     TEXT NOT NULL,
    created  INTEGER NOT NULL,
    PRIMARY KEY (user_id, game)
);
-- Per-game settings from the admin page (Game settings). mature: NULL uses
-- the game list's own `mature:` value, 0 = not mature, 1-5 = that grade and
-- up. disabled: no standard account can see or play it.
CREATE TABLE IF NOT EXISTS game_settings (
    game     TEXT PRIMARY KEY,
    mature   INTEGER,
    disabled INTEGER NOT NULL DEFAULT 0
);
-- What admins did on the admin page (Admin log), newest last.
CREATE TABLE IF NOT EXISTS admin_log (
    id       INTEGER PRIMARY KEY,
    created  INTEGER NOT NULL,
    admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    admin    TEXT NOT NULL,   -- their name then, kept if the account goes
    action   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created    INTEGER NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);
"""


# ---------------------------------------------------------------- database

def connect():
    con = sqlite3.connect(CONFIG["db"], timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    folder = os.path.dirname(os.path.abspath(CONFIG["db"]))
    os.makedirs(folder, exist_ok=True)
    con = connect()
    con.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    con.executescript(SCHEMA)
    # Databases made before timeouts existed: add the column.
    columns = [r["name"] for r in con.execute("PRAGMA table_info(users)")]
    if "timeout_until" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN timeout_until INTEGER NOT NULL DEFAULT 0")
    if "screen_name" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN screen_name TEXT")
    if "invite_code" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN invite_code TEXT")
    if "proper_name" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN proper_name TEXT NOT NULL DEFAULT ''")
    if "hidden_games" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN hidden_games INTEGER NOT NULL DEFAULT 0")
    if "grade_level" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN grade_level INTEGER NOT NULL DEFAULT 1")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_by_invite ON users(invite_code)")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_by_screen_name "
                "ON users(screen_name COLLATE NOCASE)")
    con.commit()
    con.close()


# ---------------------------------------------------------------- invites
# An admin makes an account with a username (what the student logs in with)
# and gets an invite code. The student enters the code on join.html and picks
# a screen name (what everyone else sees) and their own PIN. Until then the
# account has no PIN, so nobody can log in to it.

INVITE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L


def new_invite_code(con):
    while True:
        code = "".join(secrets.choice(INVITE_CHARS) for _ in range(8))
        if not con.execute("SELECT 1 FROM users WHERE invite_code = ?", (code,)).fetchone():
            return code


def show_code(code):
    return code[:4] + "-" + code[4:]


def clean_code(text):
    """What someone typed -> stored form: 'k7mp 3xqa' -> 'K7MP3XQA'."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def username_problem(con, name):
    """Why an admin can't use this username, or None."""
    if not isinstance(name, str) or not USERNAME_RE.fullmatch(name):
        return "Usernames are 3-20 letters, numbers, - or _."
    if con.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone():
        return "There's already a user called %s." % name
    if con.execute("SELECT 1 FROM users WHERE screen_name = ? COLLATE NOCASE", (name,)).fetchone():
        return "Someone already uses %s as their screen name." % name
    return None


MAX_PROPER_NAME = 100


def clean_proper_name(text):
    """A person's name as written in legal and formal contexts. Only admins
    ever see it. Any characters (accents, apostrophes, hyphens) are fine."""
    return " ".join(str(text or "").split())


def proper_name_problem(name):
    if not name:
        return "Enter their proper name (as written in legal and formal contexts)."
    if len(name) > MAX_PROPER_NAME:
        return "Proper names can be up to %d characters." % MAX_PROPER_NAME
    return None


def create_invite(con, username, proper_name, admin=False, grade=1):
    code = new_invite_code(con)
    cur = con.execute(
        "INSERT INTO users (username, password, created, is_admin, invite_code, proper_name, "
        "grade_level) VALUES (?, '', ?, ?, ?, ?, ?)",
        (username, int(time.time()), 1 if admin else 0, code, proper_name, grade))
    return cur.lastrowid, code


def shown_name(row):
    """The name other people see."""
    return row["screen_name"] or row["username"]


def admin_name(row):
    """How the admin tools refer to someone: their proper name if known."""
    return row["proper_name"] or row["username"]


# Timeout lengths offered on the admin page, in minutes (up to a week).
TIMEOUT_CHOICES = (15, 60, 24 * 60, 7 * 24 * 60, -1)  # -1: indefinitely
MAX_TIMEOUT_MINUTES = 7 * 24 * 60
INDEFINITE = -1
FOREVER = 253402300799  # timeout_until for "indefinitely": the last second of 9999


def until_text(ts):
    """'3:45 PM' today, otherwise 'Fri Nov 28, 3:45 PM' (the Pi's time zone).
    An indefinite timeout reads 'further notice'."""
    if ts >= FOREVER:
        return "further notice"
    t = time.localtime(ts)
    clock = time.strftime("%I:%M %p", t).lstrip("0")
    if time.strftime("%Y-%m-%d", t) == time.strftime("%Y-%m-%d"):
        return clock
    return time.strftime("%a %b ", t) + str(t.tm_mday) + ", " + clock


def length_text(minutes):
    for size, word in ((10080, "week"), (1440, "day"), (60, "hour"), (1, "minute")):
        if minutes % size == 0:
            n = minutes // size
            return "%d %s%s" % (n, word, "" if n == 1 else "s")


def set_timeout(con, user_id, minutes):
    """Start (minutes > 0, or INDEFINITE) or end (0) a timeout. Starting one
    logs them out."""
    if minutes == INDEFINITE:
        until = FOREVER
    else:
        until = int(time.time()) + minutes * 60 if minutes > 0 else 0
    con.execute("UPDATE users SET timeout_until = ? WHERE id = ?", (until, user_id))
    if until:
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return until


# ---------------------------------------------------------------- passwords

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P,
                                      salt.hex(), digest.hex())


def check_password(password, stored):
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=32,
                             maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False


# Checked against when a username doesn't exist, so a wrong name takes as
# long as a wrong password and doesn't reveal which accounts exist.
DUMMY_HASH = None


# ---------------------------------------------------------------- word filter
# The list lives in server/blocked-words.txt (see the notes at its top) and is
# re-read whenever the file changes.

WORDS_FILE = os.path.join(ROOT, "server", "blocked-words.txt")
_words = {"mtime": None, "patterns": []}
_words_lock = threading.Lock()

# Endings allowed after a plain "word" entry: ass -> asses, damn -> damned.
WORD_ENDINGS = r"(?:s|es|ed|d|er|ers|ing|y|ies)?"
# Look-alike characters, only swapped when they sit in a chunk that has
# letters, so "455 points" stays a number.
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
                      "7": "t", "8": "b", "9": "g", "@": "a", "$": "s"})


def _word_pattern(entry):
    """'shit*' -> regex. Each letter may repeat (fuuuck), but never fewer
    times than in the entry, so 'ass' matches 'asss' but not 'as'."""
    exact = entry.startswith("=")
    word = entry.lstrip("=").strip("*")
    core = "".join(re.escape(m.group(1)) + "{%d,}" % len(m.group(0))
                   for m in re.finditer(r"(.)\1*", word))
    if entry.startswith("*") and entry.endswith("*"):
        return re.compile(core)
    if entry.endswith("*"):
        return re.compile("^" + core)
    return re.compile("^" + core + ("" if exact else WORD_ENDINGS) + "$")


def blocked_patterns():
    try:
        mtime = os.path.getmtime(WORDS_FILE)
    except OSError:
        return _words["patterns"]
    with _words_lock:
        if mtime != _words["mtime"]:
            patterns = []
            with open(WORDS_FILE, encoding="utf-8") as f:
                for line in f:
                    entry = normalize(line.split("#", 1)[0].strip())
                    if entry.lstrip("=").strip("*"):
                        patterns.append(_word_pattern(entry))
            _words["patterns"] = patterns
            _words["mtime"] = mtime
        return _words["patterns"]


def normalize(text):
    """Lowercase, drop accents and invisible characters."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)
                   and unicodedata.category(c) != "Cf")


def candidate_words(text):
    """Every word a blocked word could be hiding in."""
    words = []
    singles = []  # runs of lone letters: "f u c k" -> "fuck"
    for chunk in normalize(text).split():
        if re.search(r"[a-z]", chunk):
            chunk = chunk.translate(LEET)
            chunk = re.sub(r"(?<=[a-z0-9])[!|](?=[a-z0-9])", "i", chunk)  # sh!t
        parts = re.findall(r"[a-z]+", chunk)
        words.extend(parts)
        if len(parts) > 1:
            words.append("".join(parts))  # fu-ck, f.u.c.k
        for p in parts:
            if len(p) == 1:
                singles.append(p)
            else:
                if len(singles) > 1:
                    words.append("".join(singles))
                singles = []
        if not parts:
            if len(singles) > 1:
                words.append("".join(singles))
            singles = []
    if len(singles) > 1:
        words.append("".join(singles))
    return words


def has_blocked_word(text):
    patterns = blocked_patterns()
    return any(p.search(w) for w in candidate_words(text) for p in patterns)


# ---------------------------------------------------------------- game list

# Hidden games: their .swf files and their own list (games/hidden/games.js)
# live in this folder. Only admins and accounts with the hidden_games flag
# can load anything in it or use those games' comments, ratings and unlocks.
# For them, hidden games work exactly like the rest.
HIDDEN_FOLDER = "/games/hidden"
HIDDEN_LIST = os.path.join(ROOT, "games", "hidden", "games.js")

# Grade levels. Every standard account has one, 1-5. A game marked
# `mature: N` in its list never sits behind the "?" lock: accounts at grade N
# or above (and admins) get it open, everyone else can't see or load it.
GRADES = range(1, 6)
PUBLIC_LIST = os.path.join(ROOT, "games.js")

_games = {}
_games_lock = threading.Lock()


def _games_in(path):
    """{id: {"file": ..., "mature": level or 0}} for a games.js-style list,
    re-read whenever the file changes. Comment lines are skipped."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _games_lock:
        cached = _games.get(path)
        if cached is None or cached[0] != mtime:
            with open(path, encoding="utf-8") as f:
                text = "\n".join(line for line in f.read().splitlines()
                                 if not line.lstrip().startswith("//"))
            games = {}
            for block in re.findall(r"\{([^{}]*)\}", text):
                gid = re.search(r'\bid:\s*"([a-z0-9-]+)"', block)
                if not gid:
                    continue
                file = re.search(r'\bfile:\s*"([^"]+)"', block)
                title = re.search(r'\btitle:\s*"((?:[^"\\]|\\.)*)"', block)
                mature = re.search(r"\bmature:\s*([0-9]+)", block)
                games[gid.group(1)] = {
                    "title": title.group(1).replace('\\"', '"') if title else gid.group(1),
                    "file": file.group(1) if file else "",
                    "mature": int(mature.group(1)) if mature else 0,
                }
            cached = _games[path] = (mtime, games)
        return cached[1]


def may_see_hidden(user):
    return bool(user and (user["is_admin"] or user["hidden_games"]))


# Admin-page game settings, cached for a couple of seconds so checking every
# file request doesn't mean a database read each time.
_settings = {"at": 0.0, "rows": {}}
_settings_lock = threading.Lock()


def game_settings(fresh=False):
    """{game id: {"mature": None or 0-5, "disabled": bool}}"""
    with _settings_lock:
        if fresh or time.time() - _settings["at"] > 2:
            con = connect()
            try:
                rows = con.execute("SELECT game, mature, disabled FROM game_settings").fetchall()
            finally:
                con.close()
            _settings["rows"] = {r["game"]: {"mature": r["mature"], "disabled": bool(r["disabled"])}
                                 for r in rows}
            _settings["at"] = time.time()
        return _settings["rows"]


def with_settings(games):
    """Copies of the list entries with the admin page's settings applied:
    mature is the level in force, listed_mature what the list file says."""
    settings = game_settings()
    out = {}
    for gid, info in games.items():
        set_ = settings.get(gid, {})
        mature = set_.get("mature")
        out[gid] = dict(info, listed_mature=info["mature"],
                        mature=info["mature"] if mature is None else mature,
                        disabled=set_.get("disabled", False))
    return out


def game_title(gid):
    games = dict(_games_in(PUBLIC_LIST))
    games.update(_games_in(HIDDEN_LIST))
    return games[gid]["title"] if gid in games else gid


def log_admin(con, admin, action):
    """One line in the Admin log for something an admin did on the admin page."""
    con.execute("INSERT INTO admin_log (created, admin_id, admin, action) VALUES (?, ?, ?, ?)",
                (int(time.time()), admin["id"], admin_name(admin), action))


def is_admin(user):
    return bool(user and user["is_admin"])


def playable(user, info):
    """May this user see and play this (listed) game? Admins: always."""
    return is_admin(user) or (not info["disabled"] and grade_allows(user, info["mature"]))


def grade_allows(user, level):
    """Mature level 0 means not mature: anyone may see it."""
    return not level or bool(user and (user["is_admin"] or user["grade_level"] >= level))


def listed_games(user):
    """{id: info} for every game in the lists this user may see, ignoring grade."""
    games = dict(_games_in(PUBLIC_LIST))
    if may_see_hidden(user):
        games.update(_games_in(HIDDEN_LIST))
    return with_settings(games)


def game_ids(user=None):
    """Every game this user may see and play: games.js, plus the hidden ones
    if allowed, minus mature games above their grade and disabled games
    (admins keep those)."""
    return frozenset(gid for gid, info in listed_games(user).items() if playable(user, info))


def mature_level(gid, user=None):
    info = listed_games(user).get(gid)
    return info["mature"] if info else 0


def file_blocked(lowered, user):
    """lowered: a clean_path()-ed, lower-cased URL path. True if it's the .swf
    of a game this user may not play: disabled, or mature above their grade."""
    games = dict(_games_in(PUBLIC_LIST))
    games.update(_games_in(HIDDEN_LIST))
    for info in with_settings(games).values():
        if clean_path(info["file"]).lower() == lowered:
            return not playable(user, info)
    return False


def is_hidden_path(lowered):
    """lowered: a clean_path()-ed, lower-cased URL path."""
    return lowered == HIDDEN_FOLDER or lowered.startswith(HIDDEN_FOLDER + "/")


# ---------------------------------------------------------------- rate limits

class Limiter:
    """Counts events per key in a sliding window. In memory: resets on restart."""

    def __init__(self):
        self.hits = {}
        self.lock = threading.Lock()

    def allowed(self, key, limit, window):
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(key, ()) if now - t < window]
            self.hits[key] = recent
            return len(recent) < limit

    def add(self, key):
        now = time.time()
        with self.lock:
            self.hits.setdefault(key, []).append(now)
            if len(self.hits) > 20000:  # forget anything older than a day
                self.hits = {k: v for k, v in self.hits.items()
                             if v and now - v[-1] < 86400}

    def take(self, key, limit, window):
        """Record one event if under the limit. False means 'too many'."""
        if not self.allowed(key, limit, window):
            return False
        self.add(key)
        return True


LIMITS = Limiter()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def need(ok, status, message):
    if not ok:
        raise ApiError(status, message)


# ---------------------------------------------------------------- HTTP

ROUTES = [
    ("GET", r"/api/me", "me"),
    ("GET", r"/api/auth-check", "auth_check"),
    ("POST", r"/api/login", "login"),
    ("POST", r"/api/logout", "logout"),
    ("GET", r"/api/ratings", "all_ratings"),
    ("GET", r"/api/games/" + GAME_ID, "game"),
    ("POST", r"/api/games/" + GAME_ID + r"/comments", "add_comment"),
    ("PUT", r"/api/games/" + GAME_ID + r"/rating", "rate"),
    ("DELETE", r"/api/comments/(\d+)", "delete_comment"),
    ("POST", r"/api/comments/(\d+)/report", "report_comment"),
    ("GET", r"/api/unlocks", "unlocks"),
    ("POST", r"/api/games/" + GAME_ID + r"/unlock", "unlock"),
    ("GET", r"/api/saves", "saves"),
    ("POST", r"/api/saves", "update_saves"),
    # Admin tools page (admin.html). Every one checks the user is an admin.
    ("GET", r"/api/admin/reports", "admin_reports"),
    ("POST", r"/api/admin/comments/(\d+)/clear-reports", "admin_clear_reports"),
    ("GET", r"/api/admin/users", "admin_users"),
    ("POST", r"/api/admin/timeout", "admin_timeout"),
    ("POST", r"/api/admin/hidden-games", "admin_hidden_games"),
    ("GET", r"/api/admin/unlocks/([A-Za-z0-9_-]{1,40})", "admin_unlocks"),
    ("POST", r"/api/admin/unlocks", "admin_set_unlocks"),
    ("POST", r"/api/admin/grade", "admin_grade"),
    ("GET", r"/api/admin/games", "admin_games"),
    ("GET", r"/api/admin/log", "admin_log"),
    ("POST", r"/api/admin/games/" + GAME_ID, "admin_game_settings"),
    ("GET", r"/api/admin/invites", "admin_invites"),
    ("POST", r"/api/admin/invites", "admin_add_invite"),
    ("POST", r"/api/admin/invites/(\d+)/new-code", "admin_new_code"),
    ("DELETE", r"/api/admin/invites/(\d+)", "admin_delete_invite"),
    # Joining with an invite code (join.html), before anyone is logged in.
    ("POST", r"/api/invite/check", "invite_check"),
    ("POST", r"/api/invite/join", "invite_join"),
]

# Never served by --dev, even though they sit in the site folder.
PRIVATE_PREFIXES = ("/server", "/data", "/.git", "/.gitignore")

# What pages (and the Flash games inside them) may load. Games can only fetch
# from this site and the Ruffle CDN, which stops the old ad networks and
# trackers built into many .swf files. Keep in step with server/Caddyfile.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://unpkg.com",
    "connect-src 'self' https://unpkg.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' data: blob:",
    "font-src 'self' data:",
    "worker-src 'self' blob:",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

# The only files anyone can load without logging in: the log-in page and what
# it needs. In production Caddy asks /api/auth-check about every request.
PUBLIC_PATHS = ("/login.html", "/join.html", "/pinpad.js", "/styles.css", "/background.jpg")


def clean_path(path):
    """Decode %xx and resolve ./, ../ and // the way the file lookup will."""
    return "/" + posixpath.normpath(unquote(path)).lstrip("/")


def login_redirect(uri):
    """Where to send someone who isn't logged in, so they come back after."""
    target = uri if uri.startswith("/") and not uri.startswith("//") else "/"
    return "/login.html?next=" + quote(target, safe="")


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "ClubEscapade/1.0"
    sys_version = ""
    # HTTP/1.0: one request per connection. Simpler and safe when an error
    # is sent before the body is read; Caddy keeps visitors' connections alive.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # -- dispatch

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("HEAD")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        # Split by hand, not urlsplit: urlsplit reads "//server/x" as a host
        # name, while the file lookup treats it as the folder "server".
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith("/api/"):
            return self.static(method, path)
        self.extra_headers = []
        try:
            self.route(method, path)
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except Exception:  # keep the server up; details go to the log
            self.log_error("error handling %s %s", method, path)
            import traceback
            traceback.print_exc()
            self.send_json(500, {"error": "Something went wrong on the server."})

    def static(self, method, path):
        # Decode %xx and resolve ./, ../ and // before checking, the same way
        # the file lookup will, so "/./server" can't sneak past "/server".
        lowered = clean_path(path).lower()
        if not CONFIG["dev"] or method not in ("GET", "HEAD") or any(
                lowered == p or lowered.startswith(p + "/") for p in PRIVATE_PREFIXES):
            self.send_error(404)
            return
        # Same rules Caddy applies in production with forward_auth.
        if lowered not in PUBLIC_PATHS:
            con = connect()
            try:
                user = self.current_user(con)
            finally:
                con.close()
            if user is None:
                self.send_response(302)
                self.send_header("Location", login_redirect(self.path))
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if (is_hidden_path(lowered) and not may_see_hidden(user)) or \
                    file_blocked(lowered, user):
                self.send_error(404)
                return
        self.revalidate = True
        if method == "HEAD":
            super().do_HEAD()
        else:
            super().do_GET()

    def end_headers(self):
        # Site files: the browser must ask again before reusing a cached copy,
        # so pages and games aren't reachable from the cache after logging out.
        # (Caddy does the same in production; see server/Caddyfile.)
        if getattr(self, "revalidate", False):
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def route(self, method, path):
        lookup = "GET" if method == "HEAD" else method
        path_known = False
        for route_method, pattern, name in ROUTES:
            match = re.fullmatch(pattern, path)
            if not match:
                continue
            path_known = True
            if route_method == lookup:
                if lookup != "GET":
                    self.check_same_site()
                con = connect()
                try:
                    status, body = getattr(self, "api_" + name)(con, *match.groups())
                    con.commit()
                finally:
                    con.close()
                self.send_json(status, body)
                return
        raise ApiError(405 if path_known else 404,
                       "Method not allowed." if path_known else "Not found.")

    # -- request helpers

    def check_same_site(self):
        """Block other websites from posting on a visitor's behalf.

        Browsers won't send a cross-site JSON request without asking first,
        and we never say yes, so requiring JSON plus a matching Origin is
        enough alongside the SameSite cookie."""
        ctype = self.headers.get("Content-Type", "")
        need(ctype.split(";")[0].strip() == "application/json", 415, "Send JSON.")
        origin = self.headers.get("Origin")
        if origin:
            need(urlsplit(origin).netloc == self.headers.get("Host", ""),
                 403, "Requests from other sites aren't allowed.")

    def json_body(self, max_bytes=MAX_BODY):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        need(0 <= length <= max_bytes, 413, "Request too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "Request isn't valid JSON.")
        need(isinstance(data, dict), 400, "Expected a JSON object.")
        return data

    def client_ip(self):
        ip = self.client_address[0]
        # Behind Caddy every request comes from localhost; Caddy puts the
        # visitor's address last in X-Forwarded-For.
        if ip in ("127.0.0.1", "::1"):
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[-1].strip()
        return ip

    def session_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http.cookies.CookieError:
            return None
        morsel = jar.get(COOKIE)
        return morsel.value if morsel else None

    def current_user(self, con):
        token = self.session_token()
        if not token:
            return None
        return con.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires > ? AND u.banned = 0 "
            "AND u.timeout_until <= ?",
            (token_hash(token), int(time.time()), int(time.time()))).fetchone()

    def require_user(self, con, message):
        user = self.current_user(con)
        need(user is not None, 401, message)
        return user

    def require_admin(self, con):
        user = self.require_user(con, "Log in first.")
        need(user["is_admin"], 403, "Admins only.")
        return user

    def start_session(self, con, user_id):
        now = int(time.time())
        con.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
        token = secrets.token_urlsafe(32)
        con.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
                    (token_hash(token), user_id, now + SESSION_SECONDS))
        self.set_cookie(token, SESSION_SECONDS)

    def set_cookie(self, value, max_age):
        parts = ["%s=%s" % (COOKIE, value), "Path=/", "HttpOnly",
                 "SameSite=Lax", "Max-Age=%d" % max_age]
        if not CONFIG["dev"]:
            parts.append("Secure")  # HTTPS only; --dev runs on plain http
        self.extra_headers.append(("Set-Cookie", "; ".join(parts)))

    def send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in getattr(self, "extra_headers", ()):
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # -- API: accounts

    def api_me(self, con):
        return 200, {"user": public_user(self.current_user(con))}

    def api_auth_check(self, con):
        """Caddy asks this before serving any page or file (forward_auth).
        200 lets the request through; anything else is sent back instead."""
        uri = self.headers.get("X-Forwarded-Uri", "/")
        lowered = clean_path(urlsplit(uri).path).lower()
        if lowered in PUBLIC_PATHS:
            return 200, {"ok": True}
        user = self.current_user(con)
        if user:
            # Hidden games: a plain "not found" for everyone not allowed.
            need(not is_hidden_path(lowered) or may_see_hidden(user), 404, "Not found.")
            need(not file_blocked(lowered, user), 404, "Not found.")
            return 200, {"ok": True}
        self.extra_headers.append(("Location", login_redirect(uri)))
        return 302, {"error": "Log in first."}

    def api_login(self, con):
        data = self.json_body()
        name = data.get("username")
        pin = data.get("pin")
        need(isinstance(name, str) and name.strip(), 400, "Enter your username.")
        need(isinstance(pin, str) and PIN_RE.fullmatch(pin), 400, "Enter your %d-digit PIN." % PIN_LENGTH)
        ip_key = "loginfail:" + self.client_ip()
        user_key = "loginfail-user:" + name.strip().lower()
        need(LIMITS.allowed(ip_key, PIN_FAILS_PER_IP, 900), 429,
             "Too many wrong PINs from here. Wait 15 minutes and try again.")
        need(LIMITS.allowed(user_key, PIN_FAILS_PER_USER, 900), 429,
             "Too many wrong PINs for this name. Wait 15 minutes, or ask your teacher.")
        user = con.execute("SELECT * FROM users WHERE username = ?", (name.strip(),)).fetchone()
        need(not (user and user["invite_code"]), 403,
             "This account isn't set up yet. Use your invite code on the Join page.")
        ok = check_password(pin, user["password"] if user else DUMMY_HASH)
        if not (user and ok):
            LIMITS.add(ip_key)
            LIMITS.add(user_key)
            raise ApiError(401, "Wrong username or PIN.")
        need(not user["banned"], 403, "This account has been banned.")
        need(user["timeout_until"] <= time.time(), 403,
             "You're in a timeout until %s." % until_text(user["timeout_until"]))
        self.start_session(con, user["id"])
        return 200, {"user": public_user(user)}

    # -- API: joining with an invite code

    def find_invite(self, con, code):
        """The pending account for a code. Wrong guesses are rate limited."""
        fail_key = "invitefail:" + self.client_ip()
        need(LIMITS.allowed(fail_key, 50, 900), 429,
             "Too many wrong codes from here. Wait 15 minutes and try again.")
        code = clean_code(code or "")
        user = con.execute("SELECT * FROM users WHERE invite_code = ?",
                           (code,)).fetchone() if len(code) == 8 else None
        if user is None:
            LIMITS.add(fail_key)
            raise ApiError(404, "That code doesn't work. Check it and try again.")
        return user

    def check_screen_name(self, con, name, user_id):
        need(isinstance(name, str) and USERNAME_RE.fullmatch(name), 400,
             "Screen names are 3-20 letters, numbers, - or _ (no spaces).")
        need(not has_blocked_word(name), 400, "That screen name isn't allowed. Try another.")
        # No one may look like someone else: not another screen name, and not
        # another account's username while that account shows its username.
        taken = con.execute(
            "SELECT 1 FROM users WHERE id != ? AND (screen_name = ? COLLATE NOCASE "
            "OR (screen_name IS NULL AND invite_code IS NULL AND username = ?))",
            (user_id, name, name)).fetchone()
        need(taken is None, 409, "Someone already has that screen name. Try another.")

    def api_invite_check(self, con):
        """Body: {"code"} or {"code", "screenName"}: checks before the PIN step."""
        data = self.json_body()
        user = self.find_invite(con, data.get("code"))
        if "screenName" in data:
            self.check_screen_name(con, data.get("screenName"), user["id"])
        return 200, {"username": user["username"]}

    def api_invite_join(self, con):
        """Body: {"code", "screenName", "pin"}. Sets up the account and logs in."""
        data = self.json_body()
        user = self.find_invite(con, data.get("code"))
        name, pin = data.get("screenName"), data.get("pin")
        self.check_screen_name(con, name, user["id"])
        need(isinstance(pin, str) and PIN_RE.fullmatch(pin), 400,
             "Your PIN needs to be %d digits." % PIN_LENGTH)
        try:
            cur = con.execute(
                "UPDATE users SET screen_name = ?, password = ?, invite_code = NULL "
                "WHERE id = ? AND invite_code = ?",
                (name, hash_password(pin), user["id"], user["invite_code"]))
        except sqlite3.IntegrityError:
            raise ApiError(409, "Someone already has that screen name. Try another.")
        need(cur.rowcount == 1, 409, "That code was just used. Ask your teacher.")
        self.start_session(con, user["id"])
        user = con.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        return 200, {"user": public_user(user)}

    def api_logout(self, con):
        token = self.session_token()
        if token:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        self.set_cookie("", 0)
        return 200, {"user": None}

    # -- API: games

    def check_game(self, game, user):
        need(game in game_ids(user), 404, "No such game.")

    def api_game(self, con, game):
        user = self.require_user(con, "Log in first.")
        self.check_game(game, user)
        rows = con.execute(
            "SELECT c.id, c.body, c.created, c.user_id, u.username, u.screen_name, "
            "(SELECT COUNT(*) FROM reports r WHERE r.comment_id = c.id) AS reports, "
            "EXISTS (SELECT 1 FROM reports r WHERE r.comment_id = c.id AND r.user_id = ?) AS mine "
            "FROM comments c JOIN users u ON u.id = c.user_id "
            "WHERE c.game = ? AND u.banned = 0 ORDER BY c.id DESC LIMIT 200",
            (user["id"] if user else 0, game)).fetchall()
        comments = []
        for r in rows:
            own = bool(user and user["id"] == r["user_id"])
            c = {
                "id": r["id"],
                "user": shown_name(r),
                "body": r["body"],
                "created": r["created"],
                "canDelete": bool(own or (user and user["is_admin"])),
                "canReport": bool(user and not own),
                "reported": bool(r["mine"]),
            }
            if user and user["is_admin"]:
                c["reports"] = r["reports"]  # only admins see how many
            comments.append(c)
        return 200, {"comments": comments, "rating": rating_summary(con, game, user)}

    def api_add_comment(self, con, game):
        user = self.require_user(con, "Log in to comment.")
        self.check_game(game, user)
        data = self.json_body()
        body = data.get("body")
        need(isinstance(body, str), 400, "Write a comment first.")
        body = re.sub(r"\n{3,}", "\n\n", body.replace("\r\n", "\n").strip())
        need(body, 400, "Write a comment first.")
        need(len(body) <= MAX_COMMENT, 400,
             "Comments can be up to %d characters." % MAX_COMMENT)
        need(not has_blocked_word(body), 400,
             "Please keep it clean. Your comment has a word that isn't allowed here.")
        uid = str(user["id"])
        need(LIMITS.allowed("comment-min:" + uid, 5, 60) and
             LIMITS.allowed("comment-day:" + uid, 50, 86400), 429,
             "You're commenting too fast. Take a breather.")
        LIMITS.add("comment-min:" + uid)
        LIMITS.add("comment-day:" + uid)
        now = int(time.time())
        cur = con.execute(
            "INSERT INTO comments (game, user_id, body, created) VALUES (?, ?, ?, ?)",
            (game, user["id"], body, now))
        return 201, {"comment": {"id": cur.lastrowid, "user": shown_name(user),
                                 "body": body, "created": now, "canDelete": True}}

    def api_rate(self, con, game):
        user = self.require_user(con, "Log in to rate games.")
        self.check_game(game, user)
        data = self.json_body()
        stars = data.get("stars")
        need(type(stars) is int and 1 <= stars <= 5, 400, "Ratings are 1 to 5 stars.")
        need(LIMITS.take("rate:%d" % user["id"], 30, 60), 429,
             "Slow down a little.")
        con.execute(
            "INSERT INTO ratings (game, user_id, stars, updated) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (game, user_id) DO UPDATE SET stars = excluded.stars, "
            "updated = excluded.updated",
            (game, user["id"], stars, int(time.time())))
        return 200, {"rating": rating_summary(con, game, user)}

    def api_delete_comment(self, con, comment_id):
        user = self.require_user(con, "Log in first.")
        row = con.execute("SELECT user_id FROM comments WHERE id = ?",
                          (int(comment_id),)).fetchone()
        need(row is not None, 404, "That comment is already gone.")
        need(row["user_id"] == user["id"] or user["is_admin"], 403,
             "You can only delete your own comments.")
        if row["user_id"] != user["id"]:  # an admin removing someone else's
            info = con.execute("SELECT c.game, c.body, u.* FROM comments c JOIN users u "
                               "ON u.id = c.user_id WHERE c.id = ?", (int(comment_id),)).fetchone()
            body = info["body"] if len(info["body"]) <= 80 else info["body"][:77] + "..."
            log_admin(con, user, 'Deleted %s\'s comment on %s: "%s"'
                      % (admin_name(info), game_title(info["game"]), body))
        con.execute("DELETE FROM comments WHERE id = ?", (int(comment_id),))
        return 200, {"deleted": int(comment_id)}

    def api_report_comment(self, con, comment_id):
        user = self.require_user(con, "Log in to report a comment.")
        row = con.execute("SELECT user_id FROM comments WHERE id = ?",
                          (int(comment_id),)).fetchone()
        need(row is not None, 404, "That comment is already gone.")
        need(row["user_id"] != user["id"], 400, "You can't report your own comment.")
        need(LIMITS.take("report:" + str(user["id"]), 20, 3600), 429,
             "You've sent a lot of reports. Try again later.")
        con.execute("INSERT OR IGNORE INTO reports (comment_id, user_id, created) "
                    "VALUES (?, ?, ?)", (int(comment_id), user["id"], int(time.time())))
        return 200, {"reported": int(comment_id)}

    # -- API: admin tools page

    def api_admin_reports(self, con):
        self.require_admin(con)
        rows = con.execute(
            "SELECT c.id, c.game, c.body, c.created, u.username, u.screen_name, u.proper_name, "
            "u.banned, u.timeout_until, COUNT(r.user_id) AS reports, MAX(r.created) AS last_report "
            "FROM comments c JOIN users u ON u.id = c.user_id "
            "JOIN reports r ON r.comment_id = c.id "
            "GROUP BY c.id ORDER BY reports DESC, last_report DESC").fetchall()
        now = time.time()
        return 200, {"comments": [{
            "id": r["id"], "game": r["game"], "user": shown_name(r), "username": r["username"],
            "adminName": admin_name(r),
            "body": r["body"],
            "created": r["created"], "reports": r["reports"], "lastReport": r["last_report"],
            "banned": bool(r["banned"]),
            "timeoutUntil": r["timeout_until"] if r["timeout_until"] > now else None,
        } for r in rows]}

    def api_admin_clear_reports(self, con, comment_id):
        admin = self.require_admin(con)
        info = con.execute("SELECT c.game, u.* FROM comments c JOIN users u ON u.id = c.user_id "
                           "WHERE c.id = ?", (int(comment_id),)).fetchone()
        if info:
            log_admin(con, admin, "Dismissed reports on %s's comment on %s (kept it)"
                      % (admin_name(info), game_title(info["game"])))
        con.execute("DELETE FROM reports WHERE comment_id = ?", (int(comment_id),))
        return 200, {"cleared": int(comment_id)}

    def api_admin_users(self, con):
        self.require_admin(con)
        now = time.time()
        return 200, {"choices": TIMEOUT_CHOICES, "users": [{
            "name": u["username"], "screenName": u["screen_name"],
            "properName": u["proper_name"], "adminName": admin_name(u),
            "admin": bool(u["is_admin"]), "banned": bool(u["banned"]),
            "hiddenGames": bool(u["hidden_games"]), "grade": u["grade_level"],
            "timeoutUntil": u["timeout_until"] if u["timeout_until"] > now else None,
            "until": until_text(u["timeout_until"]) if u["timeout_until"] > now else None,
        } for u in con.execute("SELECT * FROM users WHERE invite_code IS NULL ORDER BY "
                               "COALESCE(NULLIF(proper_name, ''), username) COLLATE NOCASE")]}

    def api_admin_timeout(self, con):
        """Body: {"username": NAME, "minutes": N}. 0 minutes ends a timeout."""
        admin = self.require_admin(con)
        data = self.json_body()
        name, minutes = data.get("username"), data.get("minutes")
        need(isinstance(name, str) and isinstance(minutes, int)
             and (0 <= minutes <= MAX_TIMEOUT_MINUTES or minutes == INDEFINITE), 400,
             "Pick a student and a length.")
        user = con.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        need(user is not None and user["invite_code"] is None, 404,
             "No student called %s." % name)
        need(user["id"] != admin["id"], 400, "You can't time yourself out.")
        need(not user["is_admin"], 400, "Admins can't be timed out.")
        until = set_timeout(con, user["id"], minutes)
        if not until:
            log_admin(con, admin, "Ended %s's timeout" % admin_name(user))
        elif minutes == INDEFINITE:
            log_admin(con, admin, "Timed out %s indefinitely" % admin_name(user))
        else:
            log_admin(con, admin, "Timed out %s for %s (until %s)"
                      % (admin_name(user), length_text(minutes), until_text(until)))
        return 200, {"name": user["username"], "adminName": admin_name(user),
                     "timeoutUntil": until or None,
                     "until": until_text(until) if until else None}

    def api_admin_hidden_games(self, con):
        """Body: {"username": NAME, "allowed": true/false}."""
        admin = self.require_admin(con)
        data = self.json_body()
        name, allowed = data.get("username"), data.get("allowed")
        need(isinstance(name, str) and isinstance(allowed, bool), 400,
             "Pick a student and yes or no.")
        user = con.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        need(user is not None and user["invite_code"] is None, 404,
             "No student called %s." % name)
        con.execute("UPDATE users SET hidden_games = ? WHERE id = ?", (int(allowed), user["id"]))
        log_admin(con, admin, ("Let %s see the hidden games" if allowed
                               else "Took the hidden games away from %s") % admin_name(user))
        return 200, {"name": user["username"], "adminName": admin_name(user),
                     "hiddenGames": allowed}

    def admin_target(self, con, name):
        """A student (not an admin, not a waiting invite) for the admin tools."""
        user = con.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        need(user is not None and user["invite_code"] is None, 404,
             "No student called %s." % name)
        need(not user["is_admin"], 400, "Admins can already play every game.")
        return user

    def api_admin_log(self, con):
        """The 300 newest Admin log lines, newest first."""
        self.require_admin(con)
        rows = con.execute("SELECT created, admin, action FROM admin_log "
                           "ORDER BY id DESC LIMIT 300").fetchall()
        return 200, {"log": [{"created": r["created"], "admin": r["admin"], "action": r["action"]}
                             for r in rows]}

    def api_admin_games(self, con):
        """Every game in both lists, with its settings."""
        self.require_admin(con)
        hidden = set(_games_in(HIDDEN_LIST))
        games = dict(_games_in(PUBLIC_LIST))
        games.update(_games_in(HIDDEN_LIST))
        return 200, {"games": [{
            "id": gid, "hidden": gid in hidden, "mature": info["mature"],
            "listedMature": info["listed_mature"], "disabled": info["disabled"],
        } for gid, info in sorted(with_settings(games).items())]}

    def api_admin_game_settings(self, con, game):
        """Body: {"mature": 0-5} and/or {"disabled": true/false}."""
        admin = self.require_admin(con)
        games = dict(_games_in(PUBLIC_LIST))
        games.update(_games_in(HIDDEN_LIST))
        need(game in games, 404, "No such game.")
        data = self.json_body()
        mature, disabled = data.get("mature"), data.get("disabled")
        need(mature is not None or disabled is not None, 400, "Nothing to change.")
        need(mature is None or (isinstance(mature, int) and not isinstance(mature, bool)
                                and 0 <= mature <= 5), 400,
             "Maturity is 0 (not mature) or a grade from 1 to 5.")
        need(disabled is None or isinstance(disabled, bool), 400, "Bad disabled value.")
        con.execute("INSERT OR IGNORE INTO game_settings (game) VALUES (?)", (game,))
        name = game_title(game)
        if mature is not None:
            con.execute("UPDATE game_settings SET mature = ? WHERE game = ?", (mature, game))
            log_admin(con, admin, "Set %s to %s" % (
                name, "grade %d and up" % mature if mature else "not mature"))
        if disabled is not None:
            con.execute("UPDATE game_settings SET disabled = ? WHERE game = ?",
                        (int(disabled), game))
            log_admin(con, admin, "%s %s for students" % ("Disabled" if disabled else "Enabled",
                                                          name))
        con.commit()
        game_settings(fresh=True)  # take effect now, not in a couple of seconds
        info = with_settings({game: games[game]})[game]
        return 200, {"id": game, "mature": info["mature"], "listedMature": info["listed_mature"],
                     "disabled": info["disabled"]}

    def api_admin_grade(self, con):
        """Body: {"username": NAME, "grade": 1-5}."""
        admin = self.require_admin(con)
        data = self.json_body()
        name, grade = data.get("username"), data.get("grade")
        need(isinstance(name, str) and isinstance(grade, int) and grade in GRADES, 400,
             "Pick a student and a grade from 1 to 5.")
        user = self.admin_target(con, name)
        con.execute("UPDATE users SET grade_level = ? WHERE id = ?", (grade, user["id"]))
        log_admin(con, admin, "Set %s's grade to %d" % (admin_name(user), grade))
        return 200, {"name": user["username"], "adminName": admin_name(user), "grade": grade}

    def api_admin_unlocks(self, con, name):
        """The games a student has unlocked, and every game they could."""
        self.require_admin(con)
        user = self.admin_target(con, name)
        rows = con.execute("SELECT game FROM unlocks WHERE user_id = ?", (user["id"],))
        listed = listed_games(user)
        unlockable = {gid for gid, info in listed.items() if not info["mature"]}
        return 200, {"name": user["username"], "adminName": admin_name(user),
                     "grade": user["grade_level"],
                     "games": sorted(unlockable),
                     "unlocked": sorted(r["game"] for r in rows if r["game"] in unlockable),
                     "mature": [{"id": gid, "level": info["mature"],
                                 "allowed": grade_allows(user, info["mature"])}
                                for gid, info in sorted(listed.items()) if info["mature"]]}

    def api_admin_set_unlocks(self, con):
        """Body: {"username": NAME, "games": [id, ...], "unlocked": true/false}."""
        admin = self.require_admin(con)
        data = self.json_body()
        name, games, unlocked = data.get("username"), data.get("games"), data.get("unlocked")
        need(isinstance(name, str) and isinstance(games, list) and games
             and all(isinstance(g, str) for g in games) and isinstance(unlocked, bool),
             400, "Pick a student, some games, and lock or unlock.")
        user = self.admin_target(con, name)
        allowed = game_ids(user)
        unknown = [g for g in games if g not in allowed]
        need(not unknown, 404, "No such game: %s." % ", ".join(unknown[:3]))
        mature = [g for g in games if mature_level(g, user)]
        need(not mature, 400, "Mature games don't unlock; they go by grade.")
        now = int(time.time())
        for game in games:
            if unlocked:
                con.execute("INSERT OR IGNORE INTO unlocks (user_id, game, created) "
                            "VALUES (?, ?, ?)", (user["id"], game, now))
            else:
                con.execute("DELETE FROM unlocks WHERE user_id = ? AND game = ?",
                            (user["id"], game))
        what = game_title(games[0]) if len(games) == 1 else "%d games" % len(games)
        log_admin(con, admin, "%s %s for %s" % ("Unlocked" if unlocked else "Locked", what,
                                                admin_name(user)))
        return 200, {"name": user["username"], "adminName": admin_name(user),
                     "games": games, "unlocked": unlocked}

    def api_admin_invites(self, con):
        self.require_admin(con)
        rows = con.execute("SELECT id, username, proper_name, invite_code, created FROM users "
                           "WHERE invite_code IS NOT NULL ORDER BY id DESC")
        return 200, {"invites": [{"id": r["id"], "username": r["username"],
                                  "adminName": admin_name(r),
                                  "code": show_code(r["invite_code"]), "created": r["created"]}
                                 for r in rows]}

    def api_admin_add_invite(self, con):
        admin = self.require_admin(con)
        data = self.json_body()
        proper = clean_proper_name(data.get("properName"))
        problem = proper_name_problem(proper)
        need(problem is None, 400, problem)
        name = data.get("username") or ""
        name = name.strip() if isinstance(name, str) else name
        problem = username_problem(con, name)
        need(problem is None, 400, problem)
        user_id, code = create_invite(con, name, proper)
        log_admin(con, admin, "Made an invite for %s (username %s)" % (proper, name))
        return 201, {"id": user_id, "username": name, "adminName": proper,
                     "code": show_code(code)}

    def pending_invite(self, con, user_id):
        row = con.execute("SELECT * FROM users WHERE id = ? AND invite_code IS NOT NULL",
                          (int(user_id),)).fetchone()
        need(row is not None, 404, "That invite was already used or deleted.")
        return row

    def api_admin_new_code(self, con, user_id):
        admin = self.require_admin(con)
        row = self.pending_invite(con, user_id)
        log_admin(con, admin, "Gave %s a new invite code" % admin_name(row))
        code = new_invite_code(con)
        con.execute("UPDATE users SET invite_code = ? WHERE id = ?", (code, row["id"]))
        return 200, {"id": row["id"], "adminName": admin_name(row), "code": show_code(code)}

    def api_admin_delete_invite(self, con, user_id):
        admin = self.require_admin(con)
        row = self.pending_invite(con, user_id)
        log_admin(con, admin, "Deleted the invite for %s" % admin_name(row))
        con.execute("DELETE FROM users WHERE id = ?", (row["id"],))
        return 200, {"deleted": row["id"]}

    # -- API: unlocking games
    # Every game starts hidden behind a "?" on the homepage. Pressing Play on
    # a game unlocks it for that person. Admins see everything.

    def api_unlocks(self, con):
        """unlocked: games this person opened with Play. open: mature games
        their grade allows (never locked). blocked: games they may not play
        (mature above their grade, or disabled), which the pages leave out."""
        user = self.require_user(con, "Log in first.")
        rows = con.execute("SELECT game FROM unlocks WHERE user_id = ? ORDER BY created",
                           (user["id"],))
        listed = listed_games(user)
        mature = {gid for gid, info in listed.items() if info["mature"]}
        allowed = game_ids(user)
        blocked = set(listed) - allowed
        return 200, {"user": user["username"], "all": bool(user["is_admin"]),
                     "unlocked": [r["game"] for r in rows
                                  if r["game"] not in mature and r["game"] not in blocked],
                     "open": sorted(mature & allowed),
                     "blocked": sorted(blocked)}

    def api_unlock(self, con, game):
        user = self.require_user(con, "Log in first.")
        self.check_game(game, user)
        need(not mature_level(game, user), 400, "Mature games don't unlock; they go by grade.")
        cur = con.execute("INSERT OR IGNORE INTO unlocks (user_id, game, created) VALUES (?, ?, ?)",
                          (user["id"], game, int(time.time())))
        return 200, {"game": game, "new": cur.rowcount == 1}

    # -- API: Flash game saves

    def api_saves(self, con):
        user = self.require_user(con, "Log in first.")
        rows = con.execute("SELECT key, value FROM saves WHERE user_id = ?", (user["id"],))
        return 200, {"user": user["username"], "saves": {r["key"]: r["value"] for r in rows}}

    def api_update_saves(self, con):
        """Body: {"put": {key: base64 value, ...}, "delete": [key, ...]}"""
        user = self.require_user(con, "Log in first.")
        need(LIMITS.take("saves:" + str(user["id"]), 120, 60), 429, "Saving too often.")
        data = self.json_body(MAX_SAVES_BODY)
        put, delete = data.get("put", {}), data.get("delete", [])
        need(isinstance(put, dict) and isinstance(delete, list), 400, "Bad save data.")
        for key, value in put.items():
            need(0 < len(key) <= MAX_SAVE_KEY and isinstance(value, str)
                 and len(value) <= MAX_SAVE_VALUE, 400, "A save is too big.")
        need(all(isinstance(k, str) for k in delete), 400, "Bad save data.")
        now = int(time.time())
        for key in delete:
            con.execute("DELETE FROM saves WHERE user_id = ? AND key = ?", (user["id"], key))
        for key, value in put.items():
            con.execute("INSERT INTO saves (user_id, key, value, updated) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value, "
                        "updated = excluded.updated", (user["id"], key, value, now))
        total = con.execute("SELECT COALESCE(SUM(LENGTH(key) + LENGTH(value)), 0) FROM saves "
                            "WHERE user_id = ?", (user["id"],)).fetchone()[0]
        if total > MAX_SAVES_TOTAL:
            con.rollback()
            raise ApiError(413, "Your saves are full. Ask your teacher to clear some.")
        return 200, {"saved": len(put), "deleted": len(delete)}

    def api_all_ratings(self, con):
        user = self.require_user(con, "Log in first.")
        rows = con.execute(
            "SELECT r.game, AVG(r.stars) AS avg, COUNT(*) AS count "
            "FROM ratings r JOIN users u ON u.id = r.user_id "
            "WHERE u.banned = 0 GROUP BY r.game").fetchall()
        known = game_ids(user)
        return 200, {"ratings": {r["game"]: {"avg": round(r["avg"], 2), "count": r["count"]}
                                 for r in rows if r["game"] in known}}

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.client_ip(), fmt % args))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row):
    if row is None:
        return None
    return {"name": shown_name(row), "username": row["username"], "admin": bool(row["is_admin"])}


def rating_summary(con, game, user):
    row = con.execute(
        "SELECT AVG(r.stars) AS avg, COUNT(*) AS count FROM ratings r "
        "JOIN users u ON u.id = r.user_id WHERE r.game = ? AND u.banned = 0",
        (game,)).fetchone()
    mine = None
    if user:
        own = con.execute("SELECT stars FROM ratings WHERE game = ? AND user_id = ?",
                          (game, user["id"])).fetchone()
        mine = own["stars"] if own else None
    return {"avg": round(row["avg"], 2) if row["avg"] is not None else None,
            "count": row["count"], "mine": mine}


# ---------------------------------------------------------------- command line

def find_user(con, name):
    user = con.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
    if user is None:
        sys.exit("No user called %r." % name)
    return user


def cmd_serve(args):
    global DUMMY_HASH
    CONFIG["dev"] = args.dev
    init_db()
    DUMMY_HASH = hash_password(secrets.token_hex(8))
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    mode = "site + API (dev mode, cookies over plain http)" if args.dev else "API only"
    print("Club Escapade %s on http://%s:%d  db=%s" % (mode, args.host, args.port, CONFIG["db"]),
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_set_flag(args, column, value, done):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    con.execute("UPDATE users SET %s = ? WHERE id = ?" % column, (value, user["id"]))
    if column == "banned" and value:
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    con.commit()
    print(done % user["username"])


def pick_pin(args, name):
    """--choose: type it twice. Otherwise a random one."""
    if not args.choose:
        return str(secrets.randbelow(10 ** PIN_LENGTH)).zfill(PIN_LENGTH)
    pin = getpass.getpass("New %d-digit PIN for %s: " % (PIN_LENGTH, name))
    if not PIN_RE.fullmatch(pin):
        sys.exit("PINs are exactly %d digits. Nothing changed." % PIN_LENGTH)
    if getpass.getpass("Type it again: ") != pin:
        sys.exit("Those didn't match. Nothing changed.")
    return pin


def cmd_add_user(args):
    init_db()
    con = connect()
    name = args.username
    problem = username_problem(con, name)
    if problem:
        sys.exit(problem)
    if has_blocked_word(name) and not args.force:
        sys.exit("%r has a word from blocked-words.txt. Add --force to use it anyway." % name)
    pin = pick_pin(args, name)
    proper = clean_proper_name(args.proper_name)
    if len(proper) > MAX_PROPER_NAME:
        sys.exit("Proper names can be up to %d characters." % MAX_PROPER_NAME)
    con.execute("INSERT INTO users (username, password, created, is_admin, proper_name, "
                "grade_level) VALUES (?, ?, ?, ?, ?, ?)",
                (name, hash_password(pin), int(time.time()), 1 if args.admin else 0, proper,
                 args.grade))
    con.commit()
    kind = "Admin" if args.admin else "User"
    if args.choose:
        print("%s %s added." % (kind, name))
    else:
        print("%s %s added. PIN:  %s" % (kind, name, pin))


def cmd_invite(args):
    init_db()
    con = connect()
    problem = username_problem(con, args.username)
    proper = clean_proper_name(args.proper_name)
    problem = problem or proper_name_problem(proper)
    if problem:
        sys.exit(problem)
    _, code = create_invite(con, args.username, proper, admin=args.admin, grade=args.grade)
    con.commit()
    print("Invite for %s (%s):  %s" % (proper, args.username, show_code(code)))
    print("They enter it on the Join page (join.html), pick a screen name and a PIN,")
    print("then log in with the username %s and that PIN." % args.username)


def cmd_set_proper_name(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    proper = clean_proper_name(args.proper_name)
    problem = proper_name_problem(proper)
    if problem:
        sys.exit(problem)
    con.execute("UPDATE users SET proper_name = ? WHERE id = ?", (proper, user["id"]))
    con.commit()
    print("%s's proper name is now %s." % (user["username"], proper))


def cmd_list_invites(args):
    init_db()
    con = connect()
    rows = con.execute("SELECT * FROM users WHERE invite_code IS NOT NULL ORDER BY id").fetchall()
    if not rows:
        print("No unused invites.")
    for r in rows:
        print("%s  %s  %-20s %s%s" % (show_code(r["invite_code"]),
                                      time.strftime("%Y-%m-%d", time.localtime(r["created"])),
                                      r["username"], r["proper_name"],
                                      "  (admin)" if r["is_admin"] else ""))


def cmd_reset_pin(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    pin = pick_pin(args, user["username"])
    con.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(pin), user["id"]))
    con.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    con.commit()
    if args.choose:
        print("PIN for %s changed. They've been logged out everywhere." % user["username"])
    else:
        print("New PIN for %s:  %s" % (user["username"], pin))
        print("They've been logged out everywhere. Give it to them in person.")


def cmd_clear_saves(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    sql, params = "DELETE FROM saves WHERE user_id = ?", [user["id"]]
    if args.game:
        # Ruffle names saves "<site>/<path to .swf>/<name>"; match the .swf part.
        sql += " AND key LIKE ? ESCAPE '\\'"
        file = "games/%s.swf/" % args.game
        params.append("%" + file.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    cur = con.execute(sql, params)
    con.commit()
    print("Deleted %d save%s for %s%s." % (cur.rowcount, "" if cur.rowcount == 1 else "s",
                                           user["username"], " in " + args.game if args.game else ""))


def cmd_delete_comment(args):
    init_db()
    con = connect()
    cur = con.execute("DELETE FROM comments WHERE id = ?", (args.id,))
    con.commit()
    print("Deleted comment %d." % args.id if cur.rowcount else "No comment %d." % args.id)


def cmd_list_comments(args):
    init_db()
    con = connect()
    where, params = [], []
    if args.game:
        where.append("c.game = ?")
        params.append(args.game)
    if args.user:
        where.append("u.id = ?")
        params.append(find_user(con, args.user)["id"])
    if args.reported:
        where.append("reports > 0")
    sql = ("SELECT c.id, c.game, c.body, c.created, u.username, u.screen_name, u.banned, "
           "(SELECT COUNT(*) FROM reports r WHERE r.comment_id = c.id) AS reports "
           "FROM comments c JOIN users u ON u.id = c.user_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = con.execute(sql + " ORDER BY c.id DESC LIMIT ?", params + [args.limit]).fetchall()
    if not rows:
        print("No reported comments." if args.reported else "No comments.")
        return
    for r in reversed(rows):  # oldest first, so the newest ends up by the prompt
        body = " ".join(r["body"].split())
        if len(body) > 70:
            body = body[:69] + "…"
        print("%5d  %s  %-20s %-20s %s%s%s" % (
            r["id"], time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"])),
            r["game"][:20], (r["username"] if not r["screen_name"] else "%s (%s)" % (r["screen_name"], r["username"]))[:20],
            "[%d report%s] " % (r["reports"], "" if r["reports"] == 1 else "s") if r["reports"] else "",
            "(banned) " if r["banned"] else "", body))


def cmd_clear_reports(args):
    init_db()
    con = connect()
    cur = con.execute("DELETE FROM reports WHERE comment_id = ?", (args.id,))
    con.commit()
    print("Cleared %d report%s on comment %d." % (cur.rowcount, "" if cur.rowcount == 1 else "s", args.id))


def cmd_timeout(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    if user["is_admin"]:
        sys.exit("Admins can't be timed out.")
    if not (0 <= args.minutes <= MAX_TIMEOUT_MINUTES or args.minutes == INDEFINITE):
        sys.exit("Timeouts are 0 to %d minutes (a week), or \"indefinitely\"."
                 % MAX_TIMEOUT_MINUTES)
    until = set_timeout(con, user["id"], args.minutes)
    con.commit()
    if until:
        print("%s is timed out until %s and logged out." % (user["username"], until_text(until)))
    else:
        print("%s's timeout is over." % user["username"])


def cmd_reset_unlocks(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    sql, params = "DELETE FROM unlocks WHERE user_id = ?", [user["id"]]
    if args.game:
        sql += " AND game = ?"
        params.append(args.game)
    cur = con.execute(sql, params)
    con.commit()
    print("Locked %d game%s again for %s." % (cur.rowcount, "" if cur.rowcount == 1 else "s",
                                              user["username"]))


def cmd_set_grade(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    con.execute("UPDATE users SET grade_level = ? WHERE id = ?", (args.grade, user["id"]))
    con.commit()
    print("%s is now in grade %d." % (user["username"], args.grade))


def cmd_list_users(args):
    init_db()
    con = connect()
    for u in con.execute("SELECT * FROM users WHERE invite_code IS NULL ORDER BY id"):
        flags = [f for f, on in (("admin", u["is_admin"]), ("banned", u["banned"]),
                                 ("hidden-games", u["hidden_games"])) if on]
        if u["screen_name"]:
            flags.insert(0, "shows as %s" % u["screen_name"])
        if u["proper_name"]:
            flags.insert(0, u["proper_name"])
        if not u["is_admin"]:
            flags.append("grade %d" % u["grade_level"])
        if u["timeout_until"] > time.time():
            flags.append("timeout until " + until_text(u["timeout_until"]))
        print("%4d  %-20s %s  %s" % (u["id"], u["username"],
                                     time.strftime("%Y-%m-%d", time.localtime(u["created"])),
                                     " ".join(flags)))


def main():
    parser = argparse.ArgumentParser(description="Club Escapade accounts and comments server.")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite file (default: data/club.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--dev", action="store_true",
                       help="also serve the site's files and allow cookies over http")

    for name, text in (("make-admin", "let a user delete any comment"),
                       ("remove-admin", "take admin away"),
                       ("ban", "block a user and hide their comments and ratings"),
                       ("unban", "lift a ban"),
                       ("allow-hidden", "let a user see the hidden games (games/hidden/)"),
                       ("disallow-hidden", "take hidden games away")):
        sub.add_parser(name, help=text).add_argument("username")
    sub.add_parser("delete-comment", help="delete one comment by id").add_argument("id", type=int)
    au = sub.add_parser("add-user", help="create an account (prints a random PIN)")
    au.add_argument("username")
    au.add_argument("--choose", action="store_true",
                    help="type the PIN yourself instead of getting a random one")
    au.add_argument("--admin", action="store_true", help="make the account an admin")
    au.add_argument("--force", action="store_true", help="allow a name the word filter blocks")
    au.add_argument("--proper-name", help="their name as in legal and formal contexts")
    au.add_argument("--grade", type=int, choices=GRADES, default=1, help="grade level 1-5 (default 1); mature games need at least theirs")
    iv = sub.add_parser("invite", help="make an account and print its invite code")
    iv.add_argument("username", help="what they'll log in with (they pick their screen name)")
    iv.add_argument("proper_name", help='their name as in legal and formal contexts, in quotes')
    iv.add_argument("--admin", action="store_true", help="the account will be an admin")
    iv.add_argument("--grade", type=int, choices=GRADES, default=1, help="grade level 1-5 (default 1); mature games need at least theirs")
    sub.add_parser("list-invites", help="show invite codes nobody has used yet")
    sp = sub.add_parser("set-proper-name", help="record someone's legal/formal name")
    sp.add_argument("username")
    sp.add_argument("proper_name", help="in quotes, e.g. \"Jamie Rivera\"")
    cs = sub.add_parser("clear-saves", help="delete a user's game saves")
    cs.add_argument("username")
    cs.add_argument("--game", help="only this game id, e.g. red-ball")
    rp = sub.add_parser("reset-pin", aliases=["reset-password"],
                        help="give a user a new PIN and log them out")
    rp.add_argument("username")
    rp.add_argument("--choose", action="store_true",
                    help="type the new PIN yourself instead of getting a random one")
    lc = sub.add_parser("list-comments", help="show recent comments with their ids")
    lc.add_argument("--game", help="only this game id, e.g. red-ball")
    lc.add_argument("--user", help="only this username")
    lc.add_argument("-n", "--limit", type=int, default=20, help="how many (default 20)")
    lc.add_argument("--reported", action="store_true", help="only comments someone reported")
    sub.add_parser("clear-reports", help="keep a reported comment and drop its reports"
                   ).add_argument("id", type=int)
    to = sub.add_parser("timeout", help="keep a user off the site for a while")
    to.add_argument("username")
    to.add_argument("minutes", type=lambda v: INDEFINITE if v.lower() in ("indefinitely", "forever")
                    else int(v), help='how long; 0 ends a timeout; "indefinitely" until you end it')
    sub.add_parser("end-timeout", help="let a timed-out user back in").add_argument("username")
    ru = sub.add_parser("reset-unlocks", help="hide games behind the ? again for a user")
    ru.add_argument("username")
    ru.add_argument("--game", help="only this game id")
    sub.add_parser("list-users", help="show every account")
    sg = sub.add_parser("set-grade", help="set a student's grade level (1-5)")
    sg.add_argument("username")
    sg.add_argument("grade", type=int, choices=GRADES)

    args = parser.parse_args()
    CONFIG["db"] = os.path.abspath(args.db)
    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "make-admin":
        cmd_set_flag(args, "is_admin", 1, "%s is now an admin.")
    elif args.command == "remove-admin":
        cmd_set_flag(args, "is_admin", 0, "%s is no longer an admin.")
    elif args.command == "ban":
        cmd_set_flag(args, "banned", 1, "%s is banned and logged out.")
    elif args.command == "unban":
        cmd_set_flag(args, "banned", 0, "%s is unbanned.")
    elif args.command == "set-grade":
        cmd_set_grade(args)
    elif args.command == "allow-hidden":
        cmd_set_flag(args, "hidden_games", 1, "%s can now see the hidden games.")
    elif args.command == "disallow-hidden":
        cmd_set_flag(args, "hidden_games", 0, "%s can no longer see the hidden games.")
    elif args.command == "invite":
        cmd_invite(args)
    elif args.command == "list-invites":
        cmd_list_invites(args)
    elif args.command == "set-proper-name":
        cmd_set_proper_name(args)
    elif args.command == "add-user":
        cmd_add_user(args)
    elif args.command == "clear-saves":
        cmd_clear_saves(args)
    elif args.command in ("reset-pin", "reset-password"):
        cmd_reset_pin(args)
    elif args.command == "delete-comment":
        cmd_delete_comment(args)
    elif args.command == "list-comments":
        cmd_list_comments(args)
    elif args.command == "clear-reports":
        cmd_clear_reports(args)
    elif args.command == "timeout":
        cmd_timeout(args)
    elif args.command == "end-timeout":
        args.minutes = 0
        cmd_timeout(args)
    elif args.command == "reset-unlocks":
        cmd_reset_unlocks(args)
    elif args.command == "list-users":
        cmd_list_users(args)


if __name__ == "__main__":
    main()
