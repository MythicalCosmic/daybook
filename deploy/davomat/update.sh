#!/usr/bin/env bash
# Updates Davomat: the new code, a backup first, a new image, a restart, and waits until the site
# answers. Migrations run when the backend starts. Run it as root from the checkout:
#   bash deploy/davomat/update.sh                     the git checkout's branch (git pull)
#   bash deploy/davomat/update.sh --from FILE.tar.gz  a release (a tarball of the code)
#   bash deploy/davomat/update.sh --here              no new code: rebuild and restart (after
#                                                     editing .env, or a failed update)
# Options: --image FILE (a prebuilt image instead of building one), --no-backup, -y/--yes.
set -Eeuo pipefail
umask 022
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FROM='' HERE=0 IMAGE_FILE='' BACKUP=1
while [ $# -gt 0 ]; do
	case $1 in
	--from)
		[ $# -ge 2 ] || die "--from needs a file."
		FROM=$2
		shift
		;;
	--here) HERE=1 ;;
	--image)
		[ $# -ge 2 ] || die "--image needs a file."
		IMAGE_FILE=$2
		shift
		;;
	--no-backup) BACKUP=0 ;;
	-y | --yes) ;;
	-h | --help)
		sed -n '2,9p' "$0"
		exit 0
		;;
	*) die "Unknown option: $1 (see --help)" ;;
	esac
	shift
done
[ -z "$FROM" ] || [ -r "$FROM" ] || die "Can't read $FROM"
[ -z "$IMAGE_FILE" ] || [ -r "$IMAGE_FILE" ] || die "Can't read $IMAGE_FILE"
need_docker
need_env
setup_log update
trap 'printf "\n%sThe update stopped (line %s). Its log: %s%s\n" "$RED" "$LINENO" "$LOG_FILE" "$RESET" >&2' ERR

is_git() { [ -e "$ROOT/.git" ] && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; }
code_id() {
	if is_git; then git -C "$ROOT" rev-parse --short HEAD; else app_version; fi
}
checksum() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }

before_version=$(app_version)
before_code=$(code_id)
before_backup_job=$(checksum "$DAVOMAT_DIR/backup-run.sh")
step "Davomat $before_version ($before_code): updating"

# The new code ---------------------------------------------------------------------------------
if [ -n "$FROM" ]; then
	step "Unpacking $FROM"
	command -v rsync >/dev/null 2>&1 || {
		is_root || die "rsync is missing."
		apt-get update -q && apt-get install -y -q rsync
	}
	unpacked=$(mktemp -d)
	trap 'rm -rf "$unpacked"' EXIT
	tar -xf "$FROM" -C "$unpacked"
	release=$unpacked
	if [ ! -f "$release/docker-compose.davomat.yml" ]; then
		release=$(find "$unpacked" -mindepth 2 -maxdepth 2 -name docker-compose.davomat.yml -printf '%h\n' | head -n 1)
		[ -n "$release" ] || die "$FROM isn't a Davomat release (no docker-compose.davomat.yml in it)."
	fi
	backups_rel=$(env_get DAVOMAT_BACKUP_DIR ./backups)
	backups_rel=${backups_rel#./}
	# Only the code changes: the settings, the backups and the logs stay as they are.
	rsync -a --delete --exclude /.env --exclude /.env.* --exclude "/${backups_rel%/}" --exclude /backups \
		--exclude /logs --exclude /.git "$release/" "$ROOT/"
	ok "Code from $FROM"
elif [ "$HERE" = 0 ]; then
	is_git || die "This copy isn't a git checkout: update it with --from <release.tar.gz>, or rebuild it as it is with --here."
	step "Getting the new code (git pull)"
	[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ] ||
		die "The checkout has local changes (git -C $ROOT status): commit or undo them first."
	git -C "$ROOT" pull --ff-only
fi
after_version=$(app_version)
after_code=$(code_id)
if [ "$HERE" = 0 ] && [ -z "$IMAGE_FILE" ] && [ "$before_code" = "$after_code" ] && [ -z "$FROM" ]; then
	ok "Already up to date ($after_version, $after_code). To rebuild anyway: deploy/davomat/update.sh --here"
	exit 0
fi
fix_permissions

# A backup of the present state ----------------------------------------------------------------
backup_folder=''
if [ "$BACKUP" = 1 ]; then
	backup_folder=$("$DAVOMAT_DIR/backup.sh" pre-update | tail -n 1) || die "The backup failed: nothing was changed."
fi

rollback_help() {
	printf '\n    To go back to %s:\n' "$before_code" >&2
	if is_git; then
		printf '      git -C %s checkout %s\n' "$ROOT" "$before_code" >&2
	else
		printf '      unpack the previous release over %s (update.sh --from it)\n' "$ROOT" >&2
	fi
	printf '      bash deploy/davomat/update.sh --here --no-backup\n' >&2
	[ -z "$backup_folder" ] || printf '      bash deploy/davomat/restore.sh %s   (the data as it was)\n' "$backup_folder" >&2
}

# The image ------------------------------------------------------------------------------------
image=$(image_name)
case $image in *:*) previous=$image-previous ;; *) previous=$image:previous ;; esac
if docker image inspect "$image" >/dev/null 2>&1; then
	# What ran until now, kept under another name: DAVOMAT_IMAGE=<it> in .env runs it again.
	docker tag "$image" "$previous"
