# Embedded semantic memory

Jarvis stores facts in `JARVIS_BRAIN_DIR/jarvis_memory.sqlite3` using the Python
standard library. No memory server is started or contacted. The database is
created with owner-only permissions. Existing `save_memory`, `recall_memory`,
memory-count and recent-memory APIs keep their response contracts.

Semantic search uses the same all-MiniLM-L6-v2 ONNX model and normalized,
squared-L2 distances as the previous default Chroma collection. ONNX Runtime
and the tokenizer run locally; memory text is not sent to the model host.
Only the fixed model archive is downloaded, lazily at the first semantic
query. Its SHA-256 is checked before installation. Saving facts, counting and
listing recent entries do not require a model download. Embeddings are cached
with a model identifier and can be rebuilt from the retained facts.

The personal-memory store uses exact linear ranking. This avoids another
database/server dependency and is appropriate for modest personal collections;
very large collections will need a measured indexing decision.

## Existing Chroma data

The existing brain directory and Compose volume are deliberately retained.
`jarvis_chroma` and `/data/chroma` remain historical storage names, not a
Chroma process or runtime dependency. Do not rename/delete that volume during
this update.

Before a production rollout, stop the old application and take a normal volume
backup. Verify the update first against a copy of that volume. Never run old
and new writers concurrently against the same memory directory.

On first startup, if `chroma.sqlite3` is present and the new store has not been
initialized:

1. Create a new, read-only SQLite snapshot under `legacy_backups/`, including
   committed WAL records, and verify its integrity.
2. Read the `long_term_memory` collection from that snapshot without importing
   Chroma code. Preserve every fact's ID, document, scalar metadata and stored
   timestamp; other collections stay in the original archive.
3. Import all rows and the completion marker in one transaction. Invalid or
   unsupported legacy formats stop initialization; partial imports are rolled
   back and the original archive remains intact.
4. Rebuild search embeddings lazily with the same default model. The legacy
   vector index stays in the original archive; it is not treated as a new index.

The import runs once. Restarting cannot resurrect a fact deleted from the new
store. Duplicate IDs, ambiguous collection names and unsupported embedding
dimensions fail explicitly instead of silently discarding data. Import
counts and the snapshot path are recorded in `store_metadata` in the new DB.

## Recovery

Keep the original directory, verified snapshot, new database and model cache
until the new deployment is accepted. No repository test or CI job migrates a
production volume. For rollback, stop the new process and back up its complete
brain directory before restoring the old application/volume snapshot. Facts
added after cutover exist in the new SQLite database and must be reconciled
before resuming the old writer; restoring only the old snapshot does not include
those new facts. Do not delete the new database or backups during rollback.

Session history remains in the existing `JARVIS_SESSIONS_FILE`; this migration
does not change sessions, pending approvals, the device queue or research data.
