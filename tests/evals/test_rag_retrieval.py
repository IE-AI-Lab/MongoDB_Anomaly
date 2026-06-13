from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from ingestor_service.services import rag
from scripts.knowledge_seed import KNOWLEDGE_SEED
from tests.evals.cases import RAG_EVAL_CASES, RagEvalCase
from tests.fakes import FakeDB


def _seed_docs() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    docs: list[dict[str, Any]] = []
    for idx, entry in enumerate(KNOWLEDGE_SEED):
        docs.append(
            {
                "_id": f"mongo-kb-{idx}",
                "document_id": f"seed-{idx:03d}",
                "source_file": "scripts/knowledge_seed.py",
                "section_title": entry["section_title"],
                "equipment_type": entry["equipment_type"],
                "associated_error_codes": entry["associated_error_codes"],
                "text_content": entry["text_content"],
                "chunk_index": 0,
                "is_active": True,
                "ingested_at_utc": now,
                "schema_version": 1,
            }
        )
    return docs


class CapturingKnowledgeCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs
        self.last_pipeline: list[dict[str, Any]] | None = None

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.last_pipeline = pipeline
        vector = pipeline[0]["$vectorSearch"]
        pre_filter = vector["filter"]
        k = vector["limit"]
        equipment_type = pre_filter.get("equipment_type")
        error_codes = pre_filter.get("associated_error_codes", {}).get("$in", [])

        out: list[dict[str, Any]] = []
        for doc in self.docs:
            if not doc.get("is_active"):
                continue
            if equipment_type and doc.get("equipment_type") not in (equipment_type, "any"):
                continue
            if error_codes and not any(code in doc.get("associated_error_codes", []) for code in error_codes):
                continue
            out.append({k: v for k, v in doc.items() if k != "_id"})
        return out[:k]

    def find(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used in these tests
        raise AssertionError("find() should not be used when aggregate returns docs")


@pytest.mark.parametrize("case", RAG_EVAL_CASES, ids=[c.name for c in RAG_EVAL_CASES])
def test_rag_cases_return_docs_and_build_expected_filter(monkeypatch: pytest.MonkeyPatch, case: RagEvalCase):
    collection = CapturingKnowledgeCollection(_seed_docs())
    monkeypatch.setattr(rag, "col", lambda _name: collection)

    docs = rag.search_knowledge(
        case.query,
        equipment_type=case.equipment_type,
        error_codes=list(case.error_codes),
        k=5,
    )

    assert docs, f"expected at least one retrieval for case={case.name}"
    assert collection.last_pipeline is not None

    vector_search = collection.last_pipeline[0]["$vectorSearch"]
    assert vector_search["query"] == case.query
    assert vector_search["filter"]["is_active"] is True
    assert vector_search["filter"]["equipment_type"] == case.equipment_type
    assert vector_search["filter"]["associated_error_codes"] == {"$in": list(case.error_codes)}


def test_rag_fallback_returns_docs_when_vector_search_unavailable(monkeypatch: pytest.MonkeyPatch):
    db = FakeDB()
    db.add_collection("knowledge_base", _seed_docs())
    collection = db("knowledge_base")
    monkeypatch.setattr(rag, "col", lambda _name: collection)

    docs = rag.search_knowledge(
        "coolant loop flow issue",
        equipment_type="coolant_loop",
        error_codes=["FLOW_LOW"],
        k=3,
    )

    assert docs
    assert all(doc["equipment_type"] == "coolant_loop" for doc in docs)
    assert all("FLOW_LOW" in doc["associated_error_codes"] for doc in docs)
