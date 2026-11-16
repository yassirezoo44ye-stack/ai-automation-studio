"""No live database needed: verify query scoping and transition guards."""
import uuid
import pytest

from app.business_launch.store import create_project, get_project, list_projects, advance_project


ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
PROJECT = str(uuid.uuid4())


class FakeConn:
    def __init__(self, stage="IDEA"):
        self.stage = stage
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if query.lstrip().startswith("SELECT"):
            return {"stage": self.stage, "id": PROJECT}
        if query.lstrip().startswith("UPDATE"):
            self.stage = args[2]
        return {"stage": self.stage, "id": PROJECT}

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []


@pytest.mark.asyncio
async def test_create_scopes_org_from_context():
    conn = FakeConn()
    await create_project(conn, org_id=ORG, user_id=USER,
                         name="Waqar", idea="An illustrative abaya brand")
    query, args = conn.calls[0]
    assert "org_id" in query
    assert args[0] == uuid.UUID(ORG)
    assert args[1] == uuid.UUID(USER)


@pytest.mark.asyncio
async def test_read_queries_always_scope_org():
    conn = FakeConn()
    await list_projects(conn, org_id=ORG)
    await get_project(conn, org_id=ORG, project_id=PROJECT)
    for query, args in conn.calls:
        assert "org_id=$" in query
        assert uuid.UUID(ORG) in args


@pytest.mark.asyncio
async def test_stage_update_uses_compare_and_swap():
    conn = FakeConn()
    result = await advance_project(conn, org_id=ORG, project_id=PROJECT,
                                   actor_user_id=USER)
    assert result["stage"] == "FEASIBILITY"
    query, args = conn.calls[-1]
    assert "org_id=$2 AND stage=$6" in query
    assert args[-1] == "IDEA"


@pytest.mark.asyncio
async def test_approval_cannot_skip_review():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await advance_project(conn, org_id=ORG, project_id=PROJECT,
                              actor_user_id=USER, approve=True)
    assert len(conn.calls) == 1


@pytest.mark.asyncio
async def test_invalid_idea_does_not_write():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await create_project(conn, org_id=ORG, user_id=USER,
                             name="Waqar", idea="short")
    assert not conn.calls
