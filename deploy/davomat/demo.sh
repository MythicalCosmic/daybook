#!/usr/bin/env bash
# Davomat on this computer for a demo: the whole stack, as on a server, at http://localhost:18080
# (plain HTTP: browsers keep the sign-in on localhost, no certificate warning), with the example
# organization of manage.py davomat_demo. Its own project (davomat-demo), settings and backups (in
# DAVOMAT_DEMO_DIR, default ~/.local/share/davomat-demo): a real install is never touched. No root.
#   bash deploy/davomat/demo.sh up [--port 18080] [--lan] [--no-seed]
#                                       build the image if needed, start, add the example data
#   bash deploy/davomat/demo.sh seed      the example organization again (replaces the earlier one)
#   bash deploy/davomat/demo.sh rebuild   new code: rebuild and restart (update.sh --here)
#   bash deploy/davomat/demo.sh status | logs [service] | down (the data stays) | wipe (deleted)
# --lan also listens on this computer's network address, so a terminal on the same network can
# post to it (port 18080 on the terminal, not 80).
set -Eeuo pipefail
umask 022

command=${1:-up}
[ $# -eq 0 ] || shift
PORT=18080 LAN=0 SEED=1
while [ $# -gt 0 ]; do
	case $1 in
	--port) PORT=$2; shift ;;
	--lan) LAN=1 ;;
	--no-seed) SEED=0 ;;
	*) break ;;
	esac
	shift
done

DIR=${DAVOMAT_DEMO_DIR:-$HOME/.local/share/davomat-demo}
mkdir -p "$DIR"
export DAVOMAT_PROJECT=${DAVOMAT_PROJECT:-davomat-demo} DAVOMAT_ENV_FILE=$DIR/.env DAVOMAT_LOG_DIR=$DIR/logs
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[ "$PROJECT" != davomat ] || die "The demo never runs as the real project (davomat)."

# The example organization; --reset replaces an earlier one (davomat_demo never removes a real one).
seed() {
	step "The example organization (davomat_demo)"
	compose exec -T backend python manage.py davomat_demo --reset </dev/null
}

case $command in
up)
	need_docker
	if [ ! -f "$ENV_FILE" ]; then
		lan=''
		if [ "$LAN" = 1 ]; then
			lan=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit } }')
			[ -n "$lan" ] || die "No network address found for --lan."
		fi
		args=(--yes --no-start --http-only --domain localhost --http-port "$PORT" --device-host "${lan:-127.0.0.1}")
		[ "$LAN" = 1 ] || args+=(--listen-local)
		bash "$DAVOMAT_DIR/install.sh" "${args[@]}"
		for setting in GUNICORN_WORKERS=2 CELERY_CONCURRENCY=1 BOT_DB_THREADS=4 \
			POSTGRES_SHARED_BUFFERS=128MB POSTGRES_EFFECTIVE_CACHE_SIZE=512MB \
			"DAVOMAT_BACKUP_DIR=$DIR/backups" DAVOMAT_IMAGE=davomat:demo; do
			env_set "$ENV_FILE" "${setting%%=*}" "${setting#*=}"
		done
		mkdir -p "$DIR/backups"
	fi
	bash "$DAVOMAT_DIR/install.sh" --yes
	exists=$(compose exec -T backend python manage.py shell -c \
		"from apps.companies.models import Company; print(Company.objects.exists())" </dev/null 2>/dev/null | tail -n 1 || true)
	if [ "$SEED" = 1 ] && [ "$exists" != True ]; then seed; fi
	step "The demo is running"
	info "Open $(site_url)/  (the example organization: sign in as davomat_demo said above, admin / Namuna-2026 by default)"
	info "Without the example data the setup page opens instead: demo.sh wipe, then demo.sh up --no-seed."
	[ "$LAN" = 0 ] || info "Terminals on this network: host $(env_get PUBLIC_DEVICE_HOST), port $PORT, protocol HTTP."
	info "Stop it: bash deploy/davomat/demo.sh down"
	;;
seed)
	need_env
	seed
	;;
rebuild)
	need_env
	bash "$DAVOMAT_DIR/update.sh" --here --no-backup
	;;
status)
	need_env
	bash "$DAVOMAT_DIR/status.sh" || true
	;;
logs)
	need_env
	compose logs -f --tail 100 "$@"
	;;
down)
	need_env
	compose stop </dev/null
	ok "Stopped; the data stays (demo.sh up starts it again)."
	;;
wipe)
	need_env
	compose down -v --remove-orphans </dev/null
	# The backups belong to root (the backup container wrote them).
	docker run --rm -v "$DIR:/demo" --entrypoint /bin/rm postgres:18-alpine -rf /demo/backups </dev/null || true
	rm -rf "$DIR"
	ok "The demo and its data are gone."
	;;
-h | --help | help)
	sed -n '2,12p' "$0"
	;;
*)
	die "Unknown command: $command (up, seed, rebuild, status, logs, down, wipe)"
	;;
esac
