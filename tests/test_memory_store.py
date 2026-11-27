"""Persistent memory and semantic-ranking contracts without network/model access."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.memory_store import MemoryStore


def vector(first, second=0):
    return [first, second] + [0.0] * 382


def test_store_persists_exact_facts_and_metadata_without_loading_model(tmp_path):
    def offline(_):
        raise AssertionError("Saving/recent reads must not require model downloads")
    store = MemoryStore(tmp_path, embedder=offline)
    store.add(ids=["id-a"], documents=["Grüezi\nexact text"], metadatas=[{"timestamp": "2026-01-01", "zero": 0, "flag": False}])
    assert store.count() == 1
    reopened = MemoryStore(tmp_path, embedder=offline)
    assert reopened.get() == {"ids": ["id-a"], "documents": ["Grüezi\nexact text"], "metadatas": [{"timestamp": "2026-01-01", "zero": 0, "flag": False}]}
    assert (tmp_path / "jarvis_memory.sqlite3").stat().st_mode & 0o777 == 0o600


def test_semantic_query_uses_squared_l2_and_reuses_cached_document_vectors(tmp_path):
    calls = []
    def encode(texts):
        calls.append(list(texts))
        return [vector(0, 1) if text == "other" else vector(1) for text in texts]
    store = MemoryStore(tmp_path, embedder=encode)
    store.add(ids=["same", "other"], documents=["same", "other"], metadatas=[{}, {}])
    result = store.query(query_texts=["paraphrase"], n_results=5)
    assert result["ids"] == [["same", "other"]]
    assert result["distances"] == [[0.0, 2.0]]
    assert result["documents"] == [["same", "other"]]
    assert set(calls[0]) == {"same", "other", "paraphrase"}
    assert MemoryStore(tmp_path, embedder=encode).query(query_texts=["another query"], n_results=1)["ids"] == [["same"]]
    assert calls[-1] == ["another query"]


def test_empty_store_does_not_download_model_and_duplicate_batch_is_atomic(tmp_path):
    store = MemoryStore(tmp_path, embedder=lambda _: pytest.fail("No model needed"))
    assert store.query(query_texts=["query"], n_results=5)["documents"] == [[]]
    store.add(ids=["old"], documents=["old"], metadatas=[{}])
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        store.add(ids=["new", "old"], documents=["new", "replacement"], metadatas=[{}, {}])
    assert store.get()["ids"] == ["old"]
    store.delete(ids=["old"])
    assert MemoryStore(tmp_path).count() == 0


def test_parallel_saves_are_retained(tmp_path):
    store = MemoryStore(tmp_path)
    def save(number):
        store.add(ids=[str(number)], documents=[str(number)], metadatas=[{}])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(20)))
    assert store.count() == 20


def test_invalid_embedding_does_not_corrupt_documents(tmp_path):
    store = MemoryStore(tmp_path, embedder=lambda texts: [[float("nan")] * 384 for _ in texts])
    store.add(ids=["a"], documents=["fact"], metadatas=[{}])
    with pytest.raises(ValueError, match="embedding"):
        store.query(query_texts=["query"])
    assert store.get()["documents"] == ["fact"]
    with sqlite3.connect(tmp_path / "jarvis_memory.sqlite3") as db:
        assert db.execute("SELECT embedding FROM memories").fetchone() == (None,)


def test_legacy_import_is_verified_once_and_deletions_are_not_resurrected(tmp_path, monkeypatch):
    from app import memory_store
    source = tmp_path / "chroma.sqlite3"
    source.write_bytes(b"untouched source")
    backed_up = []
    def backup(src, dest):
        backed_up.append((src, dest))
        dest.write_bytes(src.read_bytes())
        return dest
    monkeypatch.setattr(memory_store, "backup_legacy_database", backup)
    monkeypatch.setattr(memory_store, "read_legacy_memories", lambda path: [("legacy", "old fact", {"timestamp": "2025-01-01"})])
    store = MemoryStore(tmp_path)
    assert store.get()["ids"] == ["legacy"]
    assert backed_up and backed_up[0][1].read_bytes() == source.read_bytes()
    store.delete(ids=["legacy"])
    assert MemoryStore(tmp_path).count() == 0
    assert len(backed_up) == 1
    assert source.read_bytes() == b"untouched source"


def test_failed_migration_can_retry_without_partial_import(tmp_path, monkeypatch):
    from app import memory_store
    source = tmp_path / "chroma.sqlite3"
    source.write_bytes(b"legacy")
    monkeypatch.setattr(memory_store, "backup_legacy_database", lambda src, dest: dest)
    monkeypatch.setattr(memory_store, "read_legacy_memories", lambda path: [("dup", "a", {}), ("dup", "b", {})])
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        MemoryStore(tmp_path)
    monkeypatch.setattr(memory_store, "read_legacy_memories", lambda path: [("fixed", "a", {})])
    assert MemoryStore(tmp_path).get()["ids"] == ["fixed"]
