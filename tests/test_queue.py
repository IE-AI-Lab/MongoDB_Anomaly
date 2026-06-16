"""Unit tests for Redis anomaly job dispatch."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestor_service.core import config
from ingestor_service.messaging import queue


class _FakeRedis:
    def __init__(self):
        self.adds: list[tuple] = []
        self.groups: list[tuple] = []
        self.deleted: list[str] = []
        self.lengths: dict[str, int] = {}

    def xlen(self, name):
        return self.lengths.get(name, 0)

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.adds.append((name, fields, maxlen, approximate))
        return "1717600000000-0"

    def xgroup_create(self, name, groupname, id="0", mkstream=False):
        self.groups.append((name, groupname, id, mkstream))

    def delete(self, name):
        self.deleted.append(name)
        return 1


@pytest.fixture(autouse=True)
def _reset_redis_client(monkeypatch):
    queue._redis_client = None
    monkeypatch.setenv("AGENT_DISPATCH", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


def test_stream_fields_stringify_values():
    doc = {
        "anomaly_id": "ANOM-1",
        "sensor_id": "SENS-1",
        "error_code": "TEMP_HIGH",
        "severity_type": "high",
        "severity_level": 10,
        "timestamp_utc": datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    }
    fields = queue._stream_fields(doc)
    assert fields["anomaly_id"] == "ANOM-1"
    assert fields["severity_level"] == "10"
    assert fields["timestamp_utc"].startswith("2026-06-05")


def test_publish_anomaly_job_xadd(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(queue, "_redis", lambda: fake)

    anomaly_doc = {
        "anomaly_id": "ANOM-99",
        "sensor_id": "SENS-VIB-001",
        "error_code": "VIBRATION_HIGH",
        "severity_type": "high",
        "severity_level": 8,
        "timestamp_utc": datetime.now(timezone.utc),
    }
    message_id = queue.publish_anomaly_job(anomaly_doc)

    assert message_id == "1717600000000-0"
    assert len(fake.adds) == 1
    name, fields, maxlen, approximate = fake.adds[0]
    # High severity routes to the high-priority stream.
    assert name == config.anomaly_stream_for_severity("high")
    assert name == "anomaly:high"
    assert fields["anomaly_id"] == "ANOM-99"
    assert fields["attempts"] == "0"
    assert maxlen == config.anomaly_stream_maxlen()
    assert approximate is True


def test_publish_routes_by_severity(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(queue, "_redis", lambda: fake)

    for severity, expected in [
        ("high", "anomaly:high"),
        ("medium", "anomaly:medium"),
        ("low", "anomaly:low"),
        ("", "anomaly:low"),  # unknown/missing falls back to lowest priority
    ]:
        fake.adds.clear()
        queue.publish_anomaly_job({"anomaly_id": "ANOM-1", "severity_type": severity})
        assert fake.adds[0][0] == expected


def test_publish_failure_does_not_raise(monkeypatch):
    class _BrokenRedis:
        def xadd(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(queue, "_redis", lambda: _BrokenRedis())
    result = queue.publish_anomaly_job({"anomaly_id": "ANOM-1"})
    assert result is None


def test_dispatch_stub_calls_handle_anomaly(monkeypatch):
    called = []
    monkeypatch.setenv("AGENT_DISPATCH", "stub")
    monkeypatch.setattr(queue, "handle_anomaly", lambda doc: called.append(doc))

    doc = {"anomaly_id": "ANOM-1"}
    queue.dispatch_anomaly(doc)
    assert called == [doc]


def test_dispatch_redis_calls_publish(monkeypatch):
    published = []
    monkeypatch.setenv("AGENT_DISPATCH", "redis")
    monkeypatch.setattr(queue, "publish_anomaly_job", lambda doc: published.append(doc) or "1-0")

    doc = {"anomaly_id": "ANOM-2"}
    queue.dispatch_anomaly(doc)
    assert published == [doc]


def test_ensure_anomaly_stream_creates_group(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(queue, "_redis", lambda: fake)
    queue.ensure_anomaly_stream()
    group = config.anomaly_consumer_group()
    assert fake.groups == [
        ("anomaly:high", group, "0", True),
        ("anomaly:medium", group, "0", True),
        ("anomaly:low", group, "0", True),
    ]


def test_ensure_anomaly_stream_skipped_for_stub(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setenv("AGENT_DISPATCH", "stub")
    monkeypatch.setattr(queue, "_redis", lambda: fake)
    queue.ensure_anomaly_stream()
    assert fake.groups == []


def test_stream_depths_reports_per_severity_and_dlq(monkeypatch):
    fake = _FakeRedis()
    fake.lengths = {
        "anomaly:high": 2,
        "anomaly:medium": 0,
        "anomaly:low": 5,
        "anomaly:dlq": 1,
    }
    monkeypatch.setattr(queue, "_redis", lambda: fake)

    result = queue.stream_depths()
    assert result["available"] is True
    assert result["streams"] == {"high": 2, "medium": 0, "low": 5}
    assert result["dlq"] == 1


def test_stream_depths_fail_open_when_not_redis(monkeypatch):
    monkeypatch.setenv("AGENT_DISPATCH", "stub")
    result = queue.stream_depths()
    assert result["available"] is False
    assert result["streams"] == {"high": 0, "medium": 0, "low": 0}
    assert result["dlq"] == 0


def test_reset_anomaly_streams_deletes_and_recreates(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(queue, "_redis", lambda: fake)
    monkeypatch.setenv("ANOMALY_STREAM_KEY", "anomaly:jobs")  # legacy key cleanup

    result = queue.reset_anomaly_streams()

    assert "anomaly:high" in fake.deleted
    assert "anomaly:medium" in fake.deleted
    assert "anomaly:low" in fake.deleted
    assert "anomaly:dlq" in fake.deleted
    assert "anomaly:jobs" in fake.deleted  # legacy
    assert result["consumer_groups_recreated"] is True
    group = config.anomaly_consumer_group()
    assert ("anomaly:high", group, "0", True) in fake.groups
