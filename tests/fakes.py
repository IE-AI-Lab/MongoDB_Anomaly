"""Small in-memory Mongo fakes used by route unit tests."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected:
                if actual is None or actual < expected["$gte"]:
                    return False
                continue
            if "$regex" in expected:
                if not isinstance(actual, str) or not re.search(expected["$regex"], actual):
                    return False
                continue
            if "$in" in expected:
                vals = expected["$in"]
                if isinstance(actual, list):
                    if not any(v in actual for v in vals):
                        return False
                elif actual not in vals:
                    return False
                continue
            return False

        # Mimic Mongo's "scalar in array field" behavior for a simple case.
        if isinstance(actual, list):
            if expected not in actual:
                return False
            continue

        if actual != expected:
            return False
    return True


def _apply_projection(doc: dict[str, Any], projection: dict[str, int] | None) -> dict[str, Any]:
    if not projection:
        return deepcopy(doc)
    out = deepcopy(doc)
    for key, value in projection.items():
        if value == 0:
            out.pop(key, None)
    return out


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def sort(self, field: str, direction: int) -> "FakeCursor":
        reverse = direction < 0
        self._docs.sort(key=lambda d: d.get(field), reverse=reverse)
        return self

    def skip(self, n: int) -> "FakeCursor":
        self._docs = self._docs[n:]
        return self

    def limit(self, n: int) -> "FakeCursor":
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


@dataclass
class _UpdateResult:
    matched_count: int
    modified_count: int = 0


@dataclass
class _DeleteResult:
    deleted_count: int


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None):
        self.docs = [deepcopy(d) for d in (docs or [])]

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, query):
                return deepcopy(doc)
        return None

    def find(self, query: dict[str, Any], projection: dict[str, int] | None = None) -> FakeCursor:
        rows = [_apply_projection(d, projection) for d in self.docs if _matches(d, query)]
        return FakeCursor(rows)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> _UpdateResult:
        for doc in self.docs:
            if _matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                return _UpdateResult(matched_count=1, modified_count=1)
        return _UpdateResult(matched_count=0)

    def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> _UpdateResult:
        matched = 0
        for doc in self.docs:
            if _matches(doc, query):
                matched += 1
                if "$set" in update:
                    doc.update(update["$set"])
        return _UpdateResult(matched_count=matched, modified_count=matched)

    def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(deepcopy(doc))

    def delete_one(self, query: dict[str, Any]) -> _DeleteResult:
        for i, doc in enumerate(self.docs):
            if _matches(doc, query):
                del self.docs[i]
                return _DeleteResult(deleted_count=1)
        return _DeleteResult(deleted_count=0)

    def delete_many(self, query: dict[str, Any]) -> _DeleteResult:
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, query)]
        return _DeleteResult(deleted_count=before - len(self.docs))


class FakeDB:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def add_collection(self, name: str, docs: list[dict[str, Any]]) -> None:
        self.collections[name] = FakeCollection(docs)

    def __call__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())
