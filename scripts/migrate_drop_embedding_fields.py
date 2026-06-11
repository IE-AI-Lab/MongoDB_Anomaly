"""One-off migration: drop pre-autoEmbed embedding fields from knowledge_base.

Before the Voyage AI Automated Embedding migration, each knowledge_base doc
stored a precomputed vector and its model metadata:

    text_embedding, embedding_model, embedding_dimensions

Atlas now generates embeddings from `text_content` at index/query time, so those
fields are dead weight (and `text_embedding` is a large array bloating every
doc). This script $unsets them. It is idempotent — running it again on a clean
collection is a no-op (modified_count = 0).

Usage:
    python -m scripts.migrate_drop_embedding_fields

Requires MONGO_URI and DB_NAME in the environment (.env is loaded).
"""

from __future__ import annotations

import os
from typing import Any

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

STALE_FIELDS = ("text_embedding", "embedding_model", "embedding_dimensions")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    load_dotenv()
    mongo_uri = require_env("MONGO_URI")
    db_name = require_env("DB_NAME")

    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10_000,
    )
    try:
        client.admin.command("ping")
        knowledge_base = client[db_name]["knowledge_base"]

        # Only touch docs that still carry at least one stale field.
        query = {"$or": [{field: {"$exists": True}} for field in STALE_FIELDS]}
        affected = knowledge_base.count_documents(query)

        result = knowledge_base.update_many(
            query, {"$unset": {field: "" for field in STALE_FIELDS}}
        )
        print(
            f"knowledge_base: {affected} doc(s) had stale embedding fields; "
            f"modified {result.modified_count}."
        )
        if affected == 0:
            print("Nothing to migrate — collection is already clean.")
    except PyMongoError as exc:
        raise RuntimeError(f"Migration failed: {exc}") from exc
    finally:
        client.close()


if __name__ == "__main__":
    main()
