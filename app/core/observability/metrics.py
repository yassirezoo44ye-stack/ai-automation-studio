"""
MetricsRegistry — in-process counters, gauges, and histograms.

Prometheus-compatible naming (snake_case) without requiring the library.
Exposes a /api/metrics endpoint-ready dict and a text/plain Prometheus scrape.

Thread-safe via threading.Lock for sync callers; coroutine-safe because
asyncio runs on a single thread.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Counter:
    name   : str
    help   : str
    labels : dict[str, str] = field(default_factory=dict)
    _value : float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self._value += amount

    @property
    def value(self) -> float:
        return self._value

    def reset(self) -> None:
        self._value = 0.0


@dataclass
class Gauge:
    name   : str
    help   : str
    labels : dict[str, str] = field(default_factory=dict)
    _value : float = 0.0

    def set(self, v: float) -> None:    self._value = v
    def inc(self, a: float = 1.0) -> None: self._value += a
    def dec(self, a: float = 1.0) -> None: self._value -= a

    @property
    def value(self) -> float:
        return self._value


@dataclass
class Histogram:
    """Stores a rolling window of observations (last 1 000)."""
    name        : str
    help        : str
    labels      : dict[str, str] = field(default_factory=dict)
    _observations: list[float]   = field(default_factory=list)
    _window     : int = 1_000

    def observe(self, v: float) -> None:
        self._observations.append(v)
        if len(self._observations) > self._window:
            self._observations = self._observations[-self._window:]

    @property
    def count(self) -> int:   return len(self._observations)
    @property
    def total(self) -> float: return sum(self._observations)
    @property
    def avg(self) -> float:
        return (self.total / self.count) if self.count else 0.0
    @property
    def p50(self) -> float:   return self._percentile(0.50)
    @property
    def p95(self) -> float:   return self._percentile(0.95)
    @property
    def p99(self) -> float:   return self._percentile(0.99)

    def _percentile(self, p: float) -> float:
        if not self._observations:
            return 0.0
        s = sorted(self._observations)
        idx = int(len(s) * p)
        return round(s[min(idx, len(s) - 1)], 2)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "total": round(self.total, 2),
            "avg"  : round(self.avg, 2),
            "p50"  : self.p50,
            "p95"  : self.p95,
            "p99"  : self.p99,
        }


class MetricsRegistry:
    """
    Central store for all runtime metrics.

    Usage:
        m = get_metrics()
        m.counter("agentos_runs_total", "Total agent executions").inc()
        m.histogram("agentos_duration_ms", "Execution duration").observe(42.0)
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._counters  : dict[str, Counter]   = {}
        self._gauges    : dict[str, Gauge]     = {}
        self._histograms: dict[str, Histogram] = {}
        self._boot_time = time.time()

    # ── Factory methods ───────────────────────────────────────────────────────

    def counter(self, name: str, help: str = "",
                labels: Optional[dict] = None) -> Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name, help=help, labels=labels or {})
            return self._counters[name]

    def gauge(self, name: str, help: str = "",
              labels: Optional[dict] = None) -> Gauge:
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name, help=help, labels=labels or {})
            return self._gauges[name]

    def histogram(self, name: str, help: str = "",
                  labels: Optional[dict] = None) -> Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name=name, help=help, labels=labels or {})
            return self._histograms[name]

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "uptime_s"  : round(time.time() - self._boot_time, 1),
                "counters"  : {k: v.value       for k, v in self._counters.items()},
                "gauges"    : {k: v.value        for k, v in self._gauges.items()},
                "histograms": {k: v.to_dict()   for k, v in self._histograms.items()},
            }

    def prometheus_text(self) -> str:
        """Prometheus text exposition format."""
        lines: list[str] = []
        ts = int(time.time() * 1000)
        for name, c in self._counters.items():
            lines.append(f"# HELP {name} {c.help}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {c.value} {ts}")
        for name, g in self._gauges.items():
            lines.append(f"# HELP {name} {g.help}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {g.value} {ts}")
        for name, h in self._histograms.items():
            lines.append(f"# HELP {name} {h.help}")
            lines.append(f"# TYPE {name} histogram")
            lines.append(f"{name}_count {h.count} {ts}")
            lines.append(f"{name}_sum {round(h.total, 2)} {ts}")
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            for c in self._counters.values():  c.reset()


