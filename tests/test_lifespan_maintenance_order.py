"""BE-03 regression guard: background maintenance must start after the
schemas its first cycle reads.

maintenance_loop() runs a cycle immediately on startup and queries
organizations, organization_members, org_subscriptions and usage tables.
When the task was created before init_tenancy_schema() /
init_org_subscriptions_schema(), a fresh database (CI, a new tenant DB,
disaster recovery) logged `relation "organizations" does not exist` and the
reconciliation steps were silently skipped.
"""
import ast
import inspect

from app import factory


def _line_of_first_call(tree: ast.AST, name: str) -> int:
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]
    assert lines, f"lifespan() no longer calls {name}()"
    return min(lines)


def test_maintenance_loop_starts_after_the_schemas_it_queries():
    tree = ast.parse(inspect.getsource(factory.lifespan))
    maintenance = _line_of_first_call(tree, "maintenance_loop")
    for schema_init in (
        "init_db",
        "init_tenancy_schema",
        "init_usage_schema",
        "init_org_subscriptions_schema",
    ):
        assert _line_of_first_call(tree, schema_init) < maintenance, (
            f"maintenance_loop() is started before {schema_init}(); its first "
            "cycle would query tables that do not exist yet on a fresh database"
        )
