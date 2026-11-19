#!/usr/bin/env bash
# Restore a Flow backup into an EMPTY database and verify it.
#
#   db_restore.sh DUMP_FILE TARGET_URL [FINGERPRINT_FILE]
#
# Refuses a target that already has tables, so it can never overwrite live
# data by mistake: create a new database (or a new Render instance), restore
# into it, verify, then point DATABASE_URL at it. With FINGERPRINT_FILE (the
# .fingerprint.txt saved beside the dump) every table's rows and contents are
# compared, and any difference fails the restore.
set -euo pipefail
dump="${1:?usage: db_restore.sh DUMP_FILE TARGET_URL [FINGERPRINT_FILE]}"
target="${2:?usage: db_restore.sh DUMP_FILE TARGET_URL [FINGERPRINT_FILE]}"
expected="${3:-}"
here="$(cd "$(dirname "$0")" && pwd)"

existing=$(psql "$target" -Atc "select count(*) from information_schema.tables where table_schema='public'")
if [ "$existing" != "0" ]; then
  echo "refusing: target database already has $existing tables in public; restore into an empty database" >&2
  exit 1
fi
# Skip COMMENT ON EXTENSION: only the extension owner (a superuser on
# Render) may set it, and the app never reads it.
toc="$(mktemp)"
pg_restore --list "$dump" | grep -v " COMMENT - EXTENSION " > "$toc"
if ! pg_restore --dbname="$target" --no-owner --no-privileges --exit-on-error --use-list="$toc" "$dump"; then
  echo "restore failed. If the error is 'permission denied to create extension', create the" >&2
  echo "extension first as an admin (CREATE EXTENSION vector;) and restore into a fresh empty database." >&2
  exit 1
fi
echo "restored $(basename "$dump")"

if [ -n "$expected" ]; then
  actual="$(mktemp)"
  "$here/db_fingerprint.sh" "$target" > "$actual"
  if diff -u "$expected" "$actual"; then
    echo "verified: $(wc -l < "$actual") tables match the backup exactly"
  else
    echo "MISMATCH: restored data differs from the backup fingerprint (diff above)" >&2
    exit 1
  fi
fi