# ── Pre-wired OS-level metrics ─────────────────────────────────────────────────

_registry: MetricsRegistry | None = None


def get_metrics() -> MetricsRegistry:
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
        _wire_defaults(_registry)
    return _registry


def _wire_defaults(m: MetricsRegistry) -> None:
    m.counter  ("agentos_runs_total",         "Total agent kernel.run() calls")
    m.counter  ("agentos_runs_success",        "Successful agent executions")
    m.counter  ("agentos_runs_failed",         "Failed agent executions")
    m.histogram("agentos_duration_ms",         "Agent execution duration in ms")
    m.counter  ("agentos_plans_total",         "Total planning engine invocations")
    m.counter  ("agentos_evolution_cycles",    "Agent evolution cycles triggered")
    m.counter  ("agentos_codegen_total",       "Code generation pipeline runs")
    m.counter  ("agentos_codegen_approved",    "Code generation runs approved")
    m.counter  ("agentos_codegen_rejected",    "Code generation runs rejected")
    m.gauge    ("agentos_agents_active",       "Currently registered agents")
    m.gauge    ("agentos_services_running",    "Background services currently running")
    m.histogram("agentos_plan_tasks",          "Number of tasks in an execution plan")
    m.counter  ("http_requests_total",         "Total HTTP requests")
    m.histogram("http_request_duration_ms",    "HTTP request latency in ms")
    m.counter  ("http_errors_total",           "Total HTTP 5xx errors")

    # ── Rate limiting ────────────────────────────────────────────────────
    m.counter  ("rate_limit_rejections_total", "Total requests rejected with HTTP 429")

    # ── AI ────────────────────────────────────────────────────────────────
    m.counter  ("ai_requests_total",           "Total completed AI requests")
    m.counter  ("ai_tokens_input_total",       "Total input tokens consumed")
    m.counter  ("ai_tokens_output_total",      "Total output tokens generated")
    m.counter  ("ai_cost_usd_total",           "Total AI spend in USD")
    m.histogram("ai_request_latency_ms",       "AI request latency in ms")
    m.counter  ("ai_provider_failures_total",  "Total AI provider call failures")
    m.gauge    ("ai_active_streams",           "Currently open AI streaming responses")

    # ── Workflow ──────────────────────────────────────────────────────────
    m.counter  ("workflow_runs_total",         "Total workflow runs started")
    m.counter  ("workflow_runs_success",       "Total workflow runs completed successfully")
    m.counter  ("workflow_runs_failed",        "Total workflow runs that failed")
    m.gauge    ("workflow_active_runs",        "Currently executing workflow runs")

    # ── Marketplace ───────────────────────────────────────────────────────
    m.counter  ("marketplace_installs_total",  "Total marketplace listing installs")
    m.counter  ("marketplace_publishes_total", "Total marketplace listing publishes")

    # ── Billing ───────────────────────────────────────────────────────────
    m.counter  ("billing_events_total",        "Total billing.updated events processed")

    # ── System (sampled every ~15s by SystemMetricsService) ─────────────────
    m.gauge    ("system_cpu_percent",          "Process CPU utilisation percent")
    m.gauge    ("system_memory_rss_mb",        "Process resident memory in MB")
    m.gauge    ("system_disk_used_percent",    "Disk utilisation percent")
    m.gauge    ("system_network_bytes_sent",   "Cumulative bytes sent")
    m.gauge    ("system_network_bytes_recv",   "Cumulative bytes received")
    m.gauge    ("system_open_fds",             "Open file descriptors (process)")

    # ── Sandbox (sampled every ~15s by SystemMetricsService) ─────────────────
    m.gauge    ("sandbox_running_workers",     "Currently running sandbox workers")
    m.gauge    ("sandbox_execution_failures",  "Sandbox workers in crashed state")
    m.gauge    ("sandbox_cpu_seconds",         "Total CPU seconds used by running sandbox workers")
    m.gauge    ("sandbox_memory_mb",           "Total memory MB used by running sandbox workers")
