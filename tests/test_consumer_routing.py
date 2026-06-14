"""Unit tests for the worker's priority draining + retry/DLQ logic."""

from __future__ import annotations

from agent_worker import config, consumer


class _FakeRedis:
    def __init__(self, data: dict[str, list[tuple[str, dict[str, str]]]] | None = None):
        # data: {stream_key: [(message_id, fields), ...]}
        self.data: dict[str, list[tuple[str, dict[str, str]]]] = data or {}
        self.acks: list[tuple] = []
        self.adds: list[tuple[str, dict[str, str]]] = []

    def xreadgroup(self, groupname, consumername, streams, count=1, block=None):
        out = []
        for stream in streams:
            msgs = self.data.get(stream, [])
            if msgs:
                take, self.data[stream] = msgs[:count], msgs[count:]
                out.append((stream, take))
        return out

    def xack(self, stream, group, message_id):
        self.acks.append((stream, group, message_id))

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.adds.append((name, dict(fields)))
        return "9-0"


# --- priority draining ------------------------------------------------------

def test_next_batch_prefers_high_then_medium_then_low():
    fake = _FakeRedis(
        {
            "anomaly:high": [("1-0", {"anomaly_id": "H"})],
            "anomaly:medium": [("2-0", {"anomaly_id": "M"})],
            "anomaly:low": [("3-0", {"anomaly_id": "L"})],
        }
    )
    items = consumer._next_batch(fake, "g", "c", block_ms=10)
    assert items == [("anomaly:high", "1-0", {"anomaly_id": "H"})]


def test_next_batch_falls_through_to_medium_when_high_empty():
    fake = _FakeRedis({"anomaly:medium": [("2-0", {"anomaly_id": "M"})]})
    items = consumer._next_batch(fake, "g", "c", block_ms=10)
    assert items == [("anomaly:medium", "2-0", {"anomaly_id": "M"})]


def test_next_batch_empty_when_no_work():
    assert consumer._next_batch(_FakeRedis(), "g", "c", block_ms=10) == []


# --- retry + DLQ ------------------------------------------------------------

def test_handle_failure_requeues_with_incremented_attempts(monkeypatch):
    monkeypatch.setenv("ANOMALY_MAX_RETRIES", "3")
    fake = _FakeRedis()
    fields = {"anomaly_id": "A", "attempts": "0"}

    consumer._handle_failure(fake, "anomaly:high", "g", "1-0", fields)

    assert len(fake.adds) == 1
    name, requeued = fake.adds[0]
    assert name == "anomaly:high"  # back to its source stream
    assert requeued["attempts"] == "1"
    assert fake.acks == [("anomaly:high", "g", "1-0")]


def test_handle_failure_routes_to_dlq_when_exhausted(monkeypatch):
    monkeypatch.setenv("ANOMALY_MAX_RETRIES", "3")
    fake = _FakeRedis()
    fields = {"anomaly_id": "A", "attempts": "2"}  # this is the 3rd attempt

    consumer._handle_failure(fake, "anomaly:high", "g", "5-0", fields)

    assert len(fake.adds) == 1
    name, dead = fake.adds[0]
    assert name == config.anomaly_dlq_stream()
    assert name == "anomaly:dlq"
    assert dead["attempts"] == "3"
    assert dead["source_stream"] == "anomaly:high"
    assert "failed_at_utc" in dead
    assert fake.acks == [("anomaly:high", "g", "5-0")]
