#!/usr/bin/env bash
# Print one line per table in the public schema: "table|row_count|md5".
# The md5 covers every row's full contents (order-independent), so two
# databases print identical output only when their data is identical.
# Usage: db_fingerprint.sh DATABASE_URL
set -euo pipefail
url="${1:?usage: db_fingerprint.sh DATABASE_URL}"
query=$(psql "$url" -v ON_ERROR_STOP=1 -Atc "
  select string_agg(format(
    'select %L, count(*), coalesce(md5(string_agg(md5(x::text), '''' order by md5(x::text))), ''-'') from %I.%I x',
    table_name, table_schema, table_name), ' union all ')
  from information_schema.tables
  where table_schema = 'public' and table_type = 'BASE TABLE'")
if [ -z "$query" ]; then
  echo "no tables in schema public" >&2
  exit 1
fi
psql "$url" -v ON_ERROR_STOP=1 -Atc "$query order by 1"
