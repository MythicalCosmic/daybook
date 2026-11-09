#!/bin/sh
# Runs inside the backup container (postgres:18-alpine, docker-compose.davomat.yml):
#   backup-run.sh --daily    every day at BACKUP_TIME (in TZ), keeping BACKUP_KEEP_DAYS days
#   backup-run.sh LABEL      one backup now (deploy/davomat/backup.sh, update.sh, restore.sh)
#
# A backup is a folder /backups/<YYYY-MM-DD_HHMMSS>-<label>/ with db.sql.gz (pg_dump, plain SQL),
# media.tgz (logos, employee photos), private_media.tgz (scan snapshots, exports) and info.txt.
# It is written as .<name>.partial and renamed when complete, so a folder with a date is whole.
# Only root may read them: they hold everyone's names, photos and attendance.
set -eu
set -o pipefail
umask 077

# Every step is checked by hand: called from `||` (the daily loop), `set -e` doesn't stop a function.
failed() {
	echo "backup: $name: $1 failed" >&2
	rm -rf "$partial"
}

backup_once() {
	label=$1
	name=$(date +%Y-%m-%d_%H%M%S)-$label
	partial=/backups/.$name.partial
	rm -rf "$partial" && mkdir -p "$partial" || {
		failed "making the folder"
		return 1
	}
	echo "backup: $name: the database"
	pg_dump --no-owner | gzip >"$partial/db.sql.gz" || {
		failed "the database dump"
		return 1
	}
	echo "backup: $name: the photos and files"
	tar czf "$partial/media.tgz" -C /media . || {
		failed "the photos"
		return 1
	}
	tar czf "$partial/private_media.tgz" -C /private_media . || {
		failed "the private files"
		return 1
	}
	{
		echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		echo "label=$label"
		echo "database=$PGDATABASE"
		echo "server=$(pg_dump --version | sed 's/^pg_dump //')"
	} >"$partial/info.txt" && mv "$partial" "/backups/$name" || {
		failed "finishing"
		return 1
	}
	echo "backup: done $name $(du -sh "/backups/$name" | cut -f1)"
}

prune() {
	keep=${BACKUP_KEEP_DAYS:-14}
	find /backups -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]_*' \
		-mtime +"$keep" -exec rm -rf {} +
	# A backup cut off half way (the server restarted during one).
	find /backups -mindepth 1 -maxdepth 1 -type d -name '.*.partial' -mmin +720 -exec rm -rf {} +
}

daily() {
	at=${BACKUP_TIME:-02:30}
	case $at in
	[0-2][0-9]:[0-5][0-9]) ;;
	*)
		echo "backup: BACKUP_TIME must look like 02:30, not $at" >&2
		exit 1
		;;
	esac
	trap 'exit 0' TERM INT
	echo "backup: every day at $at (${TZ:-UTC}) into /backups, kept ${BACKUP_KEEP_DAYS:-14} days"
	while :; do
		now=$(date +%s)
		next=$(date -d "$(date +%Y-%m-%d) $at" +%s)
		[ "$next" -gt "$now" ] || next=$((next + 86400))
		sleep $((next - now)) &
		wait $!
		backup_once nightly || echo "backup: failed (see above); the next try is tomorrow" >&2
		prune || true
	done
}

case ${1:-} in
--daily) daily ;;
'' | -*)
	echo "usage: backup-run.sh --daily | LABEL" >&2
	exit 2
	;;
*[!A-Za-z0-9-]*)
	echo "backup: a label has only letters, digits and dashes: $1" >&2
	exit 2
	;;
*)
	backup_once "$1" || exit 1
	prune || true
	;;
esac
