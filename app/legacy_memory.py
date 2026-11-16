"""Read-only import and verified backup helpers for legacy Chroma memory."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3


_COLLECTION = "long_term_memory"
_METADATA_SEGMENT = "urn:chroma:segment/metadata/sqlite"
_REQUIRED_COLUMNS = {
    "collections": {"id", "name", "dimension"},
    "segments": {"id", "type", "scope", "collection"},
    "embeddings": {"id", "segment_id", "embedding_id", "created_at"},
    "embedding_metadata": {
        "id", "key", "string_value", "int_value", "float_value", "bool_value"
    },
}


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _validate_schema(db: sqlite3.Connection) -> None:
    for table, required in _REQUIRED_COLUMNS.items():
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        if not exists or not required <= columns:
            raise ValueError("unsupported legacy Chroma schema")


def _metadata_value(row: tuple) -> object:
    key, string_value, int_value, float_value, bool_value = row
    values = [string_value, int_value, float_value, bool_value]
    present = [value is not None for value in values]
    if sum(present) != 1:
        raise ValueError("malformed legacy metadata")
    if string_value is not None:
        if not isinstance(string_value, str):
            raise ValueError("malformed legacy metadata")
        return string_value
    if int_value is not None:
        if not isinstance(int_value, int):
            raise ValueError("malformed legacy metadata")
        return int_value
    if float_value is not None:
        if not isinstance(float_value, (int, float)):
            raise ValueError("malformed legacy metadata")
        return float(float_value)
    if bool_value not in (0, 1):
        raise ValueError("malformed legacy metadata")
    return bool(bool_value)


def read_legacy_memories(source: Path) -> list[tuple[str, str, dict]]:
    """Return legacy IDs, documents and exact scalar user metadata."""
    try:
        with closing(_open_readonly(Path(source))) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            _validate_schema(db)
            collections = db.execute(
                "SELECT id,dimension FROM collections WHERE name=?", (_COLLECTION,)
            ).fetchall()
            if len(collections) > 1:
                raise ValueError("ambiguous legacy memory collection")
            if not collections:
                return []
            collection_id, dimension = collections[0]
            if not isinstance(collection_id, str) or not collection_id:
                raise ValueError("invalid legacy collection ID")
            if dimension not in (None, 384):
                raise ValueError("unsupported legacy memory embedding dimension")

            rows = db.execute(
                "SELECT id,type,scope FROM segments WHERE collection=? ORDER BY id",
                (collection_id,),
            ).fetchall()
            segment_ids = []
            for segment_id, segment_type, scope in rows:
                if scope == "METADATA":
                    if segment_type != _METADATA_SEGMENT:
                        raise ValueError("unsupported legacy metadata segment")
                    if not isinstance(segment_id, str) or not segment_id:
                        raise ValueError("invalid legacy metadata segment ID")
                    segment_ids.append(segment_id)
            if not segment_ids:
                raise ValueError("legacy memory metadata segment is missing")

            memories = []
            seen_ids = set()
            for segment_id in segment_ids:
                embeddings = db.execute(
                    "SELECT id,embedding_id FROM embeddings WHERE segment_id=? ORDER BY id",
                    (segment_id,),
                ).fetchall()
                for row_id, memory_id in embeddings:
                    if not isinstance(memory_id, str) or not memory_id or memory_id in seen_ids:
                        raise ValueError("invalid or duplicate legacy memory ID")
                    seen_ids.add(memory_id)
                    metadata = {}
                    document = None
                    values = db.execute(
                        "SELECT key,string_value,int_value,float_value,bool_value "
                        "FROM embedding_metadata WHERE id=? ORDER BY key",
                        (row_id,),
                    ).fetchall()
                    for item in values:
                        key = item[0]
                        if not isinstance(key, str) or not key:
                            raise ValueError("malformed legacy metadata key")
                        value = _metadata_value(item)
                        if key == "chroma:document":
                            if not isinstance(value, str):
                                raise ValueError("legacy document is not text")
                            document = value
                        elif key in metadata:
                            raise ValueError("duplicate legacy metadata key")
                        else:
                            metadata[key] = value
                    if document is None:
                        raise ValueError("legacy memory document is missing")
                    memories.append((memory_id, document, metadata))
            return memories
    except ValueError:
        raise
    except (OSError, sqlite3.Error):
        raise ValueError("legacy Chroma database is unreadable") from None


def backup_legacy_database(source: Path, destination: Path) -> Path:
    """Create an exclusive, integrity-checked SQLite snapshot without source writes."""
    destination = Path(destination)
    created = False
    try:
        with closing(_open_readonly(Path(source))) as db:
            db.execute("PRAGMA query_only=ON")
            _validate_schema(db)
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            os.close(descriptor)
            created = True
            backup = sqlite3.connect(destination)
            try:
                db.backup(backup)
                result = backup.execute("PRAGMA integrity_check").fetchone()
                if result != ("ok",):
                    raise ValueError("legacy Chroma backup integrity check failed")
            finally:
                backup.close()
        return destination
    except FileExistsError:
        raise
    except ValueError:
        if created:
            destination.unlink(missing_ok=True)
        raise
    except (OSError, sqlite3.Error):
        if created:
            destination.unlink(missing_ok=True)
        raise ValueError("legacy Chroma backup failed") from None
