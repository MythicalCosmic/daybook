#!/usr/bin/env bash
# The whole Davomat stack, end to end, on this computer (needs Docker, curl and python3; no root):
#   1. install.sh writes the settings and starts the stack as its own project (davomat-smoke) on
#      local ports, with DOMAIN=localhost (HTTPS from Caddy's own authority);
#   2. the organization is set up through the API, a terminal added, and its events posted the
#      way a Hikvision terminal does (smoke_events.py: multipart JSON + snapshot, plain HTTP to the
#      bare address, HTTPS without SNI); the employees must be created from the unknown numbers
#      and checked in (smoke_api.py);
#   3. backup.sh, a change, restore.sh: the change must be gone; status.sh; update.sh --here;
#   4. down -v: nothing is left (unless --keep).
#   bash deploy/davomat/smoke.sh [--keep] [--http-port 18080] [--https-port 18443] [--build-lock FILE]
# --build-lock FILE runs the image builds under flock FILE (one build at a time on a shared machine).
set -Eeuo pipefail
umask 022

HTTP_PORT=18080 HTTPS_PORT=18443 KEEP=0 LOCK=''
while [ $# -gt 0 ]; do
	case $1 in
	--keep) KEEP=1 ;;
	--http-port) HTTP_PORT=$2; shift ;;
	--https-port) HTTPS_PORT=$2; shift ;;
	--build-lock) LOCK=$2; shift ;;
	-h | --help)
		sed -n '2,13p' "$0"
		exit 0
		;;
	*)
		echo "Unknown option: $1" >&2
		exit 2
		;;
	esac
	shift
done

export DAVOMAT_PROJECT=${DAVOMAT_PROJECT:-davomat-smoke}
WORK=$(mktemp -d "${TMPDIR:-/tmp}/davomat-smoke.XXXXXX")
export DAVOMAT_ENV_FILE=$WORK/.env DAVOMAT_LOG_DIR=$WORK/logs
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[ "$PROJECT" != davomat ] || die "The smoke test never runs as the real project (davomat)."
need_docker
command -v python3 >/dev/null 2>&1 || die "python3 is needed."
started=$SECONDS

locked() {
	if [ -n "$LOCK" ]; then flock "$LOCK" "$@"; else "$@"; fi
}

# The backups were written by root in the backup container: removed through a container too.
as_root_in_docker() {
	docker run --rm -v "$WORK:/work" --entrypoint /bin/sh postgres:18-alpine -c "$1" </dev/null
}

cleanup() {
	local status=$?
	trap - EXIT
	if [ "$KEEP" = 1 ]; then
		step "Kept running (--keep)"
		info "$(site_url)/  (sign in as admin; the password is in $WORK/state.json)"
		info "Remove it: DAVOMAT_PROJECT=$PROJECT DAVOMAT_ENV_FILE=$ENV_FILE docker compose -p $PROJECT -f $COMPOSE_YML --env-file $ENV_FILE down -v"
		exit "$status"
	fi
	step "Removing the smoke stack"
	compose down -v --remove-orphans </dev/null >/dev/null 2>&1 || true
	# update.sh's copy of the image before it; the image itself stays for the next run.
	docker image rm "$(image_name)-previous" >/dev/null 2>&1 || true
	as_root_in_docker 'rm -rf /work/backups' >/dev/null 2>&1 || true
	rm -rf "$WORK"
	ok "Containers, volumes and files removed."
	exit "$status"
}
trap cleanup EXIT
trap 'printf "\n%sThe smoke test stopped at line %s.%s\n" "$RED" "$LINENO" "$RESET" >&2' ERR

step "Smoke test: $PROJECT on ports $HTTP_PORT and $HTTPS_PORT ($WORK)"
for port in "$HTTP_PORT" "$HTTPS_PORT"; do
	if ss -Hltn "sport = :$port" 2>/dev/null | grep -q .; then die "Port $port is taken."; fi
done

bash "$DAVOMAT_DIR/install.sh" --yes --no-start --domain localhost --device-host 127.0.0.1 \
	--http-port "$HTTP_PORT" --https-port "$HTTPS_PORT" --listen-local
