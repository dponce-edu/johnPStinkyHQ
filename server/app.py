#!/usr/bin/env python3
"""Club Escapade accounts, comments and ratings server.

Standard library only (Python 3.9+), so it runs on a 32-bit Raspberry Pi 2
with nothing to install beyond python3. Data lives in one SQLite file.

In production Caddy serves the site's files and HTTPS, and passes /api/*
to this server on 127.0.0.1:8080. See server/README.md.

    python3 server/app.py serve --dev      # local testing: site + API on :8080
    python3 server/app.py make-admin NAME  # let NAME delete any comment
    python3 server/app.py ban NAME         # block NAME and hide their posts
    python3 server/app.py --help           # everything else
"""

import argparse
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
from urllib.parse import unquote, urlsplit

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
    ("POST", r"/api/signup", "signup"),
    ("POST", r"/api/login", "login"),
    ("POST", r"/api/logout", "logout"),
    ("GET", r"/api/ratings", "all_ratings"),
    ("GET", r"/api/games/" + GAME_ID, "game"),
    ("POST", r"/api/games/" + GAME_ID + r"/comments", "add_comment"),
    ("PUT", r"/api/games/" + GAME_ID + r"/rating", "rate"),
    ("DELETE", r"/api/comments/(\d+)", "delete_comment"),
]

# Never served by --dev, even though they sit in the site folder.
PRIVATE_PREFIXES = ("/server", "/data", "/.git", "/.gitignore")


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
        lowered = "/" + posixpath.normpath(unquote(path)).lower().lstrip("/")
        if not CONFIG["dev"] or method not in ("GET", "HEAD") or any(
                lowered == p or lowered.startswith(p + "/") for p in PRIVATE_PREFIXES):
            self.send_error(404)
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

    def api_signup(self, con):
        data = self.json_body()
        name = data.get("username")
        password = data.get("password")
        need(isinstance(name, str) and USERNAME_RE.fullmatch(name), 400,
             "Usernames are 3-20 letters, numbers, - or _.")
        need(isinstance(password, str) and 8 <= len(password) <= 200, 400,
             "Passwords need at least 8 characters.")
        need(LIMITS.take("signup:" + self.client_ip(), 5, 3600), 429,
             "Too many new accounts from here. Try again in an hour.")
        exists = con.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone()
        need(exists is None, 409, "That username is taken.")
        try:
            cur = con.execute(
                "INSERT INTO users (username, password, created) VALUES (?, ?, ?)",
                (name, hash_password(password), int(time.time())))
        except sqlite3.IntegrityError:
            raise ApiError(409, "That username is taken.")
        self.start_session(con, cur.lastrowid)
        user = con.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return 201, {"user": public_user(user)}

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
        user = self.current_user(con)
        rows = con.execute(
            "SELECT c.id, c.body, c.created, c.user_id, u.username "
            "FROM comments c JOIN users u ON u.id = c.user_id "
            "WHERE c.game = ? AND u.banned = 0 ORDER BY c.id DESC LIMIT 200",
            (game,)).fetchall()
        comments = [{
            "id": r["id"],
            "user": r["username"],
            "body": r["body"],
            "created": r["created"],
            "canDelete": bool(user and (user["id"] == r["user_id"] or user["is_admin"])),
        } for r in rows]
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

    def api_all_ratings(self, con):
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


def cmd_delete_comment(args):
    init_db()
    con = connect()
    cur = con.execute("DELETE FROM comments WHERE id = ?", (args.id,))
    con.commit()
    print("Deleted comment %d." % args.id if cur.rowcount else "No comment %d." % args.id)


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
    elif args.command == "delete-comment":
        cmd_delete_comment(args)
    elif args.command == "list-users":
        cmd_list_users(args)


if __name__ == "__main__":
    main()
