# When something goes wrong

Start here, on the server, from the checkout (`/opt/davomat`):

```bash
bash deploy/davomat/status.sh
```

It changes nothing and shows the services, the site and its certificate, the terminals' address,
the worker and the bot, the backups, the disk and the last errors; it ends with what needs a look.
The commands below use `dc` for `docker compose -f docker-compose.davomat.yml`:

```bash
alias dc='docker compose -f docker-compose.davomat.yml'
dc ps                        # the services and their health
dc logs --tail 100 backend   # one service's log (caddy, backend, worker, beat, bot, db, backup)
dc logs -f backend           # follow it
```

## The site doesn't open

- **Right after installing, for a few minutes**: the first start sets up the database. `dc logs
  backend` shows `Applying …` lines; wait for `Listening at`.
- **Certificate errors / "connection refused" from outside**: Caddy gets the certificate from Let's
  Encrypt, which must reach the server on **ports 80 and 443 from the internet**. Check the
  firewall (`ufw status`), the provider's cloud firewall, and that the domain's DNS `A` record
  points at the server (`getent hosts <domain>`). `dc logs caddy` says what failed. After a fix,
  Caddy tries again by itself (or `dc restart caddy`).
- **Too many failed certificate attempts**: Let's Encrypt pauses a name for an hour after five
  failures. Fix the cause, wait, `dc restart caddy`. `<server IP>.nip.io` always resolves to the
  server and is a good test.
- **"Bad Request (400)"**: the address in the browser isn't the one in `.env`. Davomat answers only
  to `DOMAIN` (`DJANGO_ALLOWED_HOSTS`). After changing them: `bash deploy/davomat/update.sh --here`.
- **A service keeps restarting** (`dc ps` says `Restarting`): its log (`dc logs --tail 100
  <service>`) has the reason; most often a wrong or missing value in `.env`.

## The terminal can't reach the server

The terminal's card stays at "Waiting for the terminal's first event".

1. **From a computer on the terminal's network**, open (or `curl`) the terminal's address from
   the setup page, over HTTP: `http://<server>/api/v1/devices/hik/<code>/`. It must answer
   `{"statusCode": 200, "statusString": "OK", …}`.
   - It answers: the network is fine; the terminal's settings are not (step 2).
   - 404: the code is wrong (copy the URL again from the setup page; a new code makes the old one
     stop working).
   - No answer: that network can't reach the server on port 80 (the office firewall, or the
     server's), or the server's address is wrong.
2. **On the terminal** (HTTP Listening): the host exactly as on the setup page, the URL with its
   leading and trailing `/`, port `80`, protocol `HTTP`, saved. The terminal needs a **gateway**
   in its own network settings (Configuration › Network › Basic Settings) to reach anything
   outside its network, and a DNS server if the host is a name: an IP address avoids DNS.
3. `dc logs --tail 50 backend | grep devices` shows every request that arrived from a terminal.

## HTTPS on old firmware

Many terminals can't do HTTPS with today's certificates (the DS-K1T341AMF with V3.2.x firmware
never connects, whatever the setting). Use **HTTP on port 80**: Davomat never redirects the
terminals' address to HTTPS and accepts the events as they are. The secret code in the URL is what
protects it; if that address leaks, give the terminal a new code (its page, one click) and type
the new URL in.

## The history backlog

"The terminal is sending its old history first" for hours after connecting a terminal is
normal: it uploads every scan it ever stored, oldest first, at its own pace (about one or two a
second; 40 000 old scans take a working day). Davomat skips them (no arrivals, no messages) and
counts them on the terminal's card. Live scans come right after. Don't restart or reset the
terminal: it starts over, and a factory reset deletes the enrolled faces.

## The clock

- **"The terminal's clock is N min behind/ahead"**: set the terminal's time zone (GMT+05:00 for
  Tashkent) and NTP (`pool.ntp.org`) under Configuration › System › Time Settings. A terminal
  with a factory time zone (often GMT+08:00) or a clock set by hand is the usual cause.
- **"The clock is far behind: its live scans look old and are skipped"**: the terminal's date is
  wrong (days or more): set it, as above. Scans are kept again at once.
- **The server's clock**: `timedatectl` should say `System clock synchronized: yes`; if not:
  `timedatectl set-ntp true`.

## Scans that don't count

- **"Not linked"**: the number isn't anyone's. With new employees created from unknown numbers
  (the default) this only happens for numbers set aside; otherwise link it on Face ID › People.
- **"Repeat"**: a second scan within a few minutes of the last one; nothing changes. Normal.
- **An employee who left**: their scans are logged but don't count.

## Telegram

- **Settings › Telegram says the token is invalid**: it was revoked or mistyped: BotFather ›
  `/mybots` › the bot › API Token, paste it again.
- **The bot doesn't answer**: `dc logs --tail 50 bot`. "No Telegram bot token yet": paste one.
  "Conflict: terminated by other getUpdates request": another program uses the same token (an
  old server, a test): stop it, or revoke the token in BotFather and paste the new one. The server
  must reach `api.telegram.org` over HTTPS (outbound).
- **Someone gets no messages**: they must have opened their link and pressed Start, and not have
  blocked the bot; their Telegram is shown as linked on their page.

## The setup page asks for a code

It is the setup code the installer printed at the end. Lost it? It is also in the settings, on
the server:

```bash
grep DAVOMAT_SETUP_TOKEN /opt/davomat/.env
```

## A lost password

An administrator sets a new one in Settings › Users and roles. When nobody can sign in, on the
server:

```bash
cd /opt/davomat
docker compose -f docker-compose.davomat.yml exec backend python manage.py changepassword <username>
```

The usernames that can sign in:

```bash
docker compose -f docker-compose.davomat.yml exec backend python manage.py shell -c \
  "from django.contrib.auth import get_user_model as U; print([u.username for u in U().objects.filter(is_active=True) if u.has_usable_password()])"
```

Five wrong passwords lock that username for 15 minutes from that computer: wait them out.

## Disk and memory

- `df -h` and `docker system df`: old images go with `docker image prune -f`.
- `du -sh backups`: backups are kept 14 days (`BACKUP_KEEP_DAYS` in `.env`); copy them off and
  delete what you don't need.
- Scan photos are deleted after the days set in Face ID › Settings.
- With less than 4 GB of memory, building can fail: add swap
  (`fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`), or
  use a prebuilt image (INSTALL.md, section 8).

## An update went wrong

`update.sh` prints the way back when the new version doesn't start. In short:

```bash
git -C /opt/davomat checkout <the previous commit>     # or unpack the previous release
bash deploy/davomat/update.sh --here --no-backup
bash deploy/davomat/restore.sh backups/<date>_<time>-pre-update   # only if the data must go back too
```

## Starting over

To wipe everything (all data, irreversibly), keeping `.env`:

```bash
docker compose -f docker-compose.davomat.yml down -v
bash deploy/davomat/install.sh
```

## Asking for help

Send the output of `bash deploy/davomat/status.sh` and the last lines of the log of the service
in trouble (`dc logs --tail 200 <service>`). Never send `.env`: it holds the keys.
