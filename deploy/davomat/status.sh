#!/usr/bin/env bash
# How Davomat is doing, read only (it changes nothing): the services, the site, the version, the
# certificate, the worker, the bot, the backups, the disk and the last errors. Run it as root from
# the checkout:
#   bash deploy/davomat/status.sh            (exit status 1 when something needs a look)
set -Euo pipefail
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case ${1:-} in -h | --help)
	sed -n '2,5p' "$0"
	exit 0
	;;
esac
need_docker
need_env
problems=0
problem() {
	warn "$*"
	problems=$((problems + 1))
}

url=$(site_url)
step "Davomat at $url (project $PROJECT, code $(app_version))"

step "Services"
for service in caddy backend worker beat bot backup db redis; do
	state=$(service_state "$service")
	case $state in
	healthy | running) ok "$(printf '%-8s %s' "$service" "$state")" ;;
	*) problem "$(printf '%-8s %s' "$service" "$state")" ;;
	esac
done

step "Site"
if health=$(site_get /health/ 2>/dev/null); then
	ok "$url/health/: $(printf '%s' "$health" | tr -d '\n' | cut -c1-140)"
else
	problem "$url/health/ doesn't answer from this server (the certificate, Caddy or the backend: see the logs below)."
fi
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
	"http://127.0.0.1:$(env_get HTTP_PORT 80)/api/v1/devices/hik/0000000000000000/" || true)
if [ "$code" = 404 ]; then
	ok "Terminal address (plain HTTP, port $(env_get HTTP_PORT 80)): answers"
else
	problem "Terminal address (plain HTTP, port $(env_get HTTP_PORT 80)): $code instead of 404"
fi
if [ "$(env_get CADDYFILE Caddyfile)" != Caddyfile.http ] && command -v openssl >/dev/null 2>&1; then
	domain=$(env_get DOMAIN)
	expiry=$(echo | timeout 10 openssl s_client -connect "127.0.0.1:$(env_get HTTPS_PORT 443)" \
		-servername "$domain" 2>/dev/null | openssl x509 -noout -enddate -issuer 2>/dev/null | tr '\n' ' ' || true)
	if [ -n "$expiry" ]; then
		ok "Certificate: $(printf '%s' "$expiry" | sed 's/notAfter=/until /; s/issuer=/from /')"
	else
		problem "No certificate for $domain yet (Caddy's log says why)."
	fi
fi

step "Worker and bot"
if [ "$(service_state worker)" = running ]; then
	if compose exec -T worker sh -c 'celery -A config inspect ping --timeout 10 -d "celery@$(hostname)"' \
		</dev/null >/dev/null 2>&1; then
		ok "worker answers"
	else
		problem "worker doesn't answer a ping (busy, or stuck: compose logs worker)"
	fi
fi
compose logs --no-color --no-log-prefix --tail 3 bot </dev/null 2>/dev/null | cut -c1-160 | sed 's/^/    bot: /'

step "Backups"
dir=$(backup_dir)
if [ -d "$dir" ]; then
	latest=$(find "$dir" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9]-*' 2>/dev/null | sort | tail -n 1)
	count=$(find "$dir" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9]-*' 2>/dev/null | wc -l)
	if [ -n "$latest" ]; then
		age_h=$((($(date +%s) - $(stat -c %Y "$latest")) / 3600))
		msg="$count in $dir, the newest $(basename "$latest") ($age_h h ago, $(du -sh "$latest" 2>/dev/null | cut -f1)); nightly at $(env_get BACKUP_TIME 02:30) $(env_get BACKUP_TZ Asia/Tashkent)"
		if [ "$age_h" -gt 30 ]; then problem "$msg: none in the last day"; else ok "$msg"; fi
	else
		problem "No backup in $dir yet (the first nightly one comes at $(env_get BACKUP_TIME 02:30); now: deploy/davomat/backup.sh)"
	fi
else
	problem "No backups folder ($dir) yet: deploy/davomat/backup.sh makes one."
fi

step "Disk and memory"
df -h "$ROOT" | awk 'NR == 2 { printf "    disk: %s free of %s (%s used)\n", $4, $2, $5 }'
used_pct=$(df -P "$ROOT" | awk 'NR == 2 { gsub("%", "", $5); print $5 }')
[ "${used_pct:-0}" -lt 90 ] || problem "The disk is ${used_pct}% full."
free -h 2>/dev/null | awk '/^Mem:/ { printf "    memory: %s available of %s\n", $7, $2 }'
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' 2>/dev/null |
	grep "^$PROJECT-" | sed "s/^$PROJECT-/    /" || true

step "Errors in the last hour"
errors=$(compose logs --no-color --since 1h backend worker beat bot </dev/null 2>&1 |
	grep -E 'Traceback|ERROR|CRITICAL' || true)
if [ -z "$errors" ]; then
	ok "none"
else
	info "$(printf '%s\n' "$errors" | wc -l) lines; the last ones:"
	printf '%s\n' "$errors" | tail -n 5 | cut -c1-200 | sed 's/^/    /'
fi

if [ "$problems" -gt 0 ]; then
	step "$problems thing(s) need a look (docs/davomat/en/TROUBLESHOOTING.md)"
	exit 1
fi
step "All good"
