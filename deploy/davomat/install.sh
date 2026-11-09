#!/usr/bin/env bash
# Installs Davomat on this server: Docker when it's missing (asking first), the settings (.env:
# the address and freshly made keys), the stack of docker-compose.davomat.yml, and waits until the
# site answers. Run it as root from the checkout (a git clone or an unpacked release) on Ubuntu
# 22.04 or 24.04:
#   sudo bash deploy/davomat/install.sh
# Running it again is safe: an existing .env is never overwritten, and what runs keeps running.
# docs/davomat/en/INSTALL.md explains every step; --help lists the options.
set -Eeuo pipefail
umask 022
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
	cat <<'EOF'
Usage: sudo bash deploy/davomat/install.sh [options]

Where people open Davomat (asked when not given):
  --domain NAME          the site's name: your domain, or <public ip>.nip.io (the default)
  --lan [ADDRESS]        a server only the local network reaches, at ADDRESS (default: its LAN
                         address), with its own HTTPS certificate (browsers ask once to trust it)
  --http-only            plain HTTP, for a trial on this computer at http://localhost only
  --device-host HOST     the address Face ID terminals post to (default: the server's IP)
  --http-port N          another port than 80 (terminals, certificates and redirects need 80)
  --https-port N         another port than 443
  --listen-local         listen on 127.0.0.1 only (tests)

The organization (otherwise the browser's setup page asks):
  --organization NAME --admin-username NAME --admin-password PASSWORD
  [--admin-first-name NAME] [--admin-last-name NAME] [--timezone Asia/Tashkent] [--language uz|ru|en]

Other:
  --image FILE           load a prebuilt image (docker save davomat:latest | gzip > FILE)
                         instead of building one here
  --no-start             write the settings and stop there
  -y, --yes              no questions: the defaults, and Docker installed when missing
  -h, --help             this text

DAVOMAT_PROJECT and DAVOMAT_ENV_FILE run a second copy (deploy/davomat/smoke.sh does).
EOF
}

DOMAIN_ARG='' MODE='' LAN_ADDRESS='' DEVICE_HOST_ARG='' HTTP_PORT_ARG='' HTTPS_PORT_ARG=''
LISTEN_LOCAL=0 IMAGE_FILE='' NO_START=0 YES=0
ORG='' ADMIN_USERNAME='' ADMIN_PASSWORD='' ADMIN_FIRST_NAME='' ADMIN_LAST_NAME='' ORG_TIMEZONE='' ORG_LANGUAGE=''

need_value() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value (see --help)."; }

parse_args() {
	while [ $# -gt 0 ]; do
		case $1 in
		--domain) need_value "$@"; DOMAIN_ARG=$2; MODE=${MODE:-public}; shift 2 ;;
		--lan)
			MODE=lan
			if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then LAN_ADDRESS=$2; shift; fi
			shift
			;;
		--http-only) MODE=http; shift ;;
		--device-host) need_value "$@"; DEVICE_HOST_ARG=$2; shift 2 ;;
		--http-port) need_value "$@"; HTTP_PORT_ARG=$2; shift 2 ;;
		--https-port) need_value "$@"; HTTPS_PORT_ARG=$2; shift 2 ;;
		--listen-local) LISTEN_LOCAL=1; shift ;;
		--organization) need_value "$@"; ORG=$2; shift 2 ;;
		--admin-username) need_value "$@"; ADMIN_USERNAME=$2; shift 2 ;;
		--admin-password) need_value "$@"; ADMIN_PASSWORD=$2; shift 2 ;;
		--admin-first-name) need_value "$@"; ADMIN_FIRST_NAME=$2; shift 2 ;;
		--admin-last-name) need_value "$@"; ADMIN_LAST_NAME=$2; shift 2 ;;
		--timezone) need_value "$@"; ORG_TIMEZONE=$2; shift 2 ;;
		--language) need_value "$@"; ORG_LANGUAGE=$2; shift 2 ;;
		--image) need_value "$@"; IMAGE_FILE=$2; shift 2 ;;
		--no-start) NO_START=1; shift ;;
		-y | --yes) YES=1; shift ;;
		-h | --help) usage; exit 0 ;;
		*) die "Unknown option: $1 (see --help)" ;;
		esac
	done
	if [ -n "$ORG$ADMIN_USERNAME$ADMIN_PASSWORD" ] && { [ -z "$ORG" ] || [ -z "$ADMIN_USERNAME" ] || [ -z "$ADMIN_PASSWORD" ]; }; then
		die "--organization, --admin-username and --admin-password go together."
	fi
	for port in "$HTTP_PORT_ARG" "$HTTPS_PORT_ARG"; do
		[ -z "$port" ] || [[ $port =~ ^[0-9]+$ && $port -ge 1 && $port -le 65535 ]] || die "Not a port: $port"
	done
	[ -z "$IMAGE_FILE" ] || [ -r "$IMAGE_FILE" ] || die "Can't read the image file $IMAGE_FILE"
	# Piped in (ssh host 'bash -s' < install.sh) or run by a tool: nobody can answer questions.
	[ -t 0 ] || INTERACTIVE=0
}

