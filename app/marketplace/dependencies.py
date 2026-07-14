"""
Marketplace dependency graph — required/optional item-to-item dependencies
with version constraints, cycle detection, and install-order resolution.

`resolve_install_order` adapts the same Kahn's-algorithm shape used by
`app/core/workflow/engine.py`'s `_topo_sort` (in-degree + children maps,
BFS-peel zero-in-degree nodes), re-typed for a dependency graph instead of
workflow steps, and raising typed exceptions instead of a bare ValueError so
the installation pipeline can distinguish failure reasons.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

DEPENDENCIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_dependencies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id             TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    depends_on_item_id  TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version_constraint  VARCHAR(30) NOT NULL DEFAULT '*',
    optional            BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_id, depends_on_item_id),
    CHECK (item_id != depends_on_item_id)
);
CREATE INDEX IF NOT EXISTS idx_mkt_deps_item ON marketplace_dependencies(item_id);
"""


async def init_dependencies_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(DEPENDENCIES_SCHEMA)
    log.info("marketplace dependencies schema initialised")


class MissingDependencyError(Exception):
    def __init__(self, item_id: str, missing_item_id: str):
        super().__init__(f"{item_id} depends on {missing_item_id}, which does not exist")
        self.item_id, self.missing_item_id = item_id, missing_item_id


class CircularDependencyError(Exception):
    def __init__(self, item_id: str):
        super().__init__(f"circular dependency detected while resolving {item_id}")
        self.item_id = item_id


class VersionConstraintError(Exception):
    def __init__(self, item_id: str, installed: str, constraint: str):
        super().__init__(
            f"{item_id}@{installed} does not satisfy required constraint {constraint!r}"
        )
        self.item_id, self.installed, self.constraint = item_id, installed, constraint


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_version(v: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(v.strip())
    if not m:
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {v!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def version_satisfies(installed: str, constraint: str) -> bool:
    """Hand-rolled comparator — supports '*', exact '1.2.3', '^1.2.0', '>=1.0.0'.
    No new pip dependency: version strings in this codebase are already
    plain MAJOR.MINOR.PATCH, so this small comparator covers the spec's
    'version constraints' requirement without adding semver/packaging."""
    constraint = constraint.strip()
    if constraint in ("", "*"):
        return True
    installed_t = _parse_version(installed)
    if constraint.startswith("^"):
        base = _parse_version(constraint[1:])
        return installed_t[0] == base[0] and installed_t >= base
    if constraint.startswith(">="):
        return installed_t >= _parse_version(constraint[2:])
    if constraint.startswith(">"):
        return installed_t > _parse_version(constraint[1:])
    if constraint.startswith("<="):
        return installed_t <= _parse_version(constraint[2:])
    if constraint.startswith("<"):
        return installed_t < _parse_version(constraint[1:])
    return installed_t == _parse_version(constraint)


class DependencyService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def add(
        self, item_id: str, depends_on_item_id: str, *,
        version_constraint: str = "*", optional: bool = False,
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO marketplace_dependencies
                     (item_id, depends_on_item_id, version_constraint, optional)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (item_id, depends_on_item_id) DO UPDATE SET
                     version_constraint=EXCLUDED.version_constraint,
                     optional=EXCLUDED.optional
                   RETURNING *""",
                item_id, depends_on_item_id, version_constraint, optional,
            )
        return dict(row)

    async def list_for_item(self, item_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM marketplace_dependencies WHERE item_id=$1 ORDER BY created_at",
                item_id,
            )
        return [dict(r) for r in rows]

    async def resolve_install_order(self, item_id: str) -> list[str]:
        """Returns a flat install order (dependencies before dependents) for
        `item_id` and everything it transitively (non-optionally) requires.
        Raises MissingDependencyError / CircularDependencyError."""
        from app.marketplace.store import get_marketplace_store

        store = get_marketplace_store()
        graph: dict[str, list[str]] = {}

        async def _walk(node: str) -> None:
            if node in graph:
                return
            graph[node] = []
            deps = await self.list_for_item(node)
            for dep in deps:
                if dep["optional"]:
                    continue
                dep_id = dep["depends_on_item_id"]
                target = await store.get_item(dep_id)
                if target is None:
                    raise MissingDependencyError(node, dep_id)
                if not version_satisfies(target["version"], dep["version_constraint"]):
                    raise VersionConstraintError(dep_id, target["version"], dep["version_constraint"])
                graph[node].append(dep_id)
                await _walk(dep_id)

        await _walk(item_id)

        # Kahn's algorithm, adapted from app/core/workflow/engine.py's
        # _topo_sort: in-degree = number of unresolved dependencies, peel
        # zero-in-degree nodes (nodes whose deps are already resolved).
        in_degree: dict[str, int] = {n: 0 for n in graph}
        children: dict[str, list[str]] = {n: [] for n in graph}
        for node, deps in graph.items():
            for dep in deps:
                in_degree[node] += 1
                children.setdefault(dep, []).append(node)

        order: list[str] = []
        queue = [n for n, deg in in_degree.items() if deg == 0]
        while queue:
            order.extend(queue)
            next_q: list[str] = []
            for n in queue:
                for child in children.get(n, []):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_q.append(child)
            queue = next_q

        if len(order) != len(graph):
            raise CircularDependencyError(item_id)
        return order


_service: DependencyService | None = None


def get_dependency_service(pool: asyncpg.Pool | None = None) -> DependencyService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = DependencyService(pool)
    return _service
