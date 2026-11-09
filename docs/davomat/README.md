# Davomat

Face ID attendance as an app of its own: an edition of Daybook (`EDITION=davomat`) on its own
server, with its own database, its own sign-in and its own Telegram bot
([docs/DAVOMAT.md](../DAVOMAT.md) is the plan).

| | O‘zbekcha | Русский | English |
|---|---|---|---|
| Installing the server | [O‘rnatish](uz/INSTALL.md) | [Установка](ru/INSTALL.md) | [Installing](en/INSTALL.md) |
| Running the organization | [Boshqaruv](uz/ADMIN.md) | [Администрирование](ru/ADMIN.md) | [Running Davomat](en/ADMIN.md) |
| When something goes wrong | [Muammolar](uz/TROUBLESHOOTING.md) | [Неполадки](ru/TROUBLESHOOTING.md) | [Troubleshooting](en/TROUBLESHOOTING.md) |

In short, on a fresh Ubuntu 22.04 or 24.04 server, as root:

```bash
git clone <repository URL> /opt/davomat     # or unpack a release there
cd /opt/davomat
bash deploy/davomat/install.sh
```

then open the address it prints and set the organization up.

The files: `docker-compose.davomat.yml` (the stack), `deploy/davomat/` (its Caddyfile, the
settings template `.env.example`, `install.sh`, `update.sh`, `backup.sh`, `restore.sh`,
`status.sh`, and `smoke.sh`, the end-to-end test of the whole stack on one computer).