INTERACTIVE=1
asking() { [ "$YES" = 0 ] && [ "$INTERACTIVE" = 1 ]; }

# ask_yes QUESTION: yes with --yes; no when nobody can answer.
ask_yes() {
	local answer
	[ "$YES" = 1 ] && return 0
	[ "$INTERACTIVE" = 1 ] || return 1
	read -r -p "    $1 [Y/n] " answer
	case ${answer:-y} in [Yy]*) return 0 ;; *) return 1 ;; esac
}

# ask QUESTION DEFAULT: the answer, or the default.
ask() {
	local answer
	if asking; then
		read -r -p "    $1 [$2]: " answer
		printf '%s' "${answer:-$2}"
	else
		printf '%s' "$2"
	fi
}

is_ipv4() { [[ $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }
is_name() { [[ $1 =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$ ]]; }

public_ip() {
	local url ip
	for url in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
		ip=$(curl -fsS -4 --max-time 6 "$url" 2>/dev/null | tr -d '[:space:]' || true)
		if is_ipv4 "$ip"; then
			printf '%s' "$ip"
			return
		fi
	done
}

lan_ip() {
	ip -4 route get 1.1.1.1 2>/dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit } }' || true
}

# The system ---------------------------------------------------------------------------------

IS_ROOT=1

check_system() {
	step "Checking the server"
	if ! is_root; then
		if docker info >/dev/null 2>&1; then
			IS_ROOT=0
			warn "Not running as root: Docker works for this user, so the installer goes on, but it won't install Docker or open the firewall."
		else
			die "Run it as root: sudo bash deploy/davomat/install.sh"
		fi
	fi
	local os=unknown memory_kb disk_kb
	if [ -r /etc/os-release ]; then
		# shellcheck disable=SC1091
		os=$(. /etc/os-release && printf '%s %s' "${ID:-}" "${VERSION_ID:-}")
	fi
	case $os in
	"ubuntu 22.04" | "ubuntu 24.04") ok "System: Ubuntu ${os#ubuntu }" ;;
	*) warn "Davomat is tested on Ubuntu 22.04 and 24.04; this is ${os}. Going on." ;;
	esac
	if [ "$(nproc 2>/dev/null || echo 1)" -lt 2 ]; then warn "One CPU: 2 or more are recommended."; fi
	memory_kb=$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo 2>/dev/null || echo 0)
	if [ "${memory_kb:-0}" -lt 3500000 ]; then
		warn "Memory: $((memory_kb / 1024)) MB. 4 GB is recommended; building the image needs about 2 GB (add swap on a smaller server)."
	else
		ok "Memory: $((memory_kb / 1024 / 1024 + 1)) GB, CPUs: $(nproc)"
	fi
	disk_kb=$(df -Pk "$ROOT" | awk 'NR == 2 { print $4 }')
	if [ "${disk_kb:-0}" -lt 5000000 ]; then
		die "Only $((disk_kb / 1024)) MB free on the disk: Davomat needs at least 5 GB (40 GB recommended)."
	elif [ "${disk_kb:-0}" -lt 20000000 ]; then
		warn "$((disk_kb / 1024 / 1024)) GB free on the disk: 40 GB is recommended (photos and backups grow)."
	else
		ok "Disk: $((disk_kb / 1024 / 1024)) GB free"
	fi
	if command -v timedatectl >/dev/null 2>&1; then
		if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" = yes ]; then
			ok "Clock: synchronized"
		else
			warn "The server's clock isn't synchronized (timedatectl set-ntp true): scan times are checked against it."
		fi
	fi
	command -v curl >/dev/null 2>&1 || {
		[ "$IS_ROOT" = 1 ] || die "curl is missing."
		apt-get update -q && apt-get install -y -q curl
	}
}

