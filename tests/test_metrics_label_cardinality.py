"""HTTP metrics are labelled by route template, not by the raw path.

Each anonymous request to a new unique path used to add a permanent key to
the in-process metrics dicts, so memory grew without bound.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from fastapi.testclient import TestClient

from app.routers import metrics


def test_unique_paths_do_not_create_new_metric_keys():
    from app.factory import create_app
    client = TestClient(create_app(), raise_server_exceptions=False)
    metrics.http_requests_total.clear()
    for i in range(25):
        client.get(f"/probe{i}/x{i}", follow_redirects=False)
    labels = {key[1] for key in metrics.http_requests_total}
    assert not any("probe" in label for label in labels), labels
    assert len(labels) <= 2, labels
