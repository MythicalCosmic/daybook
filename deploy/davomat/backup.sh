#!/usr/bin/env bash
# A backup now: the database, the photos and the private files, into
# backups/<YYYY-MM-DD_HHMMSS>-<label>/ (deploy/davomat/backup-run.sh does the work, in the backup
# container; the nightly ones are made the same way). Run it as root from the checkout:
#   bash deploy/davomat/backup.sh [label]        label: letters, digits, dashes (default: manual)
# Prints the folder at the end. Copy it off the server (scp -r) and keep it somewhere safe.
set -Eeuo pipefail
umask 077
# shellcheck source=deploy/davomat/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case ${1:-} in -h | --help)
	header_help "$0"
	exit 0
	;;
esac
label=${1:-manual}
[[ $label =~ ^[A-Za-z0-9-]+$ ]] || die "A label has only letters, digits and dashes: $label"
need_docker
need_env

dir=$(backup_dir)
mkdir -p "$dir"
is_root && chmod 700 "$dir"

step "Backing up Davomat ($label)"
# run starts the database when it isn't running; < /dev/null so a piped script isn't swallowed.
output=$(compose run --rm -T --entrypoint /bin/sh backup /davomat/backup-run.sh "$label" </dev/null) ||
	{
		printf '%s\n' "$output" >&2
		die "The backup failed (above)."
	}
printf '%s\n' "$output" | grep -v '^backup: done ' | sed 's/^/    /'
name=$(printf '%s\n' "$output" | sed -n 's/^backup: done \([^ ]*\) .*/\1/p' | tail -n 1)
[ -n "$name" ] || die "The backup didn't say where it went:"$'\n'"$output"
size=$(printf '%s\n' "$output" | sed -n 's/^backup: done [^ ]* \(.*\)/\1/p' | tail -n 1)
ok "Backup: $dir/$name ($size)"
# The last line is the folder, for update.sh and restore.sh.
printf '%s\n' "$dir/$name"
