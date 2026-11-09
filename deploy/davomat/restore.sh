#!/usr/bin/env bash
# Puts a backup back: the database, the photos and the private files, exactly as they were then.
# Everything since that backup is lost, so a safety backup of the present state is taken first.
# Run it as root from the checkout:
#   bash deploy/davomat/restore.sh backups/2026-11-10_023000-nightly [--yes] [--no-safety-backup]
# On a new server: install Davomat with the old server's .env first (install.sh keeps it), then
# restore; the keys in .env must be the ones the backup was made with.
set -Eeuo pipefail
umask 077
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

source_dir='' YES=0 SAFETY=1
while [ $# -gt 0 ]; do
	case $1 in
	-y | --yes) YES=1 ;;
	--no-safety-backup) SAFETY=0 ;;
	-h | --help)
		sed -n '2,8p' "$0"
		exit 0
		;;
	-*) die "Unknown option: $1" ;;
	*) source_dir=$1 ;;
	esac
	shift
done
[ -n "$source_dir" ] || die "Which backup? bash deploy/davomat/restore.sh backups/<folder> (ls $(backup_dir 2>/dev/null || echo backups))"
[ -d "$source_dir" ] || die "No such folder: $source_dir"
source_dir=$(cd "$source_dir" && pwd)
[ -f "$source_dir/db.sql.gz" ] || die "$source_dir has no db.sql.gz: not a Davomat backup."
need_docker
need_env

step "Checking the backup"
for archive in db.sql.gz media.tgz private_media.tgz; do
	[ -f "$source_dir/$archive" ] || {
		warn "$archive is missing: that part is left as it is."
		continue
	}
	gzip -t "$source_dir/$archive" 2>/dev/null || die "$source_dir/$archive is damaged."
done
created=$(sed -n 's/^created=//p' "$source_dir/info.txt" 2>/dev/null || true)
ok "$source_dir${created:+ (made $created)}"

if [ "$YES" = 0 ]; then
	[ -t 0 ] || die "Run it with --yes to restore without a question."
	printf '\n    This replaces everything in Davomat with that backup: what happened since is lost.\n'
	read -r -p "    Type restore to go on: " answer
	[ "$answer" = restore ] || die "Nothing was changed."
fi

if [ "$SAFETY" = 1 ]; then
	step "A safety backup of the present state first"
	safety=$("$DAVOMAT_DIR/backup.sh" pre-restore | tail -n 1) || die "The safety backup failed: nothing was changed."
	ok "Safety backup: $safety"
fi

step "Stopping Davomat"
compose stop caddy bot beat worker backend backup </dev/null
compose up -d db redis </dev/null
wait_healthy db 120 || die "The database didn't start."

step "Restoring the database"
compose exec -T db dropdb -U davomat --if-exists --force davomat </dev/null
compose exec -T db createdb -U davomat -O davomat davomat </dev/null
gunzip -c "$source_dir/db.sql.gz" | compose exec -T db psql -q -v ON_ERROR_STOP=1 -U davomat -d davomat >/dev/null
ok "Database restored."

step "Restoring the photos and files"
# The backend's image has both volumes where the app keeps them; the files belong to its user.
# shellcheck disable=SC2016
compose run --rm -T --no-deps --user root --entrypoint /bin/sh -v "$source_dir:/restore:ro" backend -c '
	set -eu
	for part in media private_media; do
		[ -f "/restore/$part.tgz" ] || continue
		target=/app/backend/$part
		find "$target" -mindepth 1 -delete
		tar xzf "/restore/$part.tgz" -C "$target"
		chown -R 10001:10001 "$target"
		echo "    $part: $(find "$target" -type f | wc -l) files"
	done' </dev/null
# Cached pages, queued jobs and the bot's state belong to the present: they go.
compose exec -T redis redis-cli FLUSHALL </dev/null >/dev/null
ok "Files restored."

step "Starting Davomat"
compose up -d db redis backend </dev/null
wait_healthy backend 1500 || {
	compose logs --no-color --tail 60 backend </dev/null >&2 || true
	die "The backend didn't start after the restore (its log is above)."
}
compose up -d --remove-orphans </dev/null
if site_get /health/ >/dev/null 2>&1; then
	ok "Restored from $source_dir; $(site_url)/ answers."
else
	warn "Restored, but $(site_url)/health/ doesn't answer yet: deploy/davomat/status.sh"
fi