ensure_docker() {
	step "Docker"
	if ! command -v docker >/dev/null 2>&1; then
		[ "$IS_ROOT" = 1 ] || die "Docker isn't installed."
		if ! ask_yes "Docker isn't installed. Install it now with Docker's official script (get.docker.com)?"; then
			die "Davomat runs in Docker: install it (https://docs.docker.com/engine/install/ubuntu/), or run this again with --yes."
		fi
		local script
		script=$(mktemp)
		curl -fsSL https://get.docker.com -o "$script"
		sh "$script"
		rm -f "$script"
		systemctl enable --now docker >/dev/null 2>&1 || true
	fi
	if ! docker info >/dev/null 2>&1; then
		[ "$IS_ROOT" = 1 ] && systemctl start docker >/dev/null 2>&1 || true
		docker info >/dev/null 2>&1 || die "Docker is installed but not running: systemctl start docker"
	fi
	if ! docker compose version >/dev/null 2>&1; then
		[ "$IS_ROOT" = 1 ] || die "The Docker Compose plugin is missing."
		ask_yes "The Docker Compose plugin is missing. Install it (apt-get install docker-compose-plugin)?" ||
			die "Install the Docker Compose plugin and run this again."
		apt-get update -q
		apt-get install -y -q docker-compose-plugin || apt-get install -y -q docker-compose-v2
	fi
	local version major minor
	version=$(docker compose version --short 2>/dev/null | sed 's/^v//')
	major=${version%%.*}
	minor=${version#*.}
	minor=${minor%%.*}
	if [ "${major:-0}" -lt 2 ] || { [ "$major" -eq 2 ] && [ "${minor:-0}" -lt 20 ]; }; then
		die "Docker Compose $version is too old: 2.20 or newer is needed (apt-get install docker-compose-plugin)."
	fi
	ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), Compose $version"
}

# The settings -------------------------------------------------------------------------------

random_text() {
	local text
	text=$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
	printf '%s' "${text:0:$1}"
}

fernet_key() { head -c 32 /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_'; }

# Eight letters and digits that can't be misread (no 0/O, 1/I), as XXXX-XXXX.
setup_code() {
	local text
	text=$(head -c 512 /dev/urandom | tr -dc 'A-HJ-NP-Z2-9')
	printf '%s-%s' "${text:0:4}" "${text:4:4}"
}

choose_address() {
	step "Where people will open Davomat"
	local public='' lan choice
	lan=$(lan_ip)
	# Asked of the internet only when a default or the DNS check needs it: a server on a local
	# network may have no way out.
	case ${MODE:-public}:$DOMAIN_ARG in
	public:) public=$(public_ip) ;;
	public:localhost | public:*.nip.io | public:*.sslip.io) [ -n "$DEVICE_HOST_ARG" ] || public=$(public_ip) ;;
	public:*)
		if ! is_ipv4 "$DOMAIN_ARG" || [ -z "$DEVICE_HOST_ARG" ]; then public=$(public_ip); fi
		;;
	esac
	if [ -z "$MODE" ] && asking; then
		info "1) On the internet: a domain name, or ${public:-<public ip>}.nip.io without one (recommended)"
		info "2) Only on this local network${lan:+ ($lan)}: HTTPS with the server's own certificate"
		choice=$(ask "Choose 1 or 2" 1)
		case $choice in 2) MODE=lan ;; *) MODE=public ;; esac
	fi
	MODE=${MODE:-public}
	case $MODE in
	public)
		DOMAIN=$DOMAIN_ARG
		if [ -z "$DOMAIN" ]; then
			[ -n "$public" ] || die "Couldn't find this server's public address: pass --domain NAME (or --lan)."
			DOMAIN=$(ask "Domain name (its DNS A record points at $public)" "$public.nip.io")
		fi
		;;
	lan)
		DOMAIN=${LAN_ADDRESS:-$(ask "The server's address on the local network" "${lan:-}")}
		;;
	http)
		DOMAIN=${DOMAIN_ARG:-localhost}
		;;
	esac
	DOMAIN=$(printf '%s' "$DOMAIN" | tr '[:upper:]' '[:lower:]' | sed 's#^https\?://##; s#/.*$##')
	[ -n "$DOMAIN" ] || die "No address given."
	is_ipv4 "$DOMAIN" || is_name "$DOMAIN" || die "Not a domain name or an address: $DOMAIN"

	if [ "$MODE" = public ] && ! is_ipv4 "$DOMAIN" && [ "$DOMAIN" != localhost ]; then
		case $DOMAIN in
		*.nip.io | *.sslip.io) ;;
		*)
			if [ -n "$public" ] && ! getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{ print $1 }' | grep -qx "$public"; then
				warn "$DOMAIN doesn't point at this server ($public) yet. Set its DNS A record: Caddy keeps trying and gets the certificate once it does."
			fi
			;;
		esac
	fi
	DEVICE_HOST=$DEVICE_HOST_ARG
	if [ -z "$DEVICE_HOST" ]; then
		case $MODE in
		public) DEVICE_HOST=${public:-$DOMAIN} ;;
		*) DEVICE_HOST=$DOMAIN ;;
		esac
	fi
	ok "Site: $DOMAIN ($MODE), terminals post to: $DEVICE_HOST"
}

