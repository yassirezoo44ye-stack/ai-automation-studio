#!/usr/bin/env bash
# One independent audit cycle (spec section 7) of the Flow platform.
#
# Every cycle starts from nothing it shares with another: new empty
# databases, a fresh backend process, a fresh frontend build, new synthetic
# users, and the backend tests in a different random order. It never writes
# to production, sends real messages or makes payments: AI goes to an
# offline sink or is not configured, email goes to the console, Stripe is
# not configured (journey 10 uses a locally signed sandbox webhook).
#
# Usage: scripts/audit_cycle.sh <cycle-number> <output-dir>
# Needs: a local PostgreSQL 16 with pgvector reachable as test/test on
# localhost:5432 (superuser access via PGADMIN, default "su postgres -c psql"),
# PY (python with requirements*.txt installed), node_modules, Playwright.
#
# Writes <output-dir>/cycle-<n>/*.log, ui-*.json and summary.json.
set -uo pipefail

N="${1:?cycle number}"
OUT="$(realpath -m "${2:?output dir}")/cycle-$N"
PY="${PY:-python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGHOST_ADMIN="${PGHOST_ADMIN:-/tmp}"
API_PORT=$((8100 + N))
WEB_PORT=$((5200 + N))
DB_UNIT="flow_cycle${N}_unit"
DB_E2E="flow_cycle${N}_e2e"
DB_APP="flow_cycle${N}_app"
SEED=$((RANDOM * 32768 + RANDOM))
export SESSION_SECRET="audit-cycle-$N-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"

mkdir -p "$OUT"
cd "$ROOT" || exit 1
exec 3>&1 >"$OUT/runner.log" 2>&1

admin() { su postgres -c "psql -h $PGHOST_ADMIN -q -v ON_ERROR_STOP=1 -c \"$1\""; }
fresh_db() { admin "DROP DATABASE IF EXISTS $1" && admin "CREATE DATABASE $1 OWNER test" && \
  su postgres -c "psql -h $PGHOST_ADMIN -q -d $1 -c 'CREATE EXTENSION IF NOT EXISTS vector'"; }
url() { echo "postgresql://test:test@localhost:5432/$1"; }

declare -A RC START END
step() {  # step <name> <command...>
  local name="$1"; shift
  START[$name]=$(date +%s)
  echo "== $name: $*"
  "$@" >"$OUT/$name.log" 2>&1
  RC[$name]=$?
  END[$name]=$(date +%s)
  echo "== $name exit ${RC[$name]} in $((END[$name] - START[$name]))s" | tee -a /dev/fd/3
}

echo "cycle $N commit $(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) seed $SEED" | tee /dev/fd/3
for d in $DB_UNIT $DB_E2E $DB_APP; do fresh_db "$d"; done

# ── 1. Static gates ───────────────────────────────────────────────────────────
step py_compile bash -c "$PY -m py_compile main.py app_main.py && find app -name '*.py' -print0 | xargs -0 $PY -m py_compile"
step ruff bash -c "$PY -m ruff check app/ tests/ --exit-zero --output-format=json > '$OUT/ruff.json'; $PY -c \"import json;n=len(json.load(open('$OUT/ruff.json')));print('ruff',n);raise SystemExit(n>104)\""
step secret_scan env DATABASE_URL="$(url $DB_UNIT)" "$PY" scripts/ci_secret_scan.py
step schema_check env DATABASE_URL="$(url $DB_UNIT)" "$PY" scripts/ci_schema_check.py
fresh_db "$DB_UNIT"

# ── 2. Backend and end-to-end tests ───────────────────────────────────────────
# Random order (pytest-randomly, installed locally for the audit): tests that
# only pass in file order would show up here.
step backend env DATABASE_URL="$(url $DB_UNIT)" "$PY" -m pytest -p no:cacheprovider -q tests/ \
  --randomly-seed="$SEED" -r fE
step e2e env FLOW_E2E_DATABASE_URL="$(url $DB_E2E)" DATABASE_URL="$(url $DB_E2E)" \
  "$PY" -m pytest -p no:cacheprovider -q tests_e2e --randomly-seed="$SEED" -r fE

# ── 3. Frontend ───────────────────────────────────────────────────────────────
step frontend_tests npx vitest run --sequence.shuffle --sequence.seed="$SEED"
step typecheck npx tsc --noEmit
step lint npx eslint src --max-warnings 0
rm -rf "$OUT/dist"
step build npx vite build --outDir "$OUT/dist" --emptyOutDir

