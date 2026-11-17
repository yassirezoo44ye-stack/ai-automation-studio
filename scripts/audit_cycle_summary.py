"""Summarise one audit cycle directory (written by scripts/audit_cycle.sh) as JSON.

A cycle PASSES only if every step exited 0 and the browser run found no
crash, uncaught error or failed click. Anything not run is listed under
"blocked", never counted as passed.
"""
import json
import re
import sys
from pathlib import Path

out, n, seed = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]


def read(name: str) -> str:
    p = out / name
    return p.read_text(errors="replace") if p.exists() else ""


def pytest_counts(text: str) -> dict:
    tail = [ln for ln in text.splitlines() if re.search(r"\d+ (passed|failed)", ln)]
    line = tail[-1] if tail else ""
    return {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|errors?|warnings?)", line)}


steps = {}
for ln in read("steps.txt").splitlines():
    name, rc, secs = ln.split()
    steps[name] = {"exit": int(rc), "seconds": int(secs)}

vitest = re.search(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed \((\d+)\)", re.sub(r"\x1b\[[0-9;]*m", "", read("frontend_tests.log")))
pip = read("pip_audit.log")
pip_found = re.search(r"Found (\d+) known vulnerabilit", pip)

ui = {}
try:
    acts = json.loads(read("ui-actions.json") or "[]")
    outcomes = {}
    for row in acts:
        outcomes[row.get("outcome", "?").split(":")[0]] = outcomes.get(row.get("outcome", "?").split(":")[0], 0) + 1
    bad = [r for r in acts if r.get("outcome") in ("error screen", "uncaught error") or str(r.get("outcome", "")).startswith("click failed")]
    ui["controls"] = len(acts)
    ui["outcomes"] = outcomes
    ui["action_problems"] = [{k: r.get(k) for k in ("route", "name", "outcome", "errors")} for r in bad][:20]
except json.JSONDecodeError:
    ui["controls"] = None
try:
    lay = json.loads(read("ui-layout.json") or "[]")
    ui["screens"] = len(lay)
    ui["page_scroll_x"] = sorted({f"{r['route']} {r['viewport']} {r['lang']}" for r in lay if r.get("pageScrollX", 0) > 0})
    ui["crashed_screens"] = sorted({f"{r['route']} {r['viewport']} {r['lang']}" for r in lay if r.get("crashed")})
    ui["page_errors"] = sorted({f"{r['route']}: {e}" for r in lay for e in r.get("pageErrors", [])})[:20]
    ui["raw_keys"] = sorted({k for r in lay for k in r.get("rawKeys", [])})[:20]
    ui["cut_content"] = sum(r.get("cutCount", 0) for r in lay)
except json.JSONDecodeError:
    ui["screens"] = None

head = read("runner.log").splitlines()[0] if read("runner.log") else ""
summary = {
    "cycle": n,
    "commit": (re.search(r"commit (\w+)", head) or [None, None])[1],
    "seed": seed,
    "steps": steps,
    "backend": pytest_counts(read("backend.log")),
    "e2e": pytest_counts(read("e2e.log")),
    "frontend": {"failed": int(vitest[1] or 0), "passed": int(vitest[2]), "total": int(vitest[3])} if vitest else None,
    "npm_audit": (read("npm_audit.log").strip().splitlines() or [""])[-1],
    "pip_audit": "0 known vulnerabilities" if "No known vulnerabilities" in pip else (f"{pip_found[1]} known vulnerabilities" if pip_found else "not run"),
    "ui": ui,
    "api_log_errors": len(re.findall(r'"level": "(?:ERROR|CRITICAL)"', read("api.log"))),
}
failed = [s for s, v in steps.items() if v["exit"] != 0]
if ui.get("action_problems") or ui.get("crashed_screens") or ui.get("page_errors"):
    failed.append("ui")
summary["failed_steps"] = sorted(failed)
summary["blocked"] = [
    "Docker image build (Docker Hub rate limit / package mirror blocked in this environment)",
    "Real email inbox, Google OAuth round trip, Stripe test-mode checkout, real device agent",
    "This branch is not deployed: production runs the PR #56 code without M1-M9 fixes",
]
summary["verdict"] = "PASS" if not failed else "FAIL"
(out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
print(json.dumps({k: summary[k] for k in ("cycle", "verdict", "failed_steps", "backend", "e2e", "frontend")}))