fi
if [ -n "$IMAGE_FILE" ]; then
	step "Loading the image from $IMAGE_FILE"
	loaded=$(docker load -i "$IMAGE_FILE" | sed -n 's/^Loaded image: //p' | tail -n 1)
	[ -n "$loaded" ] || die "No image in $IMAGE_FILE"
	[ "$loaded" = "$image" ] || docker tag "$loaded" "$image"
else
	step "Building Davomat $after_version"
	compose build backend </dev/null || {
		rollback_help
		die "The build failed (above): what runs wasn't touched."
	}
fi

# The restart ----------------------------------------------------------------------------------
step "Restarting"
compose up -d db redis backend </dev/null
if ! wait_healthy backend 1500; then
	compose logs --no-color --tail 60 backend </dev/null >&2 || true
	rollback_help
	die "The new backend didn't start (its log is above)."
fi
compose up -d --remove-orphans </dev/null

# Caddy reads one bind-mounted file: replaced on disk (git, rsync), a running Caddy keeps the old
# one. A changed file is checked first, then Caddy restarts (a second without the site).
caddyfile=$ROOT/deploy/davomat/$(env_get CADDYFILE Caddyfile)
if ! compose exec -T caddy cat /etc/caddy/Caddyfile </dev/null 2>/dev/null | cmp -s - "$caddyfile"; then
	step "The Caddyfile changed"
	compose run --rm --no-deps -T caddy caddy validate --config /etc/caddy/Caddyfile </dev/null >/dev/null ||
		die "The new Caddyfile doesn't validate: Caddy keeps the old one (compose run --rm caddy caddy validate --config /etc/caddy/Caddyfile)."
	compose restart caddy </dev/null
	ok "Caddy restarted with it."
fi
# The backup job is read when its container starts.
if [ "$before_backup_job" != "$(checksum "$DAVOMAT_DIR/backup-run.sh")" ]; then
	compose restart backup </dev/null
fi

step "Checking the site"
tries=0
until site_get /health/ >/dev/null 2>&1; do
	tries=$((tries + 1))
	if [ "$tries" -ge 24 ]; then
		rollback_help
		die "$(site_url)/health/ doesn't answer after the update."
	fi
	sleep 5
done
docker image prune -f >/dev/null 2>&1 || true
step "Updated: $before_version ($before_code) to $after_version ($after_code)"
info "The image that ran before is kept as $previous."
ok "$(site_get /health/ | tr -d '\n' | cut -c1-140)"
[ -z "$backup_folder" ] || info "The backup from before: $backup_folder"
info "This run: $LOG_FILE"
