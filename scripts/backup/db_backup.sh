#!/usr/bin/env bash
# Take a logical backup of the Flow database and prove it restores.
#
#   db_backup.sh SOURCE_URL OUT_DIR [SCRATCH_URL]
#
# 1. pg_dump (custom format) of SOURCE_URL into OUT_DIR/flow-<UTC time>.dump
# 2. pg_restore --list, so a truncated or corrupt file fails here
# 3. With SCRATCH_URL (an EMPTY throwaway database): restore the dump into
#    it, check core tables are present, and write the per-table fingerprint
#    next to the dump. db_restore.sh compares against that fingerprint.
#
# pg_dump must be the same major version as the server or newer (production
# runs Postgres 18). The GitHub workflow runs this inside pgvector/pgvector:pg18.
set -euo pipefail
src="${1:?usage: db_backup.sh SOURCE_URL OUT_DIR [SCRATCH_URL]}"
out="${2:?usage: db_backup.sh SOURCE_URL OUT_DIR [SCRATCH_URL]}"
scratch="${3:-}"
here="$(cd "$(dirname "$0")" && pwd)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"
dump="$out/flow-$stamp.dump"

echo "pg_dump $(pg_dump --version | awk '{print $3}') -> $(basename "$dump")"
pg_dump "$src" --format=custom --no-owner --no-privileges --file="$dump"
objects=$(pg_restore --list "$dump" | grep -vc '^;')
echo "dump ok: $(du -h "$dump" | cut -f1), $objects objects"

if [ -n "$scratch" ]; then
  existing=$(psql "$scratch" -Atc "select count(*) from information_schema.tables where table_schema='public'")
  if [ "$existing" != "0" ]; then
    echo "refusing: scratch database already has $existing tables in public" >&2
    exit 1
  fi
  # Same TOC filter as db_restore.sh: COMMENT ON EXTENSION needs the
  # extension's owner, which a restoring app user usually is not.
  toc="$(mktemp)"
  pg_restore --list "$dump" | grep -v " COMMENT - EXTENSION " > "$toc"
  pg_restore --dbname="$scratch" --no-owner --no-privileges --exit-on-error --use-list="$toc" "$dump"
  for t in users organizations projects; do
    psql "$scratch" -Atc "select 1 from $t limit 0" >/dev/null || { echo "restore check failed: table $t missing" >&2; exit 1; }
  done
  "$here/db_fingerprint.sh" "$scratch" > "$out/flow-$stamp.fingerprint.txt"
  echo "restore test ok: $(wc -l < "$out/flow-$stamp.fingerprint.txt") tables, $(awk -F'|' '{s+=$2} END {print s}' "$out/flow-$stamp.fingerprint.txt") rows"
fi
echo "$dump"
