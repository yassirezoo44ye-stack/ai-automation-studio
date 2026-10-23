"""Regression tests for HealthRegistry snapshot caching."""

import asyncio
import time
import unittest

from app.core.observability.health import HealthRegistry, HealthStatus, ProbeResult


class TestHealthRegistrySnapshot(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.registry = HealthRegistry()
        self.registry._snapshot_ttl_s = 60.0

        async def probe():
            self.calls += 1
            return ProbeResult(name="test", status=HealthStatus.HEALTHY)

        self.registry.register("test", probe)

    def run_check(self, *, force=False):
        return asyncio.run(self.registry.check_all(force=force))

    def test_reuses_cached_report_within_ttl(self):
        first = self.run_check()
        second = self.run_check()

        self.assertIs(first, second)
        self.assertEqual(self.calls, 1)
        self.assertIs(self.registry._snapshot[0], first)

    def test_force_bypasses_snapshot_and_refreshes_it(self):
        first = self.run_check()
        second = self.run_check(force=True)

        self.assertIsNot(first, second)
        self.assertEqual(self.calls, 2)
        self.assertIs(self.registry._snapshot[0], second)

    def test_expired_snapshot_triggers_new_probe_run(self):
        first = self.run_check()
        self.registry._snapshot = (
            first,
            time.time() - self.registry._snapshot_ttl_s - 1,
        )

        second = self.run_check()

        self.assertIsNot(first, second)
        self.assertEqual(self.calls, 2)
        self.assertIs(self.registry._snapshot[0], second)

    def test_snapshot_timestamp_matches_report_timestamp(self):
        report = self.run_check()

        self.assertEqual(self.registry._snapshot[1], report["ts"])
        self.assertIs(self.registry._snapshot[0], report)


if __name__ == "__main__":
    unittest.main()
