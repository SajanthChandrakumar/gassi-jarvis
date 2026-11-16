import hashlib
import sqlite3
import stat

import pytest

from app.legacy_memory import backup_legacy_database, read_legacy_memories


SCHEMA = """
CREATE TABLE collections (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, dimension INTEGER,
    database_id TEXT NOT NULL, config_json_str TEXT, schema_str TEXT,
    UNIQUE (name, database_id)
);
CREATE TABLE segments (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, scope TEXT NOT NULL,
    collection TEXT NOT NULL
);
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL, embedding_id TEXT NOT NULL,
    seq_id BLOB NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (segment_id, embedding_id)
);
CREATE TABLE embedding_metadata (
    id INTEGER, key TEXT NOT NULL, string_value TEXT, int_value INTEGER,
    float_value REAL, bool_value INTEGER, PRIMARY KEY (id, key)
);
"""
METADATA_TYPE = "urn:chroma:segment/metadata/sqlite"


def make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO collections (id,name,database_id) VALUES (?,?,?)",
        ("target", "long_term_memory", "db-1"),
    )
    conn.execute(
        "INSERT INTO segments (id,type,scope,collection) VALUES (?,?,?,?)",
        ("meta-target", METADATA_TYPE, "METADATA", "target"),
    )
    conn.commit()
    return conn


def add_memory(conn, row_id=1, memory_id="mem-1", document="Grüezi 🐕", metadata=None):
    conn.execute(
        "INSERT INTO embeddings (id,segment_id,embedding_id,seq_id,created_at) "
        "VALUES (?,?,?,?,?)",
        (row_id, "meta-target", memory_id, str(row_id).encode(), "2026-11-16 09:30:00"),
    )
    values = {"chroma:document": (document, None, None, None)}
    values.update(metadata or {})
    conn.executemany(
        "INSERT INTO embedding_metadata (id,key,string_value,int_value,float_value,bool_value) "
        "VALUES (?,?,?,?,?,?)",
        [(row_id, key, *value) for key, value in values.items()],
    )


def snapshot(path):
    return {
        suffix: hashlib.sha256(path.with_name(path.name + suffix).read_bytes()).hexdigest()
        for suffix in ("", "-wal")
        if path.with_name(path.name + suffix).exists()
    }


def test_reads_only_named_collection_and_preserves_typed_metadata(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    add_memory(
        conn,
        metadata={
            "timestamp": ("2026-11-16T10:30:00+01:00", None, None, None),
            "count": (None, 0, None, None),
            "enabled": (None, None, None, 0),
            "score": (None, None, 0.0, None),
        },
    )
    conn.execute("INSERT INTO collections (id,name,database_id) VALUES (?,?,?)", ("other", "notes", "db-1"))
    conn.execute("INSERT INTO segments (id,type,scope,collection) VALUES (?,?,?,?)", ("meta-other", METADATA_TYPE, "METADATA", "other"))
    conn.execute("INSERT INTO embeddings (id,segment_id,embedding_id,seq_id) VALUES (?,?,?,?)", (2, "meta-other", "other-id", b"2"))
    conn.execute("INSERT INTO embedding_metadata (id,key,string_value) VALUES (?,?,?)", (2, "chroma:document", "must not import"))
    conn.commit()
    conn.close()

    assert read_legacy_memories(source) == [
        (
            "mem-1",
            "Grüezi 🐕",
            {
                "timestamp": "2026-11-16T10:30:00+01:00",
                "count": 0,
                "enabled": False,
                "score": 0.0,
            },
        )
    ]


def test_empty_matching_collection_returns_empty_list(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    make_db(source).close()
    assert read_legacy_memories(source) == []


def test_rejects_same_named_collections_in_multiple_databases(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    conn.execute("INSERT INTO collections (id,name,database_id) VALUES (?,?,?)", ("duplicate", "long_term_memory", "db-2"))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="ambiguous"):
        read_legacy_memories(source)


def test_rejects_collection_dimension_other_than_minilm_or_unset(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    conn.execute("UPDATE collections SET dimension=768 WHERE id='target'")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="dimension"):
        read_legacy_memories(source)


def test_rejects_memory_without_document(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    conn.execute("INSERT INTO embeddings (id,segment_id,embedding_id,seq_id) VALUES (?,?,?,?)", (1, "meta-target", "mem-1", b"1"))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="document"):
        read_legacy_memories(source)


def test_rejects_invalid_or_colliding_memory_ids(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    add_memory(conn, memory_id="")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="ID"):
        read_legacy_memories(source)


def test_rejects_malformed_typed_metadata(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    add_memory(conn, metadata={"bad": ("value", 1, None, None)})
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="metadata"):
        read_legacy_memories(source)


def test_read_does_not_change_source_database_bytes(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    conn = make_db(source)
    add_memory(conn)
    conn.commit()
    conn.close()
    before = snapshot(source)
    read_legacy_memories(source)
    assert snapshot(source) == before


def test_backup_includes_committed_wal_and_refuses_existing_destination(tmp_path):
    source = tmp_path / "chroma.sqlite3"
    writer = make_db(source)
    writer.execute("PRAGMA journal_mode=WAL")
    add_memory(writer, metadata={"timestamp": ("2026-11-16T09:30:00Z", None, None, None)})
    writer.commit()
    before = snapshot(source)
    destination = tmp_path / "legacy-backup.sqlite3"

    assert backup_legacy_database(source, destination) == destination
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert read_legacy_memories(destination) == [
        ("mem-1", "Grüezi 🐕", {"timestamp": "2026-11-16T09:30:00Z"})
    ]
    backup_db = sqlite3.connect(destination)
    assert backup_db.execute("SELECT created_at FROM embeddings").fetchone() == (
        "2026-11-16 09:30:00",
    )
    backup_db.close()
    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    backup_db = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    for table in ("collections", "segments", "embeddings", "embedding_metadata"):
        source_count = source_db.execute(f"SELECT count(*) FROM {table}").fetchone()
        backup_count = backup_db.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert backup_count == source_count
    source_db.close()
    backup_db.close()
    assert snapshot(source) == before
    with pytest.raises(FileExistsError):
        backup_legacy_database(source, destination)
    writer.close()


def test_rejects_unsupported_schema_without_creating_backup(tmp_path):
    source = tmp_path / "unsupported.sqlite3"
    sqlite3.connect(source).execute("CREATE TABLE something_else (id INTEGER)").connection.close()
    destination = tmp_path / "backup.sqlite3"
    with pytest.raises(ValueError, match="schema"):
        backup_legacy_database(source, destination)
    assert not destination.exists()