# ── 4. Dependencies ───────────────────────────────────────────────────────────
step npm_audit bash -c "npm audit --json > '$OUT/npm-audit.json'; $PY -c \"import json;print(json.load(open('$OUT/npm-audit.json'))['metadata']['vulnerabilities'])\""
step pip_audit "$PY" -m pip_audit -r requirements.txt --progress-spinner off

# ── 5. The built app in a real browser ────────────────────────────────────────
# Backend on a fresh database; static server that behaves like the Vercel
# config (files, /api proxied, missing /assets/ = 404, else index.html).
env DATABASE_URL="$(url $DB_APP)" "$PY" -m uvicorn app_main:app --port "$API_PORT" >"$OUT/api.log" 2>&1 &
API_PID=$!
DIST="$OUT/dist" API_PORT="$API_PORT" PORT="$WEB_PORT" node -e '
const http=require("http"),fs=require("fs"),path=require("path");const D=process.env.DIST;
const T={".js":"text/javascript",".css":"text/css",".html":"text/html",".svg":"image/svg+xml",".json":"application/json",".png":"image/png",".woff2":"font/woff2",".ico":"image/x-icon"};
http.createServer((q,r)=>{const u=decodeURIComponent(q.url.split("?")[0]);
 if(u.startsWith("/api/")||u==="/health"){const p=http.request({host:"127.0.0.1",port:+process.env.API_PORT,path:q.url,method:q.method,headers:{...q.headers,host:"127.0.0.1"}},x=>{r.writeHead(x.statusCode,x.headers);x.pipe(r)});p.on("error",()=>{r.writeHead(502);r.end()});q.pipe(p);return}
 let f=path.join(D,path.normalize(u));if(!f.startsWith(D)){r.writeHead(400);return r.end()}
 if(!(fs.existsSync(f)&&fs.statSync(f).isFile())){if(u.startsWith("/assets/")){r.writeHead(404);return r.end()}f=path.join(D,"index.html")}
 r.writeHead(200,{"content-type":T[path.extname(f)]||"application/octet-stream"});fs.createReadStream(f).pipe(r)}).listen(+process.env.PORT);
' >"$OUT/web.log" 2>&1 &
WEB_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null' EXIT
for _ in $(seq 60); do curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null && break; sleep 1; done

UI_EMAIL="flow-cycle$N-$(date +%s)@example.com"
UI_PASSWORD="Cycle-$N-$(head -c 9 /dev/urandom | base64 | tr -d '/+=')a1!"
step ui_user bash -c "
  curl -sf -X POST http://127.0.0.1:$WEB_PORT/api/auth/register -H 'content-type: application/json' -H 'X-Forwarded-For: 10.95.$N.1' \
    -d '{\"email\":\"$UI_EMAIL\",\"password\":\"$UI_PASSWORD\",\"name\":\"Cycle $N\"}' &&
  su postgres -c \"psql -h $PGHOST_ADMIN -q -d $DB_APP -c \\\"UPDATE users SET email_verified=true WHERE email='$UI_EMAIL'\\\"\""
export FLOW_UI_URL="http://127.0.0.1:$WEB_PORT" FLOW_UI_EMAIL="$UI_EMAIL" FLOW_UI_PASSWORD="$UI_PASSWORD"
step ui_actions node scripts/ui-runtime-audit.mjs actions "$OUT/ui-actions.json"
step ui_layout env FLOW_UI_VIEWPORTS="desktop,small-phone" node scripts/ui-runtime-audit.mjs layout "$OUT/ui-layout.json"
# A deploy that removed an old chunk: the host must answer 404, not HTML.
step missing_chunk bash -c "test \"\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$WEB_PORT/assets/Gone-old.js)\" = 404"
step api_errors bash -c "! grep -E '\"level\": \"(ERROR|CRITICAL)\"|Traceback' '$OUT/api.log'"
kill $API_PID $WEB_PID 2>/dev/null; wait 2>/dev/null

# ── Summary ───────────────────────────────────────────────────────────────────
for s in "${!RC[@]}"; do echo "$s ${RC[$s]} $((END[$s] - START[$s]))"; done >"$OUT/steps.txt"
"$PY" scripts/audit_cycle_summary.py "$OUT" "$N" "$SEED" | tee /dev/fd/3
for d in $DB_UNIT $DB_E2E $DB_APP; do admin "DROP DATABASE IF EXISTS $d"; done
rm -rf "$OUT/dist"
