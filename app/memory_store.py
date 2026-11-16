"""Private SQLite memory with local semantic ranking and read-only legacy import."""

from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .legacy_memory import backup_legacy_database, read_legacy_memories
from .memory_embeddings import MiniLMEncoder, MODEL_ID


class MemoryStore:
    """A single local collection; no HTTP server or executable model configuration."""

    def __init__(self, directory, *, embedder=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "jarvis_memory.sqlite3"
        if self.path.is_symlink():
            raise ValueError("The memory database must not be a symlink")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        self.path.chmod(0o600)
        self._embed = embedder if embedder is not None else MiniLMEncoder(directory / "models")
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, document TEXT NOT NULL, metadata TEXT NOT NULL, embedding TEXT, model_id TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("SELECT value FROM store_metadata WHERE key='format_version'").fetchone()
            if version is not None:
                if version[0] != "1":
                    raise ValueError("Unsupported memory database version")
                return
            if db.execute("SELECT count(*) FROM memories").fetchone()[0]:
                raise ValueError("Memory database is missing its format version")
            legacy = directory / "chroma.sqlite3"
            if legacy.exists():
                backups = directory / "legacy_backups"
                backups.mkdir(mode=0o700, exist_ok=True)
                backup = backups / ("chroma-" + uuid4().hex + ".sqlite3")
                backup_legacy_database(legacy, backup)
                rows = read_legacy_memories(backup)
                db.executemany("INSERT INTO memories (id, document, metadata) VALUES (?, ?, ?)", self._rows(rows))
                db.execute("INSERT INTO store_metadata VALUES ('legacy_backup', ?)", (str(backup),))
                db.execute("INSERT INTO store_metadata VALUES ('legacy_imported_count', ?)", (str(len(rows)),))
            db.execute("INSERT INTO store_metadata VALUES ('format_version', '1')")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def _rows(rows):
        result = []
        for identifier, document, metadata in rows:
            if not isinstance(identifier, str) or not identifier or not isinstance(document, str) or not isinstance(metadata, dict):
                raise ValueError("Invalid memory id, document or metadata")
            result.append((identifier, document, json.dumps(metadata, ensure_ascii=False, allow_nan=False)))
        return result

    def add(self, *, ids, documents, metadatas=None):
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if not len(ids) == len(documents) == len(metadatas):
            raise ValueError("Memory ids, documents and metadata must have equal lengths")
        rows = self._rows(zip(ids, documents, metadatas))
        with closing(self._connect()) as db, db:
            db.executemany("INSERT INTO memories (id, document, metadata) VALUES (?, ?, ?)", rows)

    def get(self, *, include=None):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id, document, metadata FROM memories ORDER BY rowid").fetchall()
        return {"ids": [row[0] for row in rows], "documents": [row[1] for row in rows], "metadatas": [json.loads(row[2]) for row in rows]}

    def delete(self, *, ids):
        with closing(self._connect()) as db, db:
            db.executemany("DELETE FROM memories WHERE id=?", ((identifier,) for identifier in ids))

    def count(self):
        with closing(self._connect()) as db:
            return db.execute("SELECT count(*) FROM memories").fetchone()[0]

    @staticmethod
    def _vector(value):
        try:
            vector = [float(number) for number in value]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid memory embedding") from exc
        if len(vector) != 384 or not all(math.isfinite(number) for number in vector):
            raise ValueError("Invalid memory embedding dimensions or values")
        return vector

    def query(self, *, query_texts, n_results=5, include=None):
        if not isinstance(n_results, int) or isinstance(n_results, bool) or n_results < 1:
            raise ValueError("n_results must be a positive integer")
        if not all(isinstance(text, str) and text.strip() for text in query_texts):
            raise ValueError("Memory queries must be nonempty text")
        result = {key: [] for key in ("ids", "documents", "metadatas", "distances")}
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id, document, metadata, embedding, model_id FROM memories ORDER BY id").fetchall()
        if not rows:
            return {key: [[] for _ in query_texts] for key in result}
        missing = [row for row in rows if row[3] is None or row[4] != MODEL_ID]
        texts = list(query_texts) + [row[1] for row in missing]
        encoded = list(self._embed(texts))
        if len(encoded) != len(texts):
            raise ValueError("Incorrect number of memory embeddings")
        vectors = [self._vector(value) for value in encoded]
        recovered = {row[0]: vector for row, vector in zip(missing, vectors[len(query_texts):])}
        with closing(self._connect()) as db, db:
            db.executemany(
                "UPDATE memories SET embedding=?, model_id=? WHERE id=? AND document=?",
                ((json.dumps(recovered[row[0]], allow_nan=False), MODEL_ID, row[0], row[1]) for row in missing),
            )
        documents = [(row, recovered[row[0]] if row[0] in recovered else self._vector(json.loads(row[3]))) for row in rows]
        # ponytail: exact linear search suits personal memory; index only if measured volume warrants it.
        for query in vectors[:len(query_texts)]:
            ranked = sorted(
                ((math.fsum((a - b) ** 2 for a, b in zip(query, vector)), row) for row, vector in documents),
                key=lambda item: (item[0], item[1][0]),
            )[:n_results]
            result["ids"].append([row[0] for _, row in ranked])
            result["documents"].append([row[1] for _, row in ranked])
            result["metadatas"].append([json.loads(row[2]) for _, row in ranked])
            result["distances"].append([distance for distance, _ in ranked])
        return result
