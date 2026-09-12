from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import maxxvoice.api.router as maxx_router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(maxx_router.router)
    return TestClient(app)


def test_unknown_workflow_job_returns_404(client: TestClient) -> None:
    response = client.get("/maxxvoice/jobs/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown workflow job: does-not-exist"


@pytest.mark.asyncio
async def test_article_podcast_endpoint_creates_job(monkeypatch, client: TestClient) -> None:
    class FakePlan:
        def to_dict(self):
            return {"version": "1", "segments": []}

    class FakePlanner:
        def plan(self, *args, **kwargs):
            return FakePlan()

    class FakeResult:
        def to_dict(self):
            return {"status": "completed", "final_artifact": None}

    class FakeRenderer:
        async def render(self, *args, **kwargs):
            return FakeResult()

    monkeypatch.setattr(maxx_router, "ArticlePodcastPlanner", FakePlanner)
    monkeypatch.setattr(maxx_router, "ArticlePodcastRenderer", FakeRenderer)

    response = client.post(
        "/maxxvoice/workflows/article-podcast",
        json={"article": "A short article for the API test."},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["workflow"] == "article-podcast"
    assert payload["status"] in {"queued", "running", "completed"}
    assert payload["id"]

    # Let the background task advance without depending on a particular
    # scheduler interleaving in the HTTP test client.
    await asyncio.sleep(0)
    job = maxx_router._workflow_store.require(payload["id"])
    assert job.status.value in {"running", "completed"}
