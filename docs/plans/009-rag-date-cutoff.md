# Plan 009: RAG Date-Cutoff

Status (2026-10-16): steps 1-6 IMPLEMENTED and live-verified, including the missing-extension acceptance test (PASSED 2026-10-16,
single node); uncommitted; live rerun after the audit fix PASSED (2026-10-16); step 7 (final review, owner decisions) awaits the owner; the specs README row is added; the feature is NOT complete.
Spec: `docs/specs/009-rag-date-cutoff.md`.
GATE (spec section 10): each step needs explicit owner authorisation. The missing-extension test passed on the owner-provisioned
disposable database `alterfolio_novector_test` (not yet dropped); the feature is NOT complete.
Database policy (spec section 6): PostgreSQL with pgvector is authoritative for all pgvector-specific behaviour, migrations and integration
tests; SQLite is kept only for existing portable tests with meaningful non-vector coverage. Never drop the extension from
`alterfolio_test`; never use `academic_os` or `intrinsic_db` for destructive tests.

## Step 0: blocking verification (owner-assisted; nothing is guessed)
1. VERIFIED (owner-run read-only inspection, 2026-10-15): PostgreSQL 16.14, 127.0.0.1:5432, database `alterfolio_test`, role
   `alterfolio_test_user` (not superuser; database CREATE and schema USAGE).
2. VERIFIED (same inspection): pgvector 0.8.7 in schema `public`, owned by `postgres`. UNVERIFIED, non-blocking: the role that ran
   `CREATE EXTENSION`; the extension's absolute maximum dimension.
3. PROBE DONE (2026-10-15; does not pass the gate): live embed plus the controlled boundary probe; facts in spec section 10 (server
   digest equals the local manifest `0a109f42...e59f`, 768 finite values, HTTP 400 on oversize input, `prompt_eval_count` returned
   (evidence only)). GGUF header: `nomic-embed-text-v1.5`, `context_length` 2048 (file metadata).
