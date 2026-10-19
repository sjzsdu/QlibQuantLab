"""指标端点 /api/v1/metrics（阶段 8 · D8-1/D8-2）。

用**独立 app**（非 conftest 会话级 app）+ httpx ASGITransport：DB、缓存、
注册表全在同一个测试事件循环里，避免与 TestClient 的 portal 循环串池。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from conftest import make_settings
from qqlab.core.worker_heartbeat import write_heartbeat
from qqlab.main import create_app
from qqlab.models import Job, JobKind, JobStatus, Organization, User

_MEDIA = "text/plain"


def _client(app):  # noqa: ANN001, ANN201
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _scrape(app) -> str:  # noqa: ANN001, ANN201
    async with _client(app) as client:
        response = await client.get("/api/v1/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(_MEDIA)
    assert response.text.endswith("\n")
    return response.text


def _prod_settings(**overrides):  # noqa: ANN001, ANN201
    return make_settings(
        APP_ENV="production",
        AUTH_PROVIDER="casdoor",
        SESSION_COOKIE_SECURE=True,
        APP_JWT_SECRET="p" * 40,
        QLIB_SERVER_REDIS_HOST="redis",
        QLIB_SERVER_QUEUE_HOST="rabbitmq",
        CASDOOR_ISSUER="https://casdoor.example.com",
        CASDOOR_CLIENT_ID="cid",
        CASDOOR_CLIENT_SECRET="csecret",
        CASDOOR_REDIRECT_URI="http://localhost:3000/cb",
        **overrides,
    )


async def test_dev_scrape_exposes_red_queue_worker_sections() -> None:
    app = create_app(make_settings())
    async with _client(app) as client:
        live = await client.get("/api/v1/health/live")
        assert live.status_code == 200
        body = (await client.get("/api/v1/metrics")).text

    # RED：路由模板 + 状态码（scrape 请求自身在渲染之后才记录，不自增）
    assert 'qqlab_http_requests_total{method="GET",route="/api/v1/health/live",status="200"} 1' in body
    assert "# TYPE qqlab_http_request_duration_ms histogram" in body
    assert 'qqlab_http_request_duration_ms_count{method="GET",route="/api/v1/health/live"} 1' in body
    # 队列与 worker 两段 scrape 标志（现库无任务、无心跳）
    assert "qqlab_queue_scrape_ok 1" in body
    assert "qqlab_worker_scrape_ok 1" in body
    assert "qqlab_worker_up 0" in body
    assert "qqlab_worker_heartbeat_age_seconds" not in body
    assert "qqlab_worker_recycled_total 0" in body
    assert "# TYPE qqlab_jobs_depth gauge" in body


async def test_unmatched_route_labeled_unmatched() -> None:
    app = create_app(make_settings())
    async with _client(app) as client:
        missing = await client.get("/api/v1/no-such-endpoint")
        assert missing.status_code == 404
        body = (await client.get("/api/v1/metrics")).text
    assert 'route="unmatched"' in body
    assert 'status="404"' in body


async def test_worker_up_goes_1_with_fresh_heartbeat() -> None:
    app = create_app(make_settings())
    await write_heartbeat(app.state.container.cache, interval=10)
    body = await _scrape(app)
    assert "qqlab_worker_up 1" in body
    assert "qqlab_worker_heartbeat_age_seconds" in body


async def test_queue_metrics_reflect_jobs_table() -> None:
    app = create_app(make_settings())
    now = datetime.now(UTC)
    async with app.state.container.database.session() as session:
        org = Organization(slug="metrics-org", name="Metrics Org")
        session.add(org)
        await session.flush()
        user = User(username="metrics-user")
        session.add(user)
        await session.flush()
        session.add(
            Job(
                org_id=org.id,
                kind=JobKind.BACKTEST,
                status=JobStatus.QUEUED,
                payload={"k": 1},
                created_by=user.id,
            )
        )
        session.add(
            Job(
                org_id=org.id,
                kind=JobKind.BACKTEST,
                status=JobStatus.SUCCEEDED,
                payload={"k": 2},
                created_by=user.id,
                started_at=now - timedelta(seconds=30),
                finished_at=now - timedelta(seconds=10),
                created_at=now - timedelta(seconds=40),
            )
        )
        session.add(
            Job(
                org_id=org.id,
                kind=JobKind.TRAIN,
                status=JobStatus.FAILED,
                payload={"k": 3},
                created_by=user.id,
                started_at=now - timedelta(seconds=5),
                finished_at=now,
                created_at=now - timedelta(seconds=6),
            )
        )
        await session.commit()

    body = await _scrape(app)
    assert 'qqlab_jobs_depth{kind="backtest",status="queued"} 1' in body
    assert 'qqlab_jobs_finished_window{kind="backtest",status="succeeded"} 1' in body
    assert 'qqlab_jobs_finished_window{kind="train",status="failed"} 1' in body
    # 执行时长：backtest 20s、train 5s（窗口内 avg；样本 <5 不出 p95）
    assert 'qqlab_job_duration_seconds_avg{kind="backtest"} 20.000' in body
    assert 'qqlab_job_duration_seconds_avg{kind="train"} 5.000' in body
    assert 'qqlab_job_duration_seconds_p95' not in body
    # 排队等待：backtest 10s、train 1s
    assert 'qqlab_job_wait_seconds_avg{kind="backtest"} 10.000' in body


async def test_metrics_disabled_is_404_even_in_dev() -> None:
    app = create_app(make_settings(METRICS_ENABLED=False))
    async with _client(app) as client:
        response = await client.get("/api/v1/metrics")
    assert response.status_code == 404


async def test_production_requires_bearer_or_header_token() -> None:
    app = create_app(_prod_settings(METRICS_TOKEN="s3cret-token"))
    async with _client(app) as client:
        assert (await client.get("/api/v1/metrics")).status_code == 401
        wrong = await client.get("/api/v1/metrics", headers={"X-Metrics-Token": "nope"})
        assert wrong.status_code == 401
        ok_header = await client.get("/api/v1/metrics", headers={"X-Metrics-Token": "s3cret-token"})
        assert ok_header.status_code == 200
        ok_bearer = await client.get(
            "/api/v1/metrics", headers={"Authorization": "Bearer s3cret-token"}
        )
        assert ok_bearer.status_code == 200


async def test_production_without_token_fail_closed_404() -> None:
    app = create_app(_prod_settings(METRICS_TOKEN=""))
    async with _client(app) as client:
        response = await client.get(
            "/api/v1/metrics", headers={"Authorization": "Bearer anything"}
        )
    assert response.status_code == 404
