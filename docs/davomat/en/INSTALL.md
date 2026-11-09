# Installing Davomat

Davomat is Face ID attendance as an app of its own: Hikvision face terminals at the doors, the
arrivals live in the browser with each scan's photo, schedules, lateness, timesheets, reports and
a Telegram bot. One server runs one organization (with as many locations as it has).

This guide is for whoever sets up the server. The person who then runs the organization reads
[ADMIN.md](ADMIN.md); when something goes wrong, [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## 1. What you need

| | |
|---|---|
| Server | Ubuntu 22.04 or 24.04, with root access over SSH (any VPS or a computer in the office) |
| Size | 2 vCPU, 4 GB of memory, 40 GB of disk (a few hundred employees; photos and backups grow) |
| Ports | 80 and 443 open to the internet (or to the local network, see section 7) |
| Address | a domain name whose DNS `A` record points at the server, e.g. `davomat.example.uz`. Without one, `<server IP>.nip.io` works (e.g. `203.0.113.10.nip.io`), with a real HTTPS certificate |
| Terminals | Hikvision face recognition terminals (MinMoe: DS-K1T341AMF, DS-K1T341, DS-K1T342, DS-K1T343, DS-K1T671, DS-K1T804…) whose network can reach the server on port 80 |
| Telegram | optional: a bot made with @BotFather (ADMIN.md, section 7) |

Docker is installed by the installer when it's missing. Nothing else needs installing by hand.

**Cloud firewalls.** Some providers (AWS, Google Cloud, Hetzner Cloud, Oracle…) have a firewall
of their own in front of the server: open TCP 80, TCP 443 and UDP 443 there too.

## 2. Put the code on the server

Either clone the repository:

```bash
git clone <repository URL> /opt/davomat
```

or copy a release made on another computer and unpack it:

```bash
# on the computer with the code: a release of the commit to install
git archive --format=tar.gz --prefix=davomat/ -o davomat.tar.gz HEAD
scp davomat.tar.gz root@<server>:/root/

# on the server
mkdir -p /opt/davomat
tar -xzf /root/davomat.tar.gz -C /opt/davomat --strip-components=1
```

`/opt/davomat` is only a suggestion: any folder works, and everything below runs from it.

## 3. Run the installer

The build takes 5 to 15 minutes. Run the installer inside `tmux` (or `screen`), so a dropped SSH
connection doesn't stop it:

```bash
cd /opt/davomat
tmux new -s davomat          # apt-get install tmux if it's missing
bash deploy/davomat/install.sh
```

It asks two things:

1. **Where people will open Davomat**: on the internet (the default) or only on the local network.
2. **The domain name**: press Enter for `<server IP>.nip.io`, or type your domain.

Then it does the rest by itself:

- checks the server (memory, disk, the clock) and installs Docker with Docker's official script
  (after asking) when it's missing;
- writes the settings to `/opt/davomat/.env` (mode 600) with freshly made keys;
- opens ports 80 and 443 in `ufw` when the firewall is on (after asking);
- builds the image, starts everything and waits until the site answers over HTTPS (Caddy gets the
  certificate from Let's Encrypt by itself);
- prints the address to open, and where the logs and backups are.

```
==> Davomat is running
    Open https://203.0.113.10.nip.io/ in a browser to set up your organization.
    Face ID terminals post to 203.0.113.10 over HTTP, port 80: Face ID › Add a terminal shows the exact values.
```

Running the installer again is safe: it keeps the existing `.env` (it never overwrites it) and
only starts what isn't running. Its log is in `/var/log/davomat/install-<date>.log`.

### Without questions

```bash
bash deploy/davomat/install.sh --yes --domain davomat.example.uz
```

and, to create the organization at the same time instead of in the browser:

```bash
bash deploy/davomat/install.sh --yes --domain davomat.example.uz \
  --organization "Namuna MChJ" --admin-username admin --admin-password '<a strong password>' \
  --timezone Asia/Tashkent --language uz
```

| Option | What it does |
|---|---|
| `--domain NAME` | the site's name (default: `<public IP>.nip.io`) |
| `--lan [ADDRESS]` | a server only the local network reaches (section 7) |
| `--http-only` | plain HTTP, for a trial on the computer itself at `http://localhost` |
| `--device-host HOST` | the address terminals post to (default: the server's public IP) |
| `--http-port N`, `--https-port N` | other ports than 80 and 443 (terminals and certificates need 80) |
| `--organization`, `--admin-username`, `--admin-password`, `--admin-first-name`, `--admin-last-name`, `--timezone`, `--language` | create the organization now (`manage.py davomat_init`) |
| `--image FILE` | use a prebuilt image instead of building one (section 8) |
| `--no-start` | write `.env` and stop |
| `-y`, `--yes` | no questions: the defaults, and Docker installed when missing |

## 4. The first run

Open the address in a browser. A fresh Davomat opens its **setup page**:

1. **Organization**: its name (shown on the sign-in page, in reports and in Telegram), the time
   zone (arrivals and lateness follow it) and the language.
2. **Your account**: the administrator's name, username and password (at least 8 characters,
   not a common word, not only digits).
3. **Ready**: you are signed in. Add the first terminal (ADMIN.md, section 4).

The setup page works once: afterwards the address opens the sign-in page. **If the installer
printed a setup code**, the page asks for it, so only someone who saw the installer can set
Davomat up. Without one, **do it right after the installer finishes**: until then, whoever opens
the address first becomes the organization's owner. To leave no such moment at all, create the
organization with the installer's `--organization` options instead (section 3).

## 5. What runs

Everything runs in Docker Compose (`docker-compose.davomat.yml`, project `davomat`):

| Service | What it does |
|---|---|
| `caddy` | HTTPS and its certificate; plain HTTP for the terminals; logos and employee photos |
| `backend` | Davomat itself (Django and gunicorn): the web app, the API, the terminals' events. Applies database migrations when it starts |
| `worker` | background jobs: Telegram messages, exports, reports |
| `beat` | the schedule: the daily summary, lateness, clean-ups |
| `bot` | the organization's Telegram bot (it waits until a token is pasted in Settings › Telegram) |
| `db`, `redis` | PostgreSQL 18 and Redis |
| `backup` | the nightly backup (section 6) |

Where things are:

| | |
|---|---|
| Settings | `/opt/davomat/.env` (mode 600). **Keep a copy somewhere safe**: the keys in it can't be made again |
| Backups | `/opt/davomat/backups/` |
| Installer and update logs | `/var/log/davomat/` |
| Data | Docker volumes `davomat_pgdata` (database), `davomat_media` (logos, employee photos), `davomat_private_media` (scan snapshots, exports), `davomat_caddy_data` (certificates) |

Day-to-day commands, from `/opt/davomat`:

```bash
bash deploy/davomat/status.sh                     # how everything is doing (read only)
docker compose -f docker-compose.davomat.yml ps   # the services
docker compose -f docker-compose.davomat.yml logs -f backend     # a service's log
docker compose -f docker-compose.davomat.yml exec backend python manage.py <command>
```

## 6. Updates and backups

### Updating

```bash
cd /opt/davomat
bash deploy/davomat/update.sh                          # a git checkout: git pull
bash deploy/davomat/update.sh --from /root/davomat.tar.gz   # a release tarball
```

It takes a backup first, gets the new code (the `.env`, the backups and the logs are never
touched), builds the new image, restarts, runs the migrations, restarts Caddy when its file
changed, and waits until the site answers. If the new version doesn't start, it prints how to go
back: the previous code, `update.sh --here --no-backup`, and `restore.sh` with the backup it took.
`update.sh --here` rebuilds and restarts what is there (after editing `.env`, for example).

### Backups

Every night at 02:30 (Tashkent time; `BACKUP_TIME` and `BACKUP_TZ` in `.env`) the `backup`
service writes a folder `backups/<date>_<time>-nightly/` with:

- `db.sql.gz`: the whole database;
- `media.tgz`: logos and employee photos;
- `private_media.tgz`: scan snapshots and exports;
- `info.txt`: when and from what.

The last 14 days are kept (`BACKUP_KEEP_DAYS`). Only root can read them: they hold everyone's
names, photos and attendance.

```bash
bash deploy/davomat/backup.sh            # a backup now (backups/<date>_<time>-manual/)
scp -r root@<server>:/opt/davomat/backups/<folder> .    # copy one off the server
```

**Copy the backups off the server regularly** (and keep them encrypted): a backup on the same
disk doesn't survive the disk.

### Restoring

```bash
bash deploy/davomat/restore.sh backups/2026-11-10_023000-nightly
```

It asks you to type `restore`, takes a safety backup of the present state, stops Davomat, puts
back the database and the files of that backup, and starts everything again. What happened
after that backup is lost.

### Moving to a new server

1. On the old server: `bash deploy/davomat/backup.sh`, then copy the backup folder **and the
   `.env`** to the new server.
2. On the new server: put the code in `/opt/davomat` (section 2), copy the old `.env` to
   `/opt/davomat/.env` (`chmod 600`), and change `DOMAIN`, `DJANGO_ALLOWED_HOSTS`,
   `DASHBOARD_URL` and `PUBLIC_DEVICE_HOST` if the address changes.
3. `bash deploy/davomat/install.sh` (it keeps that `.env`), then
   `bash deploy/davomat/restore.sh <the backup folder>`.
4. Point the terminals at the new address if it changed (ADMIN.md, section 4).

The keys in `.env` must be the ones the backup was made with. Without them the Telegram bot's
token can't be read and has to be pasted again.

## 7. A server on the local network

When the server sits in the office and nothing on the internet reaches it, there is no public
certificate to get. Install it in LAN mode:

```bash
bash deploy/davomat/install.sh --lan                # the server's LAN address, detected
bash deploy/davomat/install.sh --lan 192.168.1.10   # or given
```

Davomat then answers at `https://192.168.1.10/` with a certificate of its own. Browsers warn once
("not private"): choose Advanced › Continue. To get rid of the warning, install Caddy's root
certificate on the office computers:

```bash
docker compose -f docker-compose.davomat.yml exec caddy cat /data/caddy/pki/authorities/local/root.crt > davomat-root.crt
```

(Windows: double-click the file › Install Certificate › Local Machine › Trusted Root
Certification Authorities.) The terminals post over plain HTTP as usual. Give the server a fixed
address in the router (a DHCP reservation), or the terminals lose it.

`--http-only` serves everything over plain HTTP. It is only for a trial on the computer itself
at `http://localhost`: browsers keep the sign-in over plain HTTP only for localhost.

## 8. A prebuilt image

Building needs about 2 GB of memory and the internet (Docker Hub, npm, PyPI). On a small or
offline server, build the image on another computer and copy it:

```bash
# on the build computer, from the checkout of the same commit
docker build -t davomat:latest .
docker save davomat:latest | gzip > davomat-image.tar.gz
scp davomat-image.tar.gz root@<server>:/root/

# on the server
bash deploy/davomat/install.sh --image /root/davomat-image.tar.gz
bash deploy/davomat/update.sh --from /root/davomat.tar.gz --image /root/davomat-image.tar.gz   # later updates
```

## 9. Security

- `.env` holds the keys: mode 600, root only. Never put it in git or in a chat.
- Only ports 80 and 443 need to be open (and SSH). PostgreSQL and Redis are never reachable from
  outside.
- Use SSH keys rather than passwords for root, and keep Ubuntu updated
  (`apt-get update && apt-get upgrade`, or `unattended-upgrades`).
- Each terminal posts to an address with its own secret code: treat that address like a
  password (a new code is one click on the terminal's page).
- Once HTTPS works, `DJANGO_SECURE_HSTS_SECONDS=31536000` in `.env` and
  `bash deploy/davomat/update.sh --here` make browsers insist on HTTPS.

## 10. Trying it on one computer

`deploy/davomat/demo.sh` runs the whole stack on a laptop or a desktop with Docker (no root), as
a project of its own with its own data, at `http://localhost:18080`, filled with an example
organization (sign in as `admin`, password `Namuna-2026`):

```bash
bash deploy/davomat/demo.sh up        # build the image if needed, start, add the example data
bash deploy/davomat/demo.sh down      # stop it (the data stays; up starts it again)
bash deploy/davomat/demo.sh wipe      # stop it and delete its data
```

`up --no-seed` starts without the example data (the setup page opens), `up --lan` lets a terminal
on the same network post to it (port 18080 on the terminal), `rebuild` takes new code, `seed`
replaces the example data. It never touches a real installation on the same computer.