write_env() {
	step "Settings"
	local tmp https_port url_port scheme=https
	mkdir -p "$(dirname "$ENV_FILE")"
	tmp=$(mktemp "$ENV_FILE.XXXXXX")
	chmod 600 "$tmp"
	cat "$DAVOMAT_DIR/.env.example" >"$tmp"
	https_port=${HTTPS_PORT_ARG:-443}
	url_port=''
	if [ "$MODE" = http ]; then
		scheme=http
		[ "${HTTP_PORT_ARG:-80}" = 80 ] || url_port=":$HTTP_PORT_ARG"
	elif [ "$https_port" != 443 ]; then
		url_port=":$https_port"
	fi
	env_set "$tmp" DOMAIN "$DOMAIN"
	env_set "$tmp" DJANGO_ALLOWED_HOSTS "$DOMAIN"
	env_set "$tmp" DASHBOARD_URL "$scheme://$DOMAIN$url_port/dashboard/"
	env_set "$tmp" PUBLIC_DEVICE_HOST "$DEVICE_HOST"
	env_set "$tmp" HTTP_PORT "${HTTP_PORT_ARG:-80}"
	env_set "$tmp" HTTPS_PORT "$https_port"
	[ "$MODE" = lan ] && env_set "$tmp" CADDY_OPTIONS local_certs
	[ "$MODE" = http ] && env_set "$tmp" CADDYFILE Caddyfile.http
	[ "$LISTEN_LOCAL" = 1 ] && env_set "$tmp" LISTEN_PREFIX 127.0.0.1:
	env_set "$tmp" DJANGO_SECRET_KEY "$(random_text 50)"
	env_set "$tmp" POSTGRES_PASSWORD "$(random_text 40)"
	env_set "$tmp" FIELD_ENCRYPTION_KEY "$(fernet_key)"
	env_set "$tmp" FIELD_HASH_KEY "$(random_text 50)"
	# The setup page asks for it, so nobody else can claim the fresh install first (check_setup_code).
	env_set "$tmp" DAVOMAT_SETUP_TOKEN "$(setup_code)"
	mv "$tmp" "$ENV_FILE"
	ok "Wrote $ENV_FILE (mode 600: only its owner reads it). Keep a copy somewhere safe: its keys can't be made again."
}

check_env() {
	step "Settings"
	ok "Keeping the existing settings: $ENV_FILE"
	local key missing=''
	for key in DOMAIN DJANGO_ALLOWED_HOSTS DJANGO_SECRET_KEY POSTGRES_PASSWORD FIELD_ENCRYPTION_KEY FIELD_HASH_KEY; do
		[ -n "$(env_get "$key")" ] || missing="$missing $key"
	done
	[ -z "$missing" ] || die "$ENV_FILE has no value for:$missing (see deploy/davomat/.env.example)."
	if [ -n "$DOMAIN_ARG$MODE$DEVICE_HOST_ARG$HTTP_PORT_ARG$HTTPS_PORT_ARG" ]; then
		warn "The address options are ignored: the existing settings say $(env_get DOMAIN). Edit $ENV_FILE to change them, then deploy/davomat/update.sh --here."
	fi
	[ "$(stat -c %a "$ENV_FILE" 2>/dev/null)" = 600 ] || chmod 600 "$ENV_FILE"
}

