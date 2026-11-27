# Club Escapade server

Log-ins, comments and 1–5 star ratings for each game. The whole site needs a
log-in: anyone not logged in only sees `login.html`. One Python file
(`app.py`) using only the standard library, plus a SQLite database. Built
to run on a Raspberry Pi 2 Model B (32-bit), but it works on any Linux box.

- **Caddy** serves the site's files, handles HTTPS, and passes `/api/*` to the server.
  Before serving any file it asks the server whether the visitor is logged in
  (`forward_auth`), and sends them to the log-in page if not.
- **app.py** listens on `127.0.0.1:8080` and stores everything in one file,
  `/var/lib/club-escapade/club.db`.
- Without the server, for example on GitHub Pages, there's nothing to check
  log-ins, so **that copy of the site stays open to everyone**. Ratings and
  comments just don't appear there.

## Try it on your computer

```sh
python3 server/app.py serve --dev
```

Make yourself an account with `python3 server/app.py add-user YOURNAME`, then
open <http://localhost:8080>. `--dev` also serves the site's files (behind the
same log-in check) and lets log-in cookies work over plain `http`. The test database goes in `data/club.db`,
which git ignores.

## Set up the Pi

1. Flash **Raspberry Pi OS Lite (32-bit)** with Raspberry Pi Imager. Turn on
   SSH in its settings, plug the Pi into your router with Ethernet, and SSH in.

2. Install Python, Caddy and git:
   ```sh
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y python3 caddy git sqlite3
   ```

3. Get the site and create the user the server runs as:
   ```sh
   sudo git clone https://github.com/dponce-edu/johnPStinkyHQ.git /srv/club-escapade/site
   sudo useradd --system --no-create-home --shell /usr/sbin/nologin clubescapade
   ```

4. Start the server, and have it start at boot:
   ```sh
   sudo cp /srv/club-escapade/site/server/club-escapade.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now club-escapade
   ```

5. Point your domain at your home and open the ports:
   - At your domain registrar, add an **A record** pointing to your home's
     public IP. If your IP changes, use a dynamic DNS service.
   - On your router, **forward ports 80 and 443** to the Pi. Give the Pi a
     fixed local IP first.

6. Set up Caddy:
   ```sh
   sudo cp /srv/club-escapade/site/server/Caddyfile /etc/caddy/Caddyfile
   sudo nano /etc/caddy/Caddyfile        # replace clubescapade.example.com
   sudo systemctl reload caddy
   ```
   Visit `https://your-domain`. Caddy gets the certificate on first visit.

7. Create your own admin account, so you can delete any comment. Then log in
   on the site with the PIN it prints:
   ```sh
   sudo -u clubescapade python3 /srv/club-escapade/site/server/app.py \
     --db /var/lib/club-escapade/club.db add-user YOURNAME --admin --proper-name "Your Name"
   ```
   There's no sign-up on the site. Students join with an invite code you make
   (see **Accounts and invites** below).

### Keep the database on a USB drive (recommended)

SD cards wear out under constant writes. Format a USB stick or SSD, mount it
at `/var/lib/club-escapade` via `/etc/fstab` **before step 4**, then run
`sudo chown clubescapade: /var/lib/club-escapade`.

## Day to day

Run these with `sudo -u clubescapade python3 /srv/club-escapade/site/server/app.py --db /var/lib/club-escapade/club.db` in front:

| Command | Does |
|---|---|
| `invite USERNAME "Proper Name"` | Makes a student account and prints its invite code (see below). Add `--admin` for an admin |
| `list-invites` | Shows invite codes nobody has used yet |
| `set-proper-name USERNAME "Proper Name"` | Records or fixes someone's proper name |
| `add-user NAME` | Makes a ready-to-use account with a random 6-digit PIN, skipping the invite. Add `--proper-name "..."`, `--choose` to type the PIN, `--admin` for an admin |
| `list-users` | Shows every account with its proper name and screen name |
| `make-admin NAME` / `remove-admin NAME` | Admins can delete anyone's comment |
| `timeout NAME MINUTES` / `end-timeout NAME` | Logs them out and keeps them off the site for that long (up to 10080, a week) |
| `ban NAME` / `unban NAME` | Banning logs them out and hides their comments and ratings |
| `list-comments` | Shows the 20 newest comments with their IDs and report counts. Add `--reported`, `--game ID`, `--user NAME` or `-n 50` to narrow or widen it |
| `delete-comment ID` | Deletes one comment |
| `reset-pin NAME` | Gives them a new random PIN and logs them out everywhere. Add `--choose` to type one yourself |
| `clear-reports ID` | Keeps a reported comment and drops its reports |
| `clear-saves NAME` | Deletes all of someone's game saves. Add `--game ID` for just one game |

