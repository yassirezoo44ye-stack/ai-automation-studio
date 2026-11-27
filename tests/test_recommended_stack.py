import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import recommended_stack as rs
from app.routers import build


class Pool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(build.router)
    with patch.object(build, 'get_pool', return_value=Pool()), patch.object(build, 'owner_user_id', AsyncMock(return_value=uuid.uuid4())):
        yield TestClient(app, follow_redirects=False)


def test_defaults_are_neutral_non_referral(monkeypatch):
    monkeypatch.delenv('RECOMMENDED_STACK_JSON', raising=False)
    assert rs.catalogue() and not any(e['referral'] for e in rs.catalogue())


def test_invalid_entries_are_dropped(monkeypatch):
    good = {'id': 'a', 'category': 'hosting', 'name': 'A', 'url': 'https://a.example/?ref=1', 'referral': True}
    bad = [{**good, 'id': 'b', 'url': 'http://b.example'}, {**good, 'id': 'c', 'url': 'https://u:p@c.example'},
           {**good, 'id': 'd', 'category': 'payments'}, {**good, 'id': 'a'}, 'x']
    monkeypatch.setenv('RECOMMENDED_STACK_JSON', json.dumps([good, *bad]))
    assert [e['id'] for e in rs.catalogue()] == ['a']


def test_list_hides_urls_and_marks_referral(client, monkeypatch):
    monkeypatch.setenv('RECOMMENDED_STACK_JSON', json.dumps([{'id': 'a', 'category': 'hosting', 'name': 'A', 'url': 'https://a.example/?ref=1', 'referral': True}]))
    items = client.get('/api/recommended-stack').json()['items']
    assert items == [{'id': 'a', 'category': 'hosting', 'name': 'A', 'referral': True}]


def test_click_returns_only_configured_urls(client, monkeypatch):
    monkeypatch.setenv('RECOMMENDED_STACK_JSON', json.dumps([{'id': 'a', 'category': 'hosting', 'name': 'A', 'url': 'https://a.example/?ref=1'}]))
    assert client.post('/api/recommended-stack/click/a').json() == {'url': 'https://a.example/?ref=1'}
    assert client.post('/api/recommended-stack/click/https%3A%2F%2Fevil.example').status_code == 404