open_firewall() {
	[ "$IS_ROOT" = 1 ] && command -v ufw >/dev/null 2>&1 || return 0
	ufw status 2>/dev/null | grep -q '^Status: active' || return 0
	local http https
	http=$(env_get HTTP_PORT 80)
	https=$(env_get HTTPS_PORT 443)
	step "Firewall"
	if ask_yes "The firewall (ufw) is on. Allow ports $http and $https for Davomat (the site and the terminals)?"; then
		ufw allow "$http/tcp" >/dev/null
		ufw allow "$https/tcp" >/dev/null
		ufw allow "$https/udp" >/dev/null
		ok "ufw allows $http/tcp, $https/tcp and $https/udp"
	else
		warn "Open ports $http and $https yourself: terminals and browsers can't reach Davomat otherwise."
	fi
}

check_ports() {
	local port listener
	[ "$(service_state caddy)" = missing ] || return 0
	command -v ss >/dev/null 2>&1 || return 0
	for port in "$(env_get HTTP_PORT 80)" "$(env_get HTTPS_PORT 443)"; do
		listener=$(ss -Hltn "sport = :$port" 2>/dev/null | head -n 1 || true)
		if [ -n "$listener" ]; then
			die "Port $port is taken by another program ($(ss -Hltnp "sport = :$port" 2>/dev/null | grep -o 'users:(("[^"]*' | cut -d'"' -f2 | head -n 1 || echo unknown)). Stop it (e.g. systemctl disable --now nginx apache2) or choose another port with --http-port/--https-port."
		fi
	done
}

# The stack ----------------------------------------------------------------------------------

build_image() {
	local image
	image=$(image_name)
	if [ -n "$IMAGE_FILE" ]; then
		step "Loading the image from $IMAGE_FILE"
		local loaded
		loaded=$(docker load -i "$IMAGE_FILE" | sed -n 's/^Loaded image: //p' | tail -n 1)
		[ -n "$loaded" ] || die "No image in $IMAGE_FILE"
		[ "$loaded" = "$image" ] || docker tag "$loaded" "$image"
		ok "Image: $image (from $loaded)"
		return
	fi
	step "Building Davomat $(app_version) (the first time takes 5-15 minutes)"
	compose build backend </dev/null
	ok "Image: $image"
}

# The setup code works only with a setup page that sends it (the dashboard's own bundle says):
# on a fresh install whose page doesn't, the code is dropped, or nobody could finish the setup.
check_setup_code() {
	[ -n "$(env_get DAVOMAT_SETUP_TOKEN)" ] || return 0
	[ "$(service_state backend)" = missing ] || return 0
	if docker run --rm --entrypoint grep "$(image_name)" -rqE 'setup_token([^_a-z]|$)' /app/dashboard/dist \
		</dev/null 2>/dev/null; then
		return 0
	fi
	env_set "$ENV_FILE" DAVOMAT_SETUP_TOKEN ''
	warn "This version's setup page asks for no setup code: open it as soon as the installer is done."
}

# True once the organization exists (the setup page or davomat_init made it).
org_exists() {
	[ "$(compose exec -T backend python manage.py shell -c \
		"from apps.companies.models import Company; print(Company.objects.exists())" </dev/null 2>/dev/null |
		tail -n 1)" = True ]
}

start_stack() {
	step "Starting"
	compose up -d db redis backend </dev/null
	info "The first start sets up the database: a few minutes."
	if ! wait_healthy backend 1500; then
		compose logs --no-color --tail 60 backend </dev/null >&2 || true
		die "The backend didn't start (its log is above). deploy/davomat/status.sh shows the rest."
	fi
	compose up -d --remove-orphans </dev/null
	ok "Running: $(compose ps --services --status running </dev/null | sort | tr '\n' ' ')"
}

init_organization() {
	[ -n "$ORG" ] || return 0
	step "The organization"
	if org_exists; then
		ok "Already set up: the organization options are ignored."
		return
	fi
	local args=(--organization "$ORG" --admin-username "$ADMIN_USERNAME")
	[ -z "$ORG_TIMEZONE" ] || args+=(--timezone "$ORG_TIMEZONE")
	[ -z "$ORG_LANGUAGE" ] || args+=(--language "$ORG_LANGUAGE")
	[ -z "$ADMIN_FIRST_NAME" ] || args+=(--admin-first-name "$ADMIN_FIRST_NAME")
	[ -z "$ADMIN_LAST_NAME" ] || args+=(--admin-last-name "$ADMIN_LAST_NAME")
	# The password travels in the environment (-e NAME takes it from this one), never in a
	# command line another user could list.
	DAVOMAT_ADMIN_PASSWORD=$ADMIN_PASSWORD compose exec -T -e DAVOMAT_ADMIN_PASSWORD backend \
		python manage.py davomat_init "${args[@]}" </dev/null ||
		die "Setting up the organization failed (above). The browser's setup page can do it instead."
	ok "$ORG is set up; sign in as $ADMIN_USERNAME."
}

verify_site() {
	step "Checking the site"
	local url tries=0 code
	url=$(site_url)
	until site_get /health/ >/dev/null 2>&1; do
		tries=$((tries + 1))
		if [ "$tries" -ge 36 ]; then
			warn "$url/health/ doesn't answer from this server yet. A public name needs ports 80 and 443 open to the internet for its certificate (firewall, DNS); deploy/davomat/status.sh checks again."
			return 0
		fi
		[ "$tries" = 1 ] && info "Waiting for the certificate and the first answer…"
		sleep 5
	done
	ok "$url/health/: $(site_get /health/ 2>/dev/null | tr -d '\n' | cut -c1-120)"
	code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
		"http://127.0.0.1:$(env_get HTTP_PORT 80)/api/v1/devices/hik/0000000000000000/" || true)
	if [ "$code" = 404 ]; then
		ok "Terminals can post over plain HTTP: the device address answers (404 for an unknown code, as it should)."
	else
		warn "The terminals' plain HTTP address answered $code instead of 404."
	fi
}

