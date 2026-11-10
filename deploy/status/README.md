# Holat · Status (uptime monitor)

A small uptime monitor and public status page for Daybook and Davomat. It runs on vps8 as its own
compose project, `daybook-status`. It is Python 3.12 stdlib only, with no external dependencies.

- Every 60 s (`config.json`) it checks the health, dashboard and Face ID terminal routes (404 = reachable),
  plus TLS days left (a warning under 14 days). The timeout is 10 s.
- A check counts as **down** only after 2 failures in a row. The incident starts at the first failure.
- Results go into SQLite in the `daybook-status-data` volume. Samples are kept for 95 days and incidents forever.
- Uptime is shown for 24h / 7d / 30d / 90d, with a bar of daily uptime for the last 90 days and recent incidents.
- Telegram alerts use Bot API `sendMessage` only. They go out on down and on recovery, with the duration, Uzbek then English.
  If `STATUS_BOT_TOKEN` / `STATUS_CHAT_IDS` are empty, alerts are only logged.
- The page is at `/` (`?lang=en` for English) and the data at `/api/status.json`. `/healthz` is for Docker.

## Add a check

Edit `config.json` (each check needs a unique `id`):
`{"id": "x", "name": "...", "url": "...", "expect_status": 200, "expect_json": {"status": "ok"}}`
or `{"id": "x-tls", "name": "TLS", "type": "tls", "host": "example.com"}`. Then run `install.sh` again.

## Deploy

```sh
deploy/status/install.sh          # rsync to vps8:/root/daybook_status, then docker compose up -d --build
```

The first run creates `/root/daybook_status/.env` from `.env.example`, and later runs keep it. Put the bot
token and chat ids there, then run `docker compose up -d` in that folder. Only `127.0.0.1:18095` is published.
Nothing else on vps8 is touched: the project has its own network (`daybook-status`) and volume.

## Public URL (to be added by the owner, not done by install.sh)

Add this block to vps8's existing Caddyfile, then reload that Caddy:

```
status.169.58.114.63.nip.io {
	encode gzip
	reverse_proxy 127.0.0.1:18095
}
```

If that Caddy runs in Docker without host networking, `127.0.0.1` there is the Caddy container itself.
In that case, either attach Caddy to the `daybook-status` network and use `reverse_proxy daybook-status-status-1:8080`,
or use the host's docker bridge address (`172.17.0.1:18095`) and publish the port on that address instead.

## Test

```sh
uv run pytest deploy/status
cd deploy/status && docker compose -p daybook-status-local up -d --build   # http://127.0.0.1:18095/
```
