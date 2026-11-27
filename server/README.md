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
   on the site with the password it prints:
   ```sh
   sudo -u clubescapade python3 /srv/club-escapade/site/server/app.py \
     --db /var/lib/club-escapade/club.db add-user YOURNAME --admin
   ```
   There's no sign-up on the site. You create every account with `add-user`
   (see below).

### Keep the database on a USB drive (recommended)

SD cards wear out under constant writes. Format a USB stick or SSD, mount it
at `/var/lib/club-escapade` via `/etc/fstab` **before step 4**, then run
`sudo chown clubescapade: /var/lib/club-escapade`.

## Day to day

Run these with `sudo -u clubescapade python3 /srv/club-escapade/site/server/app.py --db /var/lib/club-escapade/club.db` in front:

| Command | Does |
|---|---|
| `add-user NAME` | Creates an account and prints a random password to give the student. Add `--choose` to type one yourself, `--admin` for an admin |
| `list-users` | Shows every account |
| `make-admin NAME` / `remove-admin NAME` | Admins can delete anyone's comment |
| `ban NAME` / `unban NAME` | Banning logs them out and hides their comments and ratings |
| `list-comments` | Shows the 20 newest comments with their IDs and report counts. Add `--reported`, `--game ID`, `--user NAME` or `-n 50` to narrow or widen it |
| `delete-comment ID` | Deletes one comment |
| `reset-password NAME` | Gives them a new random password (like `k7mp-3xqa-9wdh`) and logs them out everywhere. Add `--choose` to type one yourself |
| `clear-reports ID` | Keeps a reported comment and drops its reports |
| `clear-saves NAME` | Deletes all of someone's game saves. Add `--game ID` for just one game |

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
checks new comments. `add-user` also warns you if a name has a blocked word.
Clean up older comments with
`delete-comment` or `ban`.

## Limits built in

| What | Limit |
|---|---|
| Usernames | 3–20 letters, numbers, `-` or `_`, case-insensitive |
| Passwords | 8–200 characters, stored as scrypt hashes |
| Sessions | 30 days, in an HttpOnly cookie |
| Failed log-ins | 10 per 15 minutes per IP address |
| Comments | 1,000 characters; 5 a minute and 50 a day per user |
| Rating changes | 30 a minute per user |
| Game saves | 512 KB per save, 10 MB per user in all |

Rate limits are kept in memory and reset when the server restarts.