# A machine shared with others: small, no messages leave it, the backups in the work folder.
for setting in TELEGRAM_DRY_RUN=true GUNICORN_WORKERS=2 CELERY_CONCURRENCY=1 BOT_DB_THREADS=4 \
	POSTGRES_SHARED_BUFFERS=128MB POSTGRES_EFFECTIVE_CACHE_SIZE=512MB \
	"DAVOMAT_BACKUP_DIR=$WORK/backups" "DAVOMAT_IMAGE=${SMOKE_IMAGE:-davomat:smoke}"; do
	env_set "$ENV_FILE" "${setting%%=*}" "${setting#*=}"
done
mkdir -p "$WORK/backups"

step "Building the image ($(image_name))"
locked docker compose -p "$PROJECT" -f "$COMPOSE_YML" --env-file "$ENV_FILE" build backend </dev/null

# The installer again: it keeps the settings, uses the image and starts everything.
bash "$DAVOMAT_DIR/install.sh" --yes

step "Every service is up"
# Healthy where the service has a health check (its first one may take half a minute), running
# otherwise.
for service in caddy backend worker beat bot backup db redis; do
	deadline=$((SECONDS + 120))
	while :; do
		state=$(service_state "$service")
		case $state in
		healthy | running) break ;;
		starting) ;;
		*) die "$service: $state: $(compose logs --no-color --tail 20 "$service" </dev/null 2>&1)" ;;
		esac
		[ "$SECONDS" -lt "$deadline" ] || die "$service: still $state after 120 s"
		sleep 3
	done
	ok "$service: $state"
done

step "Setup, a terminal and its events"
docker run --rm -v "$DAVOMAT_DIR:/davomat:ro" --entrypoint python "$(image_name)" \
	/davomat/smoke_events.py </dev/null >"$WORK/events.json"
ca_bundle "$WORK/ca.pem"
api() {
	python3 -I "$DAVOMAT_DIR/smoke_api.py" "$1" --site "https://localhost:$HTTPS_PORT" \
		--http "http://127.0.0.1:$HTTP_PORT" --http-name "http://localhost:$HTTP_PORT" \
		--https-ip "https://127.0.0.1:$HTTPS_PORT" --device-host 127.0.0.1 \
		--cacert "$WORK/ca.pem" --events "$WORK/events.json" --state "$WORK/state.json"
}
api scan

step "The worker, beat and the bot"
sleep 5
for service in worker beat bot; do
	restarts=$(restart_count "$service")
	[ "$restarts" = 0 ] || die "$service restarted $restarts times: $(compose logs --no-color --tail 20 "$service" </dev/null)"
	ok "$service: running, never restarted"
done
compose logs --no-color --no-log-prefix --tail 2 bot </dev/null | cut -c1-160 | sed 's/^/    bot: /'
errors=$(compose logs --no-color backend worker beat bot </dev/null 2>&1 | grep -cE 'Traceback|CRITICAL' || true)
[ "$errors" = 0 ] || {
	compose logs --no-color backend worker beat bot </dev/null 2>&1 | grep -B2 -A12 -E 'Traceback|CRITICAL' | tail -n 60 >&2
	die "$errors tracebacks in the logs (above)."
}
ok "no tracebacks in the logs"

step "Backup, a change, restore"
backup=$(bash "$DAVOMAT_DIR/backup.sh" smoke | tail -n 1)
# The backup belongs to root (made in the container); this user reads it for the checks and for
# restore.sh, as root does on a server.
as_root_in_docker "chown -R $(id -u):$(id -g) /work/backups"
for archive in db.sql.gz media.tgz private_media.tgz info.txt; do
	[ -s "$backup/$archive" ] || die "The backup has no $archive"
done
gzip -t "$backup/db.sql.gz" "$backup/media.tgz" "$backup/private_media.tgz"
snapshots=$(tar tzf "$backup/private_media.tgz" | grep -c '\.jpe\?g$' || true)
[ "$snapshots" -ge 2 ] || die "The backup holds $snapshots snapshots, not 2."
ok "$(basename "$backup"): database $(du -h "$backup/db.sql.gz" | cut -f1), $snapshots snapshots"
api change
bash "$DAVOMAT_DIR/restore.sh" "$backup" --yes
as_root_in_docker "chown -R $(id -u):$(id -g) /work/backups"
api restored

step "status.sh"
if bash "$DAVOMAT_DIR/status.sh"; then ok "status.sh: all good"; else die "status.sh found problems (above)."; fi

step "update.sh --here (rebuild and restart)"
locked bash "$DAVOMAT_DIR/update.sh" --here --no-backup
api restored

step "Smoke test passed in $(((SECONDS - started) / 60)) min $(((SECONDS - started) % 60)) s"
