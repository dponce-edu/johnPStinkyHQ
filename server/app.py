#!/usr/bin/env python3
"""Club Escapade accounts, comments and ratings server.

Standard library only (Python 3.9+), so it runs on a 32-bit Raspberry Pi 2
with nothing to install beyond python3. Data lives in one SQLite file.

In production Caddy serves the site's files and HTTPS, and passes /api/*
to this server on 127.0.0.1:8080. See server/README.md.

    python3 server/app.py serve --dev      # local testing: site + API on :8080
    python3 server/app.py add-user NAME    # create an account, prints its password
    python3 server/app.py make-admin NAME  # let NAME delete any comment
    python3 server/app.py ban NAME         # block NAME and hide their posts
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
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{3,20}")
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
    banned    INTEGER NOT NULL DEFAULT 0
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
    con.commit()
    con.close()


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

_games = {"mtime": None, "ids": frozenset()}
_games_lock = threading.Lock()


def game_ids():
    """Game ids from games.js, re-read whenever the file changes."""
    path = os.path.join(ROOT, "games.js")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _games["ids"]
    with _games_lock:
        if mtime != _games["mtime"]:
            with open(path, encoding="utf-8") as f:
                ids = re.findall(r'\bid:\s*"([a-z0-9-]+)"', f.read())
            _games["ids"] = frozenset(ids)
            _games["mtime"] = mtime
        return _games["ids"]


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
]

# Never served by --dev, even though they sit in the site folder.
PRIVATE_PREFIXES = ("/server", "/data", "/.git", "/.gitignore")

# The only files anyone can load without logging in: the log-in page and what
# it needs. In production Caddy asks /api/auth-check about every request.
PUBLIC_PATHS = ("/login.html", "/styles.css", "/background.jpg")


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
        # Same rule Caddy applies in production with forward_auth.
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
        if method == "HEAD":
            super().do_HEAD()
        else:
            super().do_GET()

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

    def json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        need(0 <= length <= MAX_BODY, 413, "Request too large.")
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
            "WHERE s.token_hash = ? AND s.expires > ? AND u.banned = 0",
            (token_hash(token), int(time.time()))).fetchone()

    def require_user(self, con, message):
        user = self.current_user(con)
        need(user is not None, 401, message)
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
        if clean_path(urlsplit(uri).path).lower() in PUBLIC_PATHS:
            return 200, {"ok": True}
        if self.current_user(con):
            return 200, {"ok": True}
        self.extra_headers.append(("Location", login_redirect(uri)))
        return 302, {"error": "Log in first."}

    def api_login(self, con):
        data = self.json_body()
        name = data.get("username")
        password = data.get("password")
        need(isinstance(name, str) and isinstance(password, str) and len(password) <= 200,
             400, "Enter a username and password.")
        fail_key = "loginfail:" + self.client_ip()
        need(LIMITS.allowed(fail_key, 10, 900), 429,
             "Too many failed log-ins. Wait 15 minutes and try again.")
        user = con.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        ok = check_password(password, user["password"] if user else DUMMY_HASH)
        if not (user and ok):
            LIMITS.add(fail_key)
            raise ApiError(401, "Wrong username or password.")
        need(not user["banned"], 403, "This account has been banned.")
        self.start_session(con, user["id"])
        return 200, {"user": public_user(user)}

    def api_logout(self, con):
        token = self.session_token()
        if token:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        self.set_cookie("", 0)
        return 200, {"user": None}

    # -- API: games

    def check_game(self, game):
        need(game in game_ids(), 404, "No such game.")

    def api_game(self, con, game):
        self.check_game(game)
        user = self.require_user(con, "Log in first.")
        rows = con.execute(
            "SELECT c.id, c.body, c.created, c.user_id, u.username, "
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
                "user": r["username"],
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
        self.check_game(game)
        user = self.require_user(con, "Log in to comment.")
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
        return 201, {"comment": {"id": cur.lastrowid, "user": user["username"],
                                 "body": body, "created": now, "canDelete": True}}

    def api_rate(self, con, game):
        self.check_game(game)
        user = self.require_user(con, "Log in to rate games.")
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

    def api_all_ratings(self, con):
        self.require_user(con, "Log in first.")
        rows = con.execute(
            "SELECT r.game, AVG(r.stars) AS avg, COUNT(*) AS count "
            "FROM ratings r JOIN users u ON u.id = r.user_id "
            "WHERE u.banned = 0 GROUP BY r.game").fetchall()
        known = game_ids()
        return 200, {"ratings": {r["game"]: {"avg": round(r["avg"], 2), "count": r["count"]}
                                 for r in rows if r["game"] in known}}

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.client_ip(), fmt % args))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row):
    if row is None:
        return None
    return {"name": row["username"], "admin": bool(row["is_admin"])}


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


# No 0/O, 1/l/I: easy to read off a screen and type on a Chromebook.
TEMP_PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"


def pick_password(args, name):
    """--choose: type it twice. Otherwise a random one like k7mp-3xqa-9wdh."""
    if not args.choose:
        return "-".join("".join(secrets.choice(TEMP_PASSWORD_CHARS) for _ in range(4))
                        for _ in range(3))
    password = getpass.getpass("New password for %s: " % name)
    if not 8 <= len(password) <= 200:
        sys.exit("Passwords need 8-200 characters. Nothing changed.")
    if getpass.getpass("Type it again: ") != password:
        sys.exit("Those didn't match. Nothing changed.")
    return password


def cmd_add_user(args):
    init_db()
    con = connect()
    name = args.username
    if not USERNAME_RE.fullmatch(name):
        sys.exit("Usernames are 3-20 letters, numbers, - or _.")
    if con.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone():
        sys.exit("There's already a user called %r." % name)
    if has_blocked_word(name) and not args.force:
        sys.exit("%r has a word from blocked-words.txt. Add --force to use it anyway." % name)
    password = pick_password(args, name)
    con.execute("INSERT INTO users (username, password, created, is_admin) VALUES (?, ?, ?, ?)",
                (name, hash_password(password), int(time.time()), 1 if args.admin else 0))
    con.commit()
    kind = "Admin" if args.admin else "User"
    if args.choose:
        print("%s %s added." % (kind, name))
    else:
        print("%s %s added. Password:  %s" % (kind, name, password))


def cmd_reset_password(args):
    init_db()
    con = connect()
    user = find_user(con, args.username)
    password = pick_password(args, user["username"])
    con.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), user["id"]))
    con.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    con.commit()
    if args.choose:
        print("Password for %s changed. They've been logged out everywhere." % user["username"])
    else:
        print("New password for %s:  %s" % (user["username"], password))
        print("They've been logged out everywhere. Give it to them in person.")


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
    sql = ("SELECT c.id, c.game, c.body, c.created, u.username, u.banned, "
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
            r["game"][:20], r["username"],
            "[%d report%s] " % (r["reports"], "" if r["reports"] == 1 else "s") if r["reports"] else "",
            "(banned) " if r["banned"] else "", body))


def cmd_clear_reports(args):
    init_db()
    con = connect()
    cur = con.execute("DELETE FROM reports WHERE comment_id = ?", (args.id,))
    con.commit()
    print("Cleared %d report%s on comment %d." % (cur.rowcount, "" if cur.rowcount == 1 else "s", args.id))


def cmd_list_users(args):
    init_db()
    con = connect()
    for u in con.execute("SELECT * FROM users ORDER BY id"):
        flags = [f for f, on in (("admin", u["is_admin"]), ("banned", u["banned"])) if on]
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
                       ("unban", "lift a ban")):
        sub.add_parser(name, help=text).add_argument("username")
    sub.add_parser("delete-comment", help="delete one comment by id").add_argument("id", type=int)
    au = sub.add_parser("add-user", help="create an account (prints a random password)")
    au.add_argument("username")
    au.add_argument("--choose", action="store_true",
                    help="type the password yourself instead of getting a random one")
    au.add_argument("--admin", action="store_true", help="make the account an admin")
    au.add_argument("--force", action="store_true", help="allow a name the word filter blocks")
    rp = sub.add_parser("reset-password", help="give a user a new password and log them out")
    rp.add_argument("username")
    rp.add_argument("--choose", action="store_true",
                    help="type the new password yourself instead of getting a random one")
    lc = sub.add_parser("list-comments", help="show recent comments with their ids")
    lc.add_argument("--game", help="only this game id, e.g. red-ball")
    lc.add_argument("--user", help="only this username")
    lc.add_argument("-n", "--limit", type=int, default=20, help="how many (default 20)")
    lc.add_argument("--reported", action="store_true", help="only comments someone reported")
    sub.add_parser("clear-reports", help="keep a reported comment and drop its reports"
                   ).add_argument("id", type=int)
    sub.add_parser("list-users", help="show every account")

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
    elif args.command == "add-user":
        cmd_add_user(args)
    elif args.command == "reset-password":
        cmd_reset_password(args)
    elif args.command == "delete-comment":
        cmd_delete_comment(args)
    elif args.command == "list-comments":
        cmd_list_comments(args)
    elif args.command == "clear-reports":
        cmd_clear_reports(args)
    elif args.command == "list-users":
        cmd_list_users(args)


if __name__ == "__main__":
    main()
