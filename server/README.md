# Club Escapade server

Accounts, comments and 1–5 star ratings for each game. One Python file
(`app.py`) using only the standard library, plus a SQLite database. Built
to run on a Raspberry Pi 2 Model B (32-bit), but it works on any Linux box.

- **Caddy** serves the site's files, handles HTTPS, and passes `/api/*` to the server.
- **app.py** listens on `127.0.0.1:8080` and stores everything in one file,
  `/var/lib/club-escapade/club.db`.
- Without the server, for example on GitHub Pages, the site still works.
  Ratings and comments just don't appear.

## Try it on your computer

```sh
python3 server/app.py serve --dev
```

Open <http://localhost:8080>. `--dev` also serves the site's files and lets
log-in cookies work over plain `http`. The test database goes in `data/club.db`,
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

7. Sign up on the site, then make yourself an admin so you can delete any comment:
   ```sh
   sudo -u clubescapade python3 /srv/club-escapade/site/server/app.py \
     --db /var/lib/club-escapade/club.db make-admin YOURNAME
   ```

### Keep the database on a USB drive (recommended)

SD cards wear out under constant writes. Format a USB stick or SSD, mount it
at `/var/lib/club-escapade` via `/etc/fstab` **before step 4**, then run
`sudo chown clubescapade: /var/lib/club-escapade`.

## Day to day

Run these with `sudo -u clubescapade python3 /srv/club-escapade/site/server/app.py --db /var/lib/club-escapade/club.db` in front:

| Command | Does |
|---|---|
| `list-users` | Shows every account |
| `make-admin NAME` / `remove-admin NAME` | Admins can delete anyone's comment |
| `ban NAME` / `unban NAME` | Banning logs them out and hides their comments and ratings |
| `delete-comment ID` | Deletes one comment |

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

## Limits built in

| What | Limit |
|---|---|
| Usernames | 3–20 letters, numbers, `-` or `_`, case-insensitive |
| Passwords | 8–200 characters, stored as scrypt hashes |
| Sessions | 30 days, in an HttpOnly cookie |
| New accounts | 5 per hour per IP address |
| Failed log-ins | 10 per 15 minutes per IP address |
| Comments | 1,000 characters; 5 a minute and 50 a day per user |
| Rating changes | 30 a minute per user |

Rate limits are kept in memory and reset when the server restarts.