**Accounts and invites:** every account has three names.

- **Proper name:** their name as written in legal and formal contexts. You
  enter it, and only admins ever see it. The admin tools page refers to
  everyone by it.
- **Username:** you pick it, and they log in with it.
- **Screen name:** they pick it when joining, and it's what everyone else
  sees, e.g. on comments. It must be unique, passes the word filter, and
  can't be changed later.

To add a student, use "Invite a student" on the admin tools page, or
`invite USERNAME "Proper Name"` on the Pi. Either gives you a code like
`K7MP-3XQA`. The student opens the Join page (linked from the log-in page,
or `join.html?code=K7MP-3XQA`), enters the code, picks a screen name, and
picks a 6-digit PIN twice. Then they're logged in, and the code stops working.
Students can't reset their own PIN. Use `reset-pin USERNAME` and give them the
new one. Codes are 8 letters and numbers. Wrong guesses are limited to 50 per
15 minutes per IP address.

**Admin tools page:** admins land on it after logging in, and there's an
"Admin tools" link on the homepage (`admin.html`). It lists reported
comments, most-reported first, with buttons to delete one, dismiss its
reports, or time out its author. You can invite students and see the invites
nobody has used yet ("New code" replaces a lost one, and "Delete" removes the
account). There's a form to time out any student for 15 minutes, 1 hour,
1 day or 1 week, and a list of current timeouts with "End now". A timed-out student is logged out at
once. If they try to log in, they see when the timeout ends, in the Pi's time
zone (set it with `sudo raspi-config` → Localisation if the times look off).
Their comments stay up. Admins can't be timed out.

**Reports:** logged-in users can report anyone else's comment, once each. Reported
comments stay up until you act. Admins see a red "⚑ N reports" on them on the
site, and `list-comments --reported` lists them on the Pi. Then delete the
comment, ban its author, or `clear-reports` if it's fine.

**Update the site** after pushing changes to GitHub:
```sh
cd /srv/club-escapade/site && sudo git pull && sudo systemctl restart club-escapade
```

**Back up the database** (safe while running). Add a nightly cron job with `sudo crontab -e`:
```
0 4 * * * sqlite3 /var/lib/club-escapade/club.db ".backup /mnt/backup/club-$(date +\%F).db"
```
Keep the backups on a different drive than the database.

**Logs:** `journalctl -u club-escapade -f`

**Game saves** follow each student's account (`saves.js`). Opening a game
downloads their saves first. Playing uploads changes every 15 seconds and on
leaving the page. Logging out uploads what's left and wipes their saves from
that browser. If a different student logs in on a computer where someone forgot
to log out, the old saves are wiped first, so nobody plays on someone else's
progress. Saves made in a browser before this existed are adopted by the first
student to log in there. If two computers play the same game at once, the last
upload wins.

**Blocked words:** comments containing a word from
`server/blocked-words.txt` are turned away with a "please keep it clean"
message. Edit the list in the repo, push, and `git pull` on the Pi. The
server picks up the change without a restart. The notes at the top of the
file explain the `word`, `word*`, `*word*` and `=word` forms. The filter only
checks new comments and the screen names students pick. `add-user` also warns
you if a username has a blocked word.
Clean up older comments with
`delete-comment` or `ban`.

## Limits built in

| What | Limit |
|---|---|
| Usernames | 3–20 letters, numbers, `-` or `_`, case-insensitive |
| PINs | Exactly 6 digits, stored as scrypt hashes. To change the length, edit `PIN_LENGTH` in both `server/app.py` and `login.html` |
| Sessions | 30 days, in an HttpOnly cookie |
| Wrong PINs | 5 per 15 minutes per username, then that name is locked for the rest of the 15 minutes. 100 per 15 minutes per IP address, set high because a school usually shares one |
| Comments | 1,000 characters; 5 a minute and 50 a day per user |
| Rating changes | 30 a minute per user |
| Game saves | 512 KB per save, 10 MB per user in all |

Rate limits are kept in memory and reset when the server restarts. Restarting
also unlocks a student who's locked out by wrong PINs.

A 6-digit PIN is only safe because guesses are slow: at 5 tries per 15
minutes, guessing one would take years. Anyone can lock a
classmate's name for 15 minutes by guessing wrong 5 times. If that becomes a
problem, restart the server, and ban whoever is doing it.