summary() {
	local url code
	url=$(site_url)
	code=$(env_get DAVOMAT_SETUP_TOKEN)
	step "Davomat is running"
	if [ -n "$ORG" ]; then
		info "Open ${BOLD}$url/${RESET} and sign in as ${BOLD}$ADMIN_USERNAME${RESET}."
	elif org_exists; then
		info "Open ${BOLD}$url/${RESET} and sign in."
	elif [ -n "$code" ]; then
		info "Open ${BOLD}$url/${RESET} in a browser to set up your organization."
		info "The setup page asks for this code: ${BOLD}$code${RESET} (only who sees it can set Davomat up)."
	else
		info "Open ${BOLD}$url/${RESET} in a browser to set up your organization."
		info "Do it now: until the setup is done, whoever opens the address first becomes its owner."
	fi
	info "Face ID terminals post to $(env_get PUBLIC_DEVICE_HOST "$(env_get DOMAIN)") over HTTP, port $(env_get HTTP_PORT 80): Face ID › Add a terminal shows the exact values."
	info "Settings:  $ENV_FILE (keep a copy somewhere safe)"
	info "Backups:   every night at $(env_get BACKUP_TIME 02:30) into $(backup_dir); now: deploy/davomat/backup.sh"
	info "Status:    deploy/davomat/status.sh     Update: deploy/davomat/update.sh"
	info "Logs:      docker compose -p $PROJECT -f $COMPOSE_YML logs -f"
	info "This run:  $LOG_FILE"
	info "Guides:    docs/davomat/ (uz, ru, en)"
}

main() {
	parse_args "$@"
	setup_log install
	trap 'printf "\n%sThe installer stopped (line %s). Its log: %s%s\n" "$RED" "$LINENO" "$LOG_FILE" "$RESET" >&2' ERR
	step "Davomat $(app_version): installing into $ROOT"
	check_system
	ensure_docker
	if [ -f "$ENV_FILE" ]; then
		check_env
	else
		choose_address
		write_env
	fi
	if [ "$NO_START" = 1 ]; then
		ok "Settings written; start it with: bash deploy/davomat/install.sh"
		return
	fi
	check_ports
	open_firewall
	fix_permissions
	# An image that's already here is used as it is: new code goes in with deploy/davomat/update.sh.
	if [ -n "$IMAGE_FILE" ] || ! docker image inspect "$(image_name)" >/dev/null 2>&1; then
		build_image
	else
		step "Image"
		local built
		built=$(docker image inspect -f '{{.Created}}' "$(image_name)")
		ok "Using $(image_name), built $(date -d "$built" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "$built") (new code: deploy/davomat/update.sh)"
	fi
	check_setup_code
	start_stack
	init_organization
	verify_site
	summary
}

main "$@"