3b. OWNER-CONFIRMED (2026-10-15): `MAX_CHUNK_TEXT_LENGTH` = 4,000 Python characters (chunks and queries, counted before the prefix; a
   product cap, not a token-safety guarantee; Ollama's HTTP 400 stays authoritative, spec section 7) and the prefix format
   `<prefix> <text>` with exactly one space. `\n` is recorded as a provisional chunk-combining separator, unused in 009. Not gate items
   (step 6 live tests): exact token limit, `search_query: ` prefix, unload/restart, real chunks.
3a. VERIFIED (owner-run, same inspection): `<=>` values and NaN for a zero vector, `CAST(:q AS vector)` named binding, a 768-dimension
   vector accepted. UNVERIFIED, non-blocking: invalid-input error texts and SQLSTATEs; the absolute dimension limit.
4. Done (2026-10-15): boundary amendment (spec section 5), httpx, exact scan with no vector index; recorded in CLAUDE.md s2-s4,
   `docs/design.md` and `tests/test_import_boundaries.py`.

## Steps (one at a time; focused tests, then the full suite)
1. `domain/retrieval.py`, limits in `domain/limits.py` (`MAX_CHUNK_TEXT_LENGTH = 4000`, owner-confirmed, step 0 item 3b); `tests/test_retrieval_domain.py`.
   IMPLEMENTED. The corrections required by the spec decisions of 2026-10-15 are present in code and tests: no `published_at`
   window (no `MIN/MAX_PUBLISHED_AT` in `domain/limits.py`), no score-order check in `SearchResult`, and `CutoffAudit` accepts
   violations > 0 with violations <= returned and returned - violations <= eligible. The owner explicitly authorised all three
   corrections (recorded 2026-10-16).
2. `providers/embedding/{__init__,port,ollama}.py` (port `embed(texts, role)`, role DOCUMENT or QUERY; the adapter applies the
   prefix and computes `embedding_config_id`, spec section 6) plus a fake embedder in tests; `tests/test_embedding_port.py`,
   `tests/test_embedding_ollama.py` (fake transport: exact URL and body with `model`, prefixed `input` and `truncate: false`; config id
   stable and changed by every identity field; `truncate: false` on DOCUMENT and QUERY requests; one request per call, no retry; missing model -> EMBEDDING_MODEL_MISSING;
   HTTP 400 context-length -> RetrievalInputError for each role; any other HTTP error, timeout or connection failure ->
   EMBEDDING_PROVIDER_UNAVAILABLE; NaN/inf/zero-norm -> NON_FINITE_EMBEDDING; empty, wrong or mixed length -> DIMENSION_MISMATCH;
   no determinable dimension -> DIMENSION_UNRESOLVED; vector count != input count -> EMBEDDING_PROVIDER_UNAVAILABLE; all returned as
   values, never raised, repaired or stored (spec section 7); digest mismatch). IMPLEMENTED (mocked HTTP only; live Ollama is
   step 6). Step 4 added the optional `EmbeddingBatch.model`, set by the adapter (spec section 5; owner-approved 2026-10-16).
3. `db/column_types.py` vector type, `models/chunk.py`, hand-written vector `TypeDecorator` (no new dependency), Alembic migration with dimension D and no vector index (exact scan),
   `repositories/chunks.py` (encode `[v,...]` text, never read the vector column back, order by distance; migration policy (spec section 6): require the extension, never
   CREATE EXTENSION, raise `VectorExtensionMissingError` (added to domain/retrieval.py; message starts VECTOR_EXTENSION_MISSING) if
   absent, downgrade drops only 009 objects; columns: `id` UUID, `chunk_index` INTEGER (a test asserts it agrees with
   MAX_CHUNK_INDEX = 2^31 - 1), `source_id` String(MAX_SOURCE_ID_LENGTH);
   SQLite approach (owner-approved 2026-10-15 as a design decision, not as approval to implement; PostgreSQL integration tests remain
   authoritative for vector casts, distance, ranking and extension behaviour): a TypeDecorator in db/column_types.py,
   following ExactDecimal and UTCDateTime, renders vector(768) on PostgreSQL and TEXT on SQLite only; it does not change the PostgreSQL
   schema; the TEXT form is test-only and has no vector semantics; SQLite repository tests cover only non-vector behaviour; the
   migration does not require the extension on SQLite; offline mode skips the runtime extension check and renders DDL only; existing
   SQLite and offline migration tests stay unmodified (editing an approved test needs owner approval));
   `tests/test_chunk_repository.py` (idempotency, conflict, incompatible identity, append-only, user isolation, cutoff filter,
   non-vector order (tie order and distance ranking are live-PostgreSQL only, step 6); existing offline test unmodified with all
   assertions; a new separate offline test for the document_chunks DDL (no CREATE/DROP EXTENSION, no FLOAT; verifies rendering only)).
   IMPLEMENTED; owner provisionally accepted it (2026-10-16) on its reported tests. As built, `Vector` and `UTCDateTime` live in
   `db/portable_types.py` (re-exported by `db/column_types.py`) so the retrieval model reaches no money module; the migration is
   `migrations/versions/0003_document_chunks.py`, with a separate test file, `tests/test_chunk_migration.py`. On SQLite, tie order
   and the cutoff predicate are checked as SQL text only. The live migration tests are step 6.
4. `services/retrieval.py` (ingest, search, audit); `tests/test_retrieval_service.py` (leakage, recheck raises, audit counts, every
   Unavailable reason, determinism, isolation, NULL/naive dates, atomic ingest (one oversized or one conflicting chunk in a
   multi-chunk call persists nothing), over-cap chunk and query raise RetrievalInputError with zero embedder calls, query-path
   context rejection, cap boundary 4,000 sent / 4,001 rejected before the embedder on both paths, prefix not counted; search rechecks
   every row before building SearchResult; audit_cutoff raises CutoffViolationError carrying the audit when violations > 0; any
   embedder Unavailable ends the call with nothing persisted). IMPLEMENTED 2026-10-16, awaiting owner review; 58 tests. Search
   and audit tests run on SQLite against a test-only stand-in repository that ranks in Python: they verify the service logic (cutoff
   passed through, recheck, audit, isolation, Unavailable cases), never the SQL cutoff predicate or ranking (step 6). Also changed:
   `providers/embedding/port.py` and `ollama.py` (`EmbeddingBatch.model`). Fingerprint and multi-chunk failure: spec section 4.
   Last full run, after step 4 (2026-10-16): 2,042 passed, 59 skipped, every skip "no live PostgreSQL configured". HISTORICAL; superseded by the step 6 results.
5. Boundary rules DONE (2026-10-15) in `tests/test_import_boundaries.py`: httpx files, embedding port for services, three-file float
   allowlist, empty embedding `__init__`, no `app/` import of the adapter, retrieval importer allowlists, float files cannot reach money
   modules. Several are vacuous until the modules exist. Still to add with the code: type-surface test (`float` only in `vectors`,
   `score`, `distance`; no `Decimal`) and a port purity test (stdlib + domain imports, no vendor words, failures as values).
   IMPLEMENTED 2026-10-16, awaiting owner review: `tests/test_retrieval_surface.py` (6 tests). The float allowlist is exact per
   field: `EmbeddingBatch.vectors`, `NewChunk.embedding` (the repository's input vector, owner to accept the name),
   `RetrievedChunk.score`, `ChunkHit.distance`, `NearestHit.distance`. Now that the modules exist, the earlier guards are no longer
   vacuous. Full run after step 5: 2,048 passed, 59 skipped (all "no live PostgreSQL configured"); HISTORICAL, superseded by step 6.
6. LIVE integration against the identified project database with pgvector enabled and the real Ollama model:
   `tests/test_retrieval_postgres.py`, `tests/test_embedding_live.py` (dimension 768, finite values, server digest equals the local
   manifest, oversized DOCUMENT and QUERY inputs sent directly to the adapter return the HTTP 400 context-length error
   (RetrievalInputError), an in-cap input returns 768 finite values, a digit-heavy in-cap input (about 4,000 characters) is asserted to raise
   RetrievalInputError, not assumed to succeed, document and query prefixes applied; live migration tests: missing-extension failure
   (VECTOR_EXTENSION_MISSING, nothing created; runs on the separate owner-provisioned disposable database without vector, never
   dropping the extension from alterfolio_test, never academic_os or intrinsic_db; not weakened; PASSED 2026-10-16, see below) and
   upgrade/downgrade with the extension installed (extension still present, document_chunks gone); published_at edge instants
   0001-01-01T00:00:00Z and 9999-12-31T23:59:59.999999Z stored and read back under a non-UTC session time zone).
   These tests initially exposed a timestamp-boundary failure, which was resolved by the owner-approved fix described below.
   DONE 2026-10-16. Results: focused portable 227 passed; live files 23 passed, 1 skipped; full suite with live variables 2,134 passed, 1 skipped
   (at that run the one skip was the missing-extension test; it has since passed, below; these totals pre-date that pass). Post-check: `vector` 0.8.7 installed, only an empty
   `alembic_version`. Edge instants first FAILED (psycopg decodes in the session zone: year 1 in America/Los_Angeles, year 9999 in
   Asia/Kolkata); owner-approved fix: `ChunkUTCDateTime` (`portable_types.py`, chunk columns only, shared `UTCDateTime` unchanged)
   and `timezone('UTC', published_at)` in `SEARCH_SQL`/`NEAREST_SQL`; window unchanged, no migration. Edge test now one id per zone
   and edge (get, counts, search, nearest); 4 portable tests added. Skipped runs do not count.
   MISSING-EXTENSION ACCEPTANCE PASSED 2026-10-16 (ONE node, NOT a suite run): `tests/test_chunk_migration_live.py::`
   `test_upgrade_without_the_extension_fails_with_vector_extension_missing_and_creates_nothing`, run as
   `python -m pytest -q -rA -p no:cacheprovider <node>`: 1 passed, 0 skipped, 0 failed in 0.81 s, after a passing preflight. Target:
   `alterfolio_novector_test` (owner-reported template0; owner `alterfolio_test_user`, PostgreSQL 16.14, 127.0.0.1:5432), URL derived in-process;
   `ALTERFOLIO_TEST_DATABASE_URL` absent from the pytest process. Post-check: that database has no `vector`, only an empty
   `public.alembic_version`, no application tables; `alterfolio_test` unchanged (`vector` 0.8.7, empty `alembic_version`, no
   `users`/`trades`/`import_batches`/`document_chunks`). The disposable database was NOT dropped (cleanup needs owner approval).
7. IN PROGRESS. DONE 2026-10-16: specs README row; full suite with all live variables incl. `ALTERFOLIO_TEST_NOVECTOR_DATABASE_URL`
   (both databases, Ollama): 2,135 passed, 0 failed, 0 skipped, 46.24 s (HISTORICAL, pre-fix); no live variables: 2,052 passed, 83 skipped (HISTORICAL, pre-fix); both databases
   left clean (`alterfolio_novector_test`: no `vector`, empty `alembic_version`; `alterfolio_test`: `vector` 0.8.7, empty `alembic_version`).
   Review fixes (owner-approved): `audit_cutoff` now raises `CutoffViolationError` for any detected violation (`audit=None` when the
   audit cannot be built; spec section 4) via `_recheck` before the unfiltered scan; 5 new tests in `tests/test_retrieval_service.py`
   (4 cases over `search`/`audit_cutoff` x stale counts/unfiltered-scan missing extension, 2 of which failed before the fix, plus a
   control that no violation keeps `Unavailable(VECTOR_EXTENSION_MISSING)`). Result: new tests 5 passed; focused retrieval files 226
   passed; no live variables 2,057 passed, 83 skipped. `chunks.py` `config_ids` docstring corrected.
   LIVE RERUN AFTER THE FIX, 2026-10-16: targeted live 87 passed, 0 failed, 0 skipped; full suite portable (live variables unset)
   2,057 passed, 83 skipped; full live (both databases, Ollama) 2,140 passed, 0 failed, 0 skipped, 39.65 s; both databases clean
   afterwards (`alterfolio_test`: `vector` 0.8.7, empty `alembic_version`; `alterfolio_novector_test`: no `vector`, empty
   `alembic_version`). The 2,135 / 2,052 totals above are HISTORICAL (pre-fix).
   OUTSTANDING: owner decisions (scratch probe files, commit); final review. Original regression
   command, kept for reference, from `backend/`: `.venv/Scripts/python.exe -m pytest -q` (baseline: 1,794 passed in 20.22 s, owner-run
   2026-10-15; the skipped count was not reported; new live tests must be among the passed ones).

## Failure modes and risks
Extension missing or `CREATE EXTENSION` denied; the `latest` tag moving after an Ollama pull (a digest mismatch at the per-request check gives an
explicit `Unavailable(EMBEDDING_INCOMPATIBLE)`; a move inside the tags-to-embed window may go undetected, see the known
limitation below); a prefix applied inconsistently (prevented by the role-based port); wrong database targeted;
SQLite versus PostgreSQL tie-order divergence (SQLite is test-only); exact-scan latency on large corpora (HNSW deferred); layering change touching the shared
boundary test; hardware-dependent embeddings. No change to Features 001-008.
KNOWN LIMITATION (owner-accepted 2026-10-16; not implemented): concurrent ingests for one user are unsupported. `add_chunks` checks keys
and embedding identity before inserting (`repositories/chunks.py` existing-rows read, identity check, `add_all`/`flush`) with no lock
and no identity constraint (only `(user_id, source_id, chunk_index)` is unique). Two racing ingests can (a) mix embedding identities in
one user's index, after which every search is `EMBEDDING_INCOMPATIBLE` and append-only storage cannot repair it (needs two differing
identities at once, not reachable with the single adapter); (b) hit the unique key and raise a raw `IntegrityError` (rolled back, all-or-nothing
holds; a retry reports `unchanged`). `counts`, `search` and the unfiltered scan are separate statements: concurrent writes can make audit
counts inconsistent, which raises `RetrievalInputError` when no violation is detected; a detected violation is always
`CutoffViolationError`. Cutoff and user isolation are not affected. Future mitigation (not 009): a per-user `pg_advisory_xact_lock` at the
start of `add_chunks` (the 002 import service has a user lock), mapping the unique-key error to a re-check, and optionally a
one-identity-per-user constraint; a single read snapshot for the audit.
KNOWN LIMITATION (documented 2026-10-16 after the final review; no code change): the Ollama adapter calls `GET /api/tags` on every
embedding request (no caching) and then `POST /api/embed` for the mutable tag `nomic-embed-text:latest`. The tag could theoretically be
repointed between the two requests and the change may go undetected; the embedding would be stored under the verified config id although
another model produced it. A move before the check is a digest mismatch (`Unavailable(EMBEDDING_INCOMPATIBLE)`). The digest check narrows
the window, it does not close it, and drift is not always detected. Search ties are ordered by `source_id COLLATE "C"` (code point), see spec section 7.
Test totals, 2026-10-16 (recorded results, not newly run): post-fix portable 2,057 passed, 83 skipped; full live 2,140 passed, 0 skipped;
targeted 87 passed, 0 skipped. All earlier totals in this plan are historical. Feature 009 remains NOT complete pending owner sign-off.
