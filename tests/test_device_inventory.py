"""
Device advisor M1 — read-only device inventory.

Covers the agent collector and Windows parsing (pure functions, any OS),
server-side sanitization, the WS frame rules, organization scoping of every
query, GET /api/devices/{id}/health and the controller's opt-in reporting.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import pathlib
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.inventory import collector
from agent.inventory.windows import parse_uninstall_entry
from app.services import device_inventory as inv

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORG = str(uuid.uuid4())
DEV = str(uuid.uuid4())


# ── Collector shaping ──────────────────────────────────────────────────────────

class TestShapeApps:
    def test_dedupes_on_name_and_version_case_insensitive(self):
        apps = collector.shape_apps([
            {"name": "Zoom", "version": "5.1"},
            {"name": "zoom", "version": "5.1"},
            {"name": "Zoom", "version": "6.0"},
        ])
        assert [(a["name"], a["version"]) for a in apps] == [("Zoom", "5.1"), ("Zoom", "6.0")]

    def test_sorts_by_name_and_skips_blank(self):
        apps = collector.shape_apps([{"name": "b"}, {"name": "  "}, {"name": "A"}, {}])
        assert [a["name"] for a in apps] == ["A", "b"]

    def test_caps_count_and_lengths(self):
        apps = collector.shape_apps([{"name": f"app{i:04d}" + "x" * 300} for i in range(800)])
        assert len(apps) == collector.MAX_APPS
        assert all(len(a["name"]) <= 200 for a in apps)

    def test_size_rounding_and_negative(self):
        apps = collector.shape_apps([
            {"name": "a", "size_mb": 12.345},
            {"name": "b", "size_mb": -1},
        ])
        assert apps[0]["size_mb"] == 12.3
        assert apps[1]["size_mb"] is None


class TestShapeProcesses:
    def test_aggregates_by_name_and_ranks(self):
        mb = 1024 * 1024
        procs = collector.shape_processes([
            ("chrome.exe", 100 * mb), ("chrome.exe", 150 * mb), ("code.exe", 200 * mb),
        ])
        assert procs == [
            {"name": "chrome.exe", "memory_mb": 250.0},
            {"name": "code.exe", "memory_mb": 200.0},
        ]

    def test_caps_and_skips_bad(self):
        procs = collector.shape_processes(
            [(f"p{i}", i) for i in range(50)] + [("", 5), ("bad", -1), ("x", "1")]
        )
        assert len(procs) == collector.MAX_PROCESSES
        assert all(p["name"] not in ("", "bad", "x") for p in procs)


class TestBuildFrame:
    def test_frame_shape(self):
        frame = collector.build_inventory_frame(
            apps_reader=lambda: [{"name": "Git"}],
            disks_reader=lambda: [{"mount": "C:\\", "total_gb": 100.0, "free_gb": 10.0}],
            memory_reader=lambda: {"total_mb": 16000, "used_mb": 8000},
            processes_reader=lambda: [("a", 1024 * 1024)],
            recycle_bin_reader=lambda: {"items": 3, "size_mb": 1.5},
        )
        assert frame["version"] == 1
        assert frame["type"] == "inventory_report"
        assert set(frame) == {"version", "type", "apps", "disks", "memory",
                              "top_processes", "recycle_bin", "timestamp"}

    def test_failing_reader_is_isolated(self):
        def boom():
            raise PermissionError("denied")

        frame = collector.build_inventory_frame(
            apps_reader=boom,
            disks_reader=lambda: [{"mount": "/", "total_gb": 1.0, "free_gb": 0.5}],
            memory_reader=boom,
        )
        assert frame["apps"] == []
        assert frame["memory"] is None
        assert frame["disks"] == [{"mount": "/", "total_gb": 1.0, "free_gb": 0.5}]
        assert frame["recycle_bin"] is None

    def test_real_collector_runs_here_and_is_small(self):
        frame = collector.collect_inventory()
        assert frame["type"] == "inventory_report"
        assert len(json.dumps(frame)) < 128 * 1024


def test_inventory_package_never_touches_files_or_paths():
    """Privacy: no file listing/reading, no install locations."""
    pattern = re.compile(r"\b(listdir|scandir|os\.walk|glob|open\(|InstallLocation|Path\()")
    for path in (ROOT / "agent" / "inventory").glob("*.py"):
        assert not pattern.search(path.read_text("utf-8")), path.name


# ── Windows uninstall-entry parsing ────────────────────────────────────────────

class TestParseUninstallEntry:
    def test_regular_app(self):
        entry = parse_uninstall_entry({
            "DisplayName": " 7-Zip ", "Publisher": "Igor Pavlov",
            "DisplayVersion": "23.01", "EstimatedSize": 2048,
        })
        assert entry == {"name": "7-Zip", "publisher": "Igor Pavlov",
                         "version": "23.01", "size_mb": 2.0}

    @pytest.mark.parametrize("values", [
        {},
        {"DisplayName": "   "},
        {"DisplayName": "Runtime", "SystemComponent": 1},
        {"DisplayName": "KB123", "ParentKeyName": "Office"},
        {"DisplayName": "Patch", "ReleaseType": "Security Update"},
        {"DisplayName": "Patch", "ReleaseType": "Hotfix"},
    ])
    def test_hidden_entries_skipped(self, values):
        assert parse_uninstall_entry(values) is None

    def test_bad_types_become_none(self):
        entry = parse_uninstall_entry({"DisplayName": "X", "Publisher": 5, "EstimatedSize": "big"})
        assert entry["publisher"] is None and entry["size_mb"] is None


# ── Server-side sanitization ───────────────────────────────────────────────────

class TestSanitize:
    def test_drops_unknown_fields_and_keeps_shape(self):
        out = inv.sanitize_inventory({
            "apps": [{"name": "Git", "evil": "x", "size_mb": 10}],
            "extra": "ignored",
        })
        assert set(out) == {"apps", "disks", "memory", "top_processes", "recycle_bin"}
        assert out["apps"] == [{"name": "Git", "publisher": None, "version": None, "size_mb": 10.0}]

    @pytest.mark.parametrize("bad", [True, -1, math.nan, math.inf, "5", 1e13, None])
    def test_rejects_bad_numbers(self, bad):
        out = inv.sanitize_inventory({"top_processes": [{"name": "p", "memory_mb": bad}]})
        assert out["top_processes"] == []

    def test_disk_and_memory_consistency(self):
        out = inv.sanitize_inventory({
            "disks": [{"mount": "C:", "total_gb": 10, "free_gb": 20},
                      {"mount": "D:", "total_gb": 10, "free_gb": 5}],
            "memory": {"total_mb": 100, "used_mb": 200},
        })
        assert [d["mount"] for d in out["disks"]] == ["D:"]
        assert out["memory"] is None

    def test_caps_lists_and_text(self):
        out = inv.sanitize_inventory({
            "apps": [{"name": "a" * 500}] * 900,
            "top_processes": [{"name": "p", "memory_mb": 1}] * 90,
            "disks": [{"mount": "X:", "total_gb": 1, "free_gb": 1}] * 90,
        })
        assert len(out["apps"]) == inv.MAX_APPS
        assert len(out["apps"][0]["name"]) == 200
        assert len(out["top_processes"]) == inv.MAX_PROCESSES
        assert len(out["disks"]) == inv.MAX_DISKS

    def test_non_dict_items_and_wrong_types(self):
        out = inv.sanitize_inventory({"apps": "nope", "disks": [1, "x"], "memory": [],
                                      "recycle_bin": {"items": 2.0, "size_mb": 3}})
        assert out["apps"] == [] and out["disks"] == [] and out["memory"] is None
        assert out["recycle_bin"] == {"items": 2, "size_mb": 3.0}


# ── WS frame rules ─────────────────────────────────────────────────────────────

class TestWsFrameRules:
    def test_type_allowed_and_valid(self):
        from app.routers import ws_device
        assert "inventory_report" in ws_device._ALLOWED_TYPES
        frame = collector.build_inventory_frame()
        assert ws_device._validate_frame(frame)

    def test_size_limits(self):
        from app.routers import ws_device
        assert ws_device._frame_size_ok(100 * 1024, "inventory_report")
        assert not ws_device._frame_size_ok(129 * 1024, "inventory_report")
        assert not ws_device._frame_size_ok(5000, "mouse_move")
        assert ws_device._frame_size_ok(4096, "key_down")


# ── Organization scoping ───────────────────────────────────────────────────────

def test_every_query_filters_by_organization():
    src = inspect.getsource(inv)
    queries = re.findall(r'"""(.*?)"""', src, re.S)
    sql = [q for q in queries if re.search(r"\b(SELECT|INSERT|DELETE)\b", q)]
    assert sql
    for q in sql:
        if "INSERT" in q:
            assert "organization_id" in q
        else:
            assert "organization_id = $2" in q, q


def _mock_pool(conn):
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = acquire
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return pool


def test_record_passes_device_and_org():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    with patch.object(inv, "get_pool", return_value=_mock_pool(conn)):
        assert asyncio.run(inv.record_inventory_snapshot(DEV, ORG, {"apps": []})) is True
    args = conn.fetchval.call_args.args
    assert args[1:3] == (uuid.UUID(DEV), uuid.UUID(ORG))
    insert = conn.execute.call_args_list[0].args
    assert insert[1:3] == (uuid.UUID(DEV), uuid.UUID(ORG))
    assert json.loads(insert[3])["apps"] == []


def test_record_throttled():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock()
    with patch.object(inv, "get_pool", return_value=_mock_pool(conn)):
        assert asyncio.run(inv.record_inventory_snapshot(DEV, ORG, {})) is False
    conn.execute.assert_not_called()


def test_latest_scoped_to_org():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(inv, "get_pool", return_value=_mock_pool(conn)):
        assert asyncio.run(inv.get_latest_inventory(ORG, DEV)) is None
    assert conn.fetchrow.call_args.args[1:] == (uuid.UUID(DEV), uuid.UUID(ORG))


# ── GET /api/devices/{id}/health ───────────────────────────────────────────────

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.routers.devices as dev_mod

    app = FastAPI()
    app.include_router(dev_mod.router)
    ctx_dep = inspect.signature(dev_mod.get_device_health).parameters["ctx"].default.dependency
    ctx = MagicMock()
    ctx.org_id = ORG
    app.dependency_overrides[ctx_dep] = lambda: ctx
    return TestClient(app, raise_server_exceptions=False)


def _health(device_id, device, snapshot=None):
    svc = MagicMock()
    svc.get_device = AsyncMock(return_value=device)
    latest = AsyncMock(return_value=snapshot)
    with patch("app.routers.devices.get_device_control_service", return_value=svc), \
         patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True), \
         patch("app.routers.devices.get_latest_inventory", latest):
        resp = _client().get(f"/api/devices/{device_id}/health")
    return resp, svc, latest


class TestHealthEndpoint:
    def test_unknown_device_404(self):
        resp, svc, latest = _health(DEV, None)
        assert resp.status_code == 404
        svc.get_device.assert_awaited_once_with(ORG, DEV)
        latest.assert_not_called()

    def test_malformed_id_404(self):
        resp, svc, _ = _health("not-a-uuid", {"id": DEV})
        assert resp.status_code == 404
        svc.get_device.assert_not_called()

    def test_no_snapshot_returns_nulls(self):
        resp, _, _ = _health(DEV, {"id": DEV})
        assert resp.status_code == 200
        assert resp.json() == {"device_id": DEV, "collected_at": None, "inventory": None}

    def test_snapshot_is_org_scoped(self):
        snap = {"collected_at": "2026-11-15T10:00:00+00:00", "inventory": {"apps": []}}
        resp, _, latest = _health(DEV, {"id": DEV}, snap)
        assert resp.status_code == 200
        assert resp.json()["inventory"] == {"apps": []}
        latest.assert_awaited_once_with(ORG, DEV)


# ── Controller opt-in ──────────────────────────────────────────────────────────

class TestController:
    def _ctrl(self, **kw):
        from agent.core.controller import DeviceAgentController
        return DeviceAgentController("dev", "cred", "wss://x", **kw)

    def test_off_by_default(self):
        assert self._ctrl()._inventory_enabled is False

    def test_report_sends_frame(self):
        ctrl = self._ctrl(inventory_enabled=True)
        ctrl._ws_client = MagicMock()
        ctrl._ws_client.send = AsyncMock()
        frame = {"version": 1, "type": "inventory_report"}
        with patch("agent.inventory.collector.collect_inventory", return_value=frame):
            assert asyncio.run(ctrl._report_inventory()) is True
        ctrl._ws_client.send.assert_awaited_once_with(frame)

    def test_failure_sends_nothing(self):
        ctrl = self._ctrl(inventory_enabled=True)
        ctrl._ws_client = MagicMock()
        ctrl._ws_client.send = AsyncMock()
        with patch("agent.inventory.collector.collect_inventory", side_effect=OSError("x")):
            assert asyncio.run(ctrl._report_inventory()) is False
        ctrl._ws_client.send.assert_not_called()
