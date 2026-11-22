#!/bin/sh
# Installed as `cargo` inside the crm-build container: heavy cargo commands run one at a time
# (the laptop overheats and runs out of memory when several Rust builds overlap).
REAL="${CRM_REAL_CARGO:-/usr/local/cargo/bin/cargo.proxy}"
case "$1" in
  build|check|test|run|rustc|clippy|doc|bench) exec flock /tmp/crm-cargo.lock "$REAL" "$@" ;;
  *) exec "$REAL" "$@" ;;
esac
