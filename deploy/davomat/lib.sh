# Shared by the Davomat scripts in this folder (sourced, never run on its own): where things are,
# the compose command, messages, settings, and waiting for the stack.
#
#   DAVOMAT_PROJECT   the Compose project (default davomat; smoke.sh runs davomat-smoke)
#   DAVOMAT_ENV_FILE  the settings file (default: .env at the checkout's root)
# shellcheck shell=bash

DAVOMAT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$DAVOMAT_DIR/../.." && pwd)
PROJECT=${DAVOMAT_PROJECT:-davomat}
ENV_FILE=${DAVOMAT_ENV_FILE:-$ROOT/.env}
case $ENV_FILE in /*) ;; *) ENV_FILE=$PWD/$ENV_FILE ;; esac
COMPOSE_YML=$ROOT/docker-compose.davomat.yml
# docker-compose.davomat.yml reads its env_file from here.
export DAVOMAT_ENV_FILE=$ENV_FILE

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
	BOLD=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RESET=$'\e[0m'
else
	BOLD='' DIM='' RED='' GREEN='' YELLOW='' RESET=''
fi

step() { printf '\n%s==> %s%s\n' "$BOLD" "$*" "$RESET"; }
info() { printf '    %s\n' "$*"; }
ok() { printf '    %s%s%s\n' "$GREEN" "$*" "$RESET"; }
warn() { printf '    %sWarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die() {
	printf '\n%sError:%s %s\n' "$RED" "$RESET" "$*" >&2
	exit 1
}

is_root() { [ "$(id -u)" -eq 0 ]; }

# Every docker compose call of the scripts. Callers pass < /dev/null where nothing should be read
# from stdin: piped into `ssh host 'bash -s'`, a compose exec would swallow the rest of the script.
compose() { docker compose -p "$PROJECT" -f "$COMPOSE_YML" --env-file "$ENV_FILE" "$@"; }

need_docker() {
	command -v docker >/dev/null 2>&1 || die "Docker isn't installed: run deploy/davomat/install.sh first."
	docker info >/dev/null 2>&1 || die "Docker isn't running, or this user may not use it (run as root)."
	docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is missing: apt-get install docker-compose-plugin"
}

need_env() {
	[ -f "$ENV_FILE" ] || die "No settings at $ENV_FILE: run deploy/davomat/install.sh first."
}

# env_get KEY [default]: KEY's value in the settings file (the last line wins), or the default.
env_get() {
	local value
	value=$(awk -v key="$1" 'index($0, key "=") == 1 { value = substr($0, length(key) + 2) } END { print value }' \
		"$ENV_FILE" 2>/dev/null || true)
	value=${value%$'\r'}
	case $value in
	\"*\") value=${value:1:${#value}-2} ;;
	\'*\') value=${value:1:${#value}-2} ;;
	esac
	printf '%s' "${value:-${2-}}"
}

# env_set FILE KEY VALUE: KEY's line set to VALUE (added at the end when missing), mode 600.
env_set() {
	local file=$1 tmp
	tmp=$(mktemp "$file.XXXXXX")
	chmod 600 "$tmp"
	KEY=$2 VALUE=$3 awk '
		BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"] }
		index($0, key "=") == 1 { if (!done) print key "=" value; done = 1; next }
		{ print }
		END { if (!done) print key "=" value }
	' "$file" >"$tmp"
	mv "$tmp" "$file"
}

image_name() { env_get DAVOMAT_IMAGE davomat:latest; }

# The backups folder on this server.
backup_dir() {
	local dir
	dir=$(env_get DAVOMAT_BACKUP_DIR ./backups)
	case $dir in /*) ;; *) dir=$ROOT/${dir#./} ;; esac
	printf '%s' "$dir"
}

# The address people open: https://DOMAIN (with the port when it isn't 443), or http:// in the
# plain HTTP mode.
site_url() {
	local domain port
	domain=$(env_get DOMAIN)
	if [ "$(env_get CADDYFILE Caddyfile)" = Caddyfile.http ]; then
		port=$(env_get HTTP_PORT 80)
		[ "$port" = 80 ] && printf 'http://%s' "$domain" || printf 'http://%s:%s' "$domain" "$port"
	else
		port=$(env_get HTTPS_PORT 443)
		[ "$port" = 443 ] && printf 'https://%s' "$domain" || printf 'https://%s:%s' "$domain" "$port"
	fi
}

# A CA bundle for checking the site's certificate from this server: the system's authorities and
# Caddy's own (localhost, IP addresses and local_certs use that one).
ca_bundle() {
	local bundle=$1 system
	: >"$bundle"
	for system in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/cert.pem; do
		if [ -r "$system" ]; then
			cat "$system" >>"$bundle"
			break
		fi
	done
	compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt </dev/null >>"$bundle" 2>/dev/null || true
}

# site_get PATH [curl options…]: GET a path of the site through Caddy on this server, so it works
# before the DNS does and checks the real certificate. Prints the body; fails on an error status.
site_get() {
	local path=$1 domain port bundle status
	shift
	domain=$(env_get DOMAIN)
	if [ "$(env_get CADDYFILE Caddyfile)" = Caddyfile.http ]; then
		port=$(env_get HTTP_PORT 80)
		curl -fsS --max-time 15 -H "Host: $domain" "$@" "http://127.0.0.1:$port$path"
		return
	fi
	port=$(env_get HTTPS_PORT 443)
	bundle=$(mktemp)
	ca_bundle "$bundle"
	status=0
	curl -fsS --max-time 15 --cacert "$bundle" --resolve "$domain:$port:127.0.0.1" "$@" \
		"https://$domain:$port$path" || status=$?
	rm -f "$bundle"
	return "$status"
}

# service_state SERVICE: healthy, starting, unhealthy, running (no health check), restarting,
# exited, … or missing.
service_state() {
	local id
	id=$(compose ps -aq "$1" </dev/null 2>/dev/null | head -n 1)
	[ -n "$id" ] || {
		echo missing
		return
	}
	docker inspect -f '{{if .State.Restarting}}restarting{{else if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
		"$id" 2>/dev/null || echo missing
}

# up_seconds SERVICE: how long its container has been running (0 when it isn't).
up_seconds() {
	local id started
	id=$(compose ps -q "$1" </dev/null 2>/dev/null | head -n 1)
	[ -n "$id" ] || {
		echo 0
		return
	}
	started=$(docker inspect -f '{{.State.StartedAt}}' "$id" 2>/dev/null) || {
		echo 0
		return
	}
	echo $(($(date +%s) - $(date -d "$started" +%s 2>/dev/null || date +%s)))
}

# wait_up SERVICE… [seconds each]: each one healthy (its first health check can take half a
# minute) or, without a health check, running. Fails on anything else.
wait_up() {
	local service state deadline timeout=120
	for service in "$@"; do
		deadline=$((SECONDS + timeout))
		while :; do
			state=$(service_state "$service")
			case $state in
			healthy | running) break ;;
			starting) ;;
			*)
				warn "$service: $state"
				compose logs --no-color --tail 20 "$service" </dev/null >&2 || true
				return 1
				;;
			esac
			if [ "$SECONDS" -ge "$deadline" ]; then
				warn "$service: still $state after $timeout s"
				return 1
			fi
			sleep 3
		done
		ok "$service: $state"
	done
}

restart_count() {
	local id
	id=$(compose ps -aq "$1" </dev/null 2>/dev/null | head -n 1)
	[ -n "$id" ] && docker inspect -f '{{.RestartCount}}' "$id" 2>/dev/null || echo 0
}

# wait_healthy SERVICE [seconds]: waits until the service's health check passes, showing the
# backend's progress (migrations) on the way. Fails when it crashes, turns unhealthy or times out.
wait_healthy() {
	local service=$1 timeout=${2:-1500} started=$SECONDS state line last='' restarts since
	# Only this start's lines: a restarted container keeps the log of its earlier runs.
	since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
	while :; do
		state=$(service_state "$service")
		case $state in
		healthy) return 0 ;;
		unhealthy | exited | dead | missing)
			warn "$service: $state"
			return 1
			;;
		esac
		restarts=$(restart_count "$service")
		if [ "${restarts:-0}" -ge 3 ]; then
			warn "$service keeps restarting ($restarts times)"
			return 1
		fi
		if ((SECONDS - started >= timeout)); then
			warn "$service: still $state after $timeout s"
			return 1
		fi
		line=$(compose logs --no-color --no-log-prefix --since "$since" --tail 30 "$service" </dev/null 2>/dev/null |
			grep -E 'Applying |Operations to perform|Booting worker|Listening at' | tail -n 1 | cut -c1-100 || true)
		if [ -n "$line" ] && [ "$line" != "$last" ]; then
			info "${DIM}${line}${RESET}"
			last=$line
		fi
		sleep 5
	done
}

# Every file the image is built from must stay readable for the app's user (uid 10001): a copy
# unpacked or cloned under umask 077 builds an image whose app can't read its own code.
fix_permissions() {
	local path
	for path in backend dashboard miniapp employee_bot owner_bot davomat_bot deploy \
		pyproject.toml uv.lock Dockerfile .dockerignore docker-compose.davomat.yml; do
		[ -e "$ROOT/$path" ] || continue
		find "$ROOT/$path" -name node_modules -prune -o \
			\( ! -perm -o=r -o \( -type d ! -perm -o=x \) \) -exec chmod go+rX {} + 2>/dev/null || true
	done
}

app_version() { sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n 1; }

# setup_log NAME: everything the script prints also goes to a log file (LOG_FILE), in
# DAVOMAT_LOG_DIR, else /var/log/davomat for root, else logs/ in the checkout.
setup_log() {
	local dir=${DAVOMAT_LOG_DIR:-}
	if [ -z "$dir" ]; then
		if is_root; then dir=/var/log/davomat; else dir=$ROOT/logs; fi
	fi
	mkdir -p "$dir"
	LOG_FILE=$dir/$1-$(date +%Y%m%d-%H%M%S).log
	exec > >(tee -a "$LOG_FILE") 2>&1
}
