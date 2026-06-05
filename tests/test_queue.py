"""Unit tests for Redis anomaly job dispatch."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestor_service import config, queue


class _FakeRedis:
    def __init__(self):
        self.adds: list[tuple] = []
        self.groups: list[tuple] = []

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.adds.append((name, fields, maxlen, approximate))
        return "1717600000000-0"

    def xgroup_create(self, name, groupname, id="0", mkstream=False):
        self.groups.append((name, groupname, id, mkstream))


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
    assert name == config.anomaly_stream_key()
    assert fields["anomaly_id"] == "ANOM-99"
    assert maxlen == config.anomaly_stream_maxlen()
    assert approximate is True


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
    assert fake.groups == [
        (config.anomaly_stream_key(), config.anomaly_consumer_group(), "0", True)
    ]


def test_ensure_anomaly_stream_skipped_for_stub(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setenv("AGENT_DISPATCH", "stub")
    monkeypatch.setattr(queue, "_redis", lambda: fake)
    queue.ensure_anomaly_stream()
    assert fake.groups == []
