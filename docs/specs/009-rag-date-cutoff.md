# Feature 009: RAG Date-Cutoff

Status: plan steps 1-6 implemented and live-verified (2026-10-16), uncommitted; the missing-extension acceptance test PASSED
(single node, 2026-10-16); live rerun after the audit fix PASSED (2026-10-16); NOT COMPLETE (step 7 final review and owner
decisions pending). Plan: `docs/plans/009-rag-date-cutoff.md`. Observational; no generation, no API.

## 1. Scope
Roadmap evidence: the `CLAUDE.md` "Feature numbering" rule (section 9) lists "009 RAG date-cutoff" (only mention). Owner decisions: callers supply corpus-agnostic dated
text chunks; this feature builds user-scoped chunk storage, cutoff-safe retrieval and a cutoff audit report. Non-goals: ingestion,
chunking, connectors, answer generation, API endpoints, UI, caching, re-ranking, update or delete, Feature 010, authentication.

## 2. Meaning of the date
`published_at` is when the text was published. It is NOT when an investor could have accessed it, so no true "as-known-at-date"
claim is made (CLAUDE.md rule 8 stays open). `recorded_at` (ingest time) is provenance only and never affects eligibility.

## 3. Cutoff semantics
- `cutoff` and `published_at` are aware datetimes normalised to UTC; naive values raise. Microsecond precision, no rounding.
  Any aware datetime whose UTC instant is representable (years 1..9999) is accepted; there is no narrower `published_at` window,
  because no product requirement justifies one (owner, 2026-10-15). Edge instants (year 1, year 9999) are verified live under
  Asia/Kolkata and America/Los_Angeles: psycopg decodes `timestamptz` in the session zone, which put them outside years 1..9999, so
  chunk timestamps are read as the UTC wall clock (`ChunkUTCDateTime`, `timezone('UTC', col)`; no schema or session change).
- Eligible iff `published_at <= cutoff` (inclusive). The clock is never read; the caller passes the cutoff.
- `published_at` is NOT NULL in the schema and validated at ingest. A missing, naive or unparseable date is rejected at ingest and
  can never be eligible (SQL comparison with NULL is false; the service also rejects `None`).
- The predicate is in the SQL `WHERE` before ranking (a post-filter would return fewer than k and hide leakage). The service
  rechecks every returned row and raises `CutoffViolationError` on any `published_at > cutoff`; rows are never silently dropped.

## 4. Inputs and outputs
- `ChunkInput(source_id, chunk_index >= 0, text, published_at)`: non-empty, no NUL, length limits in `domain/limits.py`; reject,
  never truncate. `MAX_CHUNK_TEXT_LENGTH` is a product cap of 4,000 Python characters (`len(str)`; owner-confirmed 2026-10-15,
  section 10), not a token-safety guarantee. It counts the caller's original text before the adapter adds `search_document: `
  or `search_query: `; prefix characters are not counted. Ollama's context limit is enforced separately (section 7). `search(user_id, query_text, cutoff, k)` with k in 1..50;
  `query_text` follows the same rules (non-empty, no NUL, at most `MAX_CHUNK_TEXT_LENGTH`). Both checks run before any provider
  call; over-cap text raises `RetrievalInputError` and is never sent.
- Ingest is all-or-nothing per call: if any chunk fails validation, embedding or persistence (including `ChunkConflictError` and
  `EmbeddingIncompatibleError`), no chunk or embedding from that call is persisted. Idempotent no-ops are not failures.
  One embedding request (DOCUMENT role; owner-confirmed 2026-10-16) carries all texts of an ingest call. If the provider rejects it as longer than the
  context, the call raises `RetrievalInputError` naming `(source_id, chunk_index)` when it holds one chunk; with several chunks
  it states that one of the N chunks was rejected, because the response does not identify the input. No retry, batch
  splitting, text shortening or partial persistence follows.
- Validation semantics (owner, 2026-10-15): `source_id` is at most `MAX_SOURCE_ID_LENGTH` = 256 Python characters. `source_id`, chunk
  `text` and `query_text` must be strings that are non-blank (not empty or whitespace-only), contain no NUL and are UTF-8-encodable;
  they are kept verbatim, never stripped or normalised. `chunk_index` is an integer (not bool) in 0..`MAX_CHUNK_INDEX` = 2^31 - 1,
  matching the PostgreSQL `INTEGER` column chosen for plan step 3. Rows read back are not re-validated against these caps.
- `RetrievedChunk(chunk_id, source_id, chunk_index, text, published_at, score, rank)`; `chunk_id` is a UUID, like every other
  primary key. A search returns `SearchResult(schema_version=1, provenance, chunks)`: `RetrievalProvenance(embedding_config_id,
  embedding_dimension, cutoff, k, input_fingerprint)` (config id and fingerprint are 64 lowercase-hex SHA-256 values; cutoff in UTC)
  and 1..k chunks ranked 1..n. A `SearchResult` is never empty (an empty search is `Unavailable`, section 7) and refuses a chunk
  after the cutoff with `CutoffViolationError` (a backstop to the service recheck, section 3). `score` is cosine similarity
  (1 - distance), a float display statistic; the ranking is the exact SQL distance order of section 7, and rounded scores are
  never used to validate or re-derive it.
- `input_fingerprint` (owner-confirmed 2026-10-16) = lowercase-hex SHA-256 of the UTF-8 bytes of `json.dumps(obj, sort_keys=True,
  separators=(",", ":"), ensure_ascii=False)` (keys sorted, no whitespace, non-ASCII kept as UTF-8). `obj` has exactly five keys:
  `user_id` (`str(UUID)`: 36 lowercase hex-and-hyphen characters), `query_text` (verbatim), `cutoff` (the cutoff converted to UTC by
  `astimezone(timezone.utc)`, then `isoformat()`: `2026-03-31T15:30:00.500000+00:00`, or `2026-03-31T15:30:00+00:00` when microseconds
  are 0), `k` (JSON integer) and `embedding_config_id` (the query batch's id, equal to the index's). It identifies the request, not a
  corpus snapshot: later ingests can change the result under the same value. No chunk count or `recorded_at` without a versioning design.
- `search` returns `EMPTY_INDEX` or `NO_ELIGIBLE_CHUNKS` from the exact counts before any provider call. `audit_cutoff` returns
  `EMPTY_INDEX` for an empty index and otherwise always runs the cutoff-filtered search, even with no eligible chunk, so a
  leaking filter is still detected.
- `audit_cutoff(...)` -> `CutoffAudit(schema_version=1, cutoff, total, eligible, excluded_after_cutoff, returned, violations,
  unfiltered_top_k_after_cutoff)`. Counts are non-negative integers; total = eligible + excluded_after_cutoff; violations <=
  returned; returned - violations <= eligible; unfiltered_top_k_after_cutoff <= excluded_after_cutoff. `CutoffAudit` can represent
  violations > 0; the service enforces the guarantee: on any detected violation (in `search` or `audit_cutoff`) it raises
  `CutoffViolationError` carrying that audit, and returns no result. If the audit itself cannot be built (missing extension on
  the unfiltered scan, or inconsistent counts), the error is still raised, with `audit=None`.

## 5. Architecture
`domain/retrieval.py` (stdlib types) <- `providers/embedding/port.py` (narrow Protocol: `embed(texts, role) -> EmbeddingBatch(
config_id, dimension, vectors, model)`, role DOCUMENT or QUERY) <- `services/retrieval.py` -> `repositories/chunks.py` -> `models/chunk.py`.
`EmbeddingBatch.model` (owner-approved 2026-10-16) is the model name the provider itself used, stored as `embedding_model`
provenance. It is `None` (the default, so three-field constructions stay valid) or a string that is non-blank, NUL-free and at
most `MAX_EMBEDDING_MODEL_LENGTH` = 128 characters; anything else raises `RetrievalInputError`. The Ollama adapter sets the tag it
requested and whose digest it verified (`nomic-embed-text:latest`). The service never supplies or guesses a name. Ingest fails
closed: `model=None` is `Unavailable(EMBEDDING_PROVIDER_UNAVAILABLE)`; an invalid name raises `RetrievalInputError` (batch
validation, and again in the repository before any write); either way nothing is stored. Search does not use it; not a config-id field.
The service and repository depend on the port only. The Ollama adapter (`providers/embedding/ollama.py`, `POST /api/embed`) applies the
prefixes, is imported only by tests in 009, and `providers/embedding/__init__.py` stays empty. Approved boundary amendment, recorded
2026-10-15 in CLAUDE.md s2-s4, `docs/design.md` and `tests/test_import_boundaries.py`: services may import `app.providers.embedding.port`
only; httpx also in `ollama.py`; floats only in `ollama.py`, `services/retrieval.py`, `repositories/chunks.py`; quant rules unchanged.

## 6. Persistence and compatibility
- Table `document_chunks`, append-only: `id`, `user_id` FK, `source_id`, `chunk_index`, `text`, `content_sha256`, `published_at`, `recorded_at`, `embedding vector(D)`,
  `embedding_model`, `embedding_config_id`, `embedding_dimension`.
- Isolation: every repository method requires `user_id` and filters on it, like `trade_repository`. No owner lookup is invented.
- Unique `(user_id, source_id, chunk_index)`. Same hash and same embedding identity: idempotent no-op. Different hash: `ChunkConflictError`. Same hash, different embedding identity:
  `EmbeddingIncompatibleError`.
- Embedding identity: `embedding_config_id` = SHA-256 of canonical JSON (sorted keys, no whitespace) of `provider` "ollama", `model_tag` "nomic-embed-text:latest", `manifest_digest`
  (full `sha256:` from the server's model listing), `dimension` 768, `document_prefix` "search_document:", `query_prefix` "search_query:", `join` `"<prefix> <text>"` (exactly one space,
  owner-confirmed 2026-10-15: `search_document: <text>`, `search_query: <text>`), `truncate` false. Chunks ALWAYS use the document prefix and queries the query prefix (never omitted or
  swapped); stored `text` and `content_sha256` exclude it. Any change to one of these eight fields (provider, model tag, manifest digest, dimension, document and query prefixes, join,
  truncate) is a new id; a user's index never mixes ids, a differing query config is `Unavailable(EMBEDDING_INCOMPATIBLE)`, no silent re-embed or model switch. A moved `latest` tag does
  not produce a new id: the adapter's id is built from the verified digest, so a listing with another digest is a digest mismatch, `Unavailable(EMBEDDING_INCOMPATIBLE)`. A move inside
  the tags-to-embed window may not be detected (section 8).
- Chunks are never combined in 009: each `ChunkInput` is embedded and stored on its own. If a later feature combines chunk texts, the owner-selected provisional separator is one newline
  (`\n`), in a deterministic order that feature must define. It is unused in 009 and is not part of `embedding_config_id`. The prefix join above (`<prefix> <text>`) is a different
  setting.
- Migration policy (owner, 2026-10-15): the Feature 009 migration requires the `vector` extension to exist and never runs `CREATE EXTENSION`. If it is missing, the migration fails
  clearly with `VECTOR_EXTENSION_MISSING` before creating anything. No superuser is granted to the project role. Downgrade removes only Feature 009's own objects (`document_chunks` and
  its indexes) and never drops the extension.
- Migration/test strategy (owner design decision, 2026-10-15): existing SQLite migration tests stay unmodified wherever they faithfully verify behaviour, so the migration must not
  require the extension on SQLite. pgvector-specific behaviour is verified on live PostgreSQL: the missing-extension failure, and upgrade/downgrade with the extension already installed
  (downgrade leaves it). Offline SQL rendering (`alembic upgrade --sql`) cannot check the extension: it renders DDL only, emits no `CREATE EXTENSION` or `DROP EXTENSION`, and its test
  asserts rendering, never runtime availability.
- Missing-extension test (owner, 2026-10-15): runs only against a separate owner-provisioned disposable PostgreSQL database where `vector` is absent. The extension is never dropped from
  `alterfolio_test`, and `academic_os` and `intrinsic_db` are never used. The database was provisioned and the test passed 2026-10-16 (section 10); the criterion was not weakened. Still
  not complete (step 7 final review and owner decisions pending).
- SQLite stand-in (owner constraints, 2026-10-15): if SQLite needs a stand-in for the vector column it is test-only, never changes the PostgreSQL production schema, and SQLite never
  substitutes for live pgvector verification (distance, ranking, casts and the extension check are verified only on live PostgreSQL). The exact approach in plan step 3 (TypeDecorator:
  vector(768) on PostgreSQL, TEXT on SQLite) is owner-approved as a design decision (2026-10-15); that is not approval to implement.
- Authoritative database (owner, 2026-10-15): PostgreSQL with pgvector is the only authoritative database for every pgvector-specific behaviour: the vector column, casts, distance,
  ranking, the extension check, migrations and integration tests. SQLite is kept only for existing portable tests where it gives meaningful (non-vector) coverage and is never evidence
  for vector behaviour. Destructive tests never run against `academic_os` or `intrinsic_db`, and the extension is never dropped from `alterfolio_test`.
- D = 768, from one verified call (section 10), never inferred from the model name. Index: btree `(user_id, published_at)` only; search and audit share one exact cosine scan (HNSW
  deferred until measured latency and a recall test against exact results justify it). Vector column: hand-written `TypeDecorator`, text bind `CAST(:p AS vector)`, no `pgvector`
  package; pgvector stores float32.

## 7. Vectors, errors, determinism
- Floats only for vectors and scores, only in the three allowlisted files (section 5). Reject NaN, infinity, empty and zero-norm
  vectors (cosine distance of a zero vector is NaN in pgvector), and any dimension differing from the batch or stored identity.
- Defects raise (`RetrievalInputError`). Valid requests without a result are explicit `Unavailable`: `EMBEDDING_PROVIDER_UNAVAILABLE`,
  `EMBEDDING_MODEL_MISSING`, `DIMENSION_UNRESOLVED`, `DIMENSION_MISMATCH`, `NON_FINITE_EMBEDDING`, `EMBEDDING_INCOMPATIBLE`,
  `VECTOR_EXTENSION_MISSING`, `EMPTY_INDEX`, `NO_ELIGIBLE_CHUNKS`. Never an empty list posing as success, a zero vector or a fallback.
- Embedding and extension error contract (owner, 2026-10-15), fail-closed: an invalid provider embedding is never stored, repaired
  or replaced. The port returns failures as values: a NaN or infinite element, or a zero norm (cosine distance NaN), is
  `Unavailable(NON_FINITE_EMBEDDING)`; an empty vector, a length other than the configured dimension 768, or differing lengths in one
  batch is `Unavailable(DIMENSION_MISMATCH)`; a response with no determinable dimension (no vectors, non-numeric elements) is
  `Unavailable(DIMENSION_UNRESOLVED)`; a vector count different from the input count is `Unavailable(EMBEDDING_PROVIDER_UNAVAILABLE)`.
  On ingest any of these ends the whole call with that `Unavailable` and persists nothing (section 4); on search it is returned.
  A missing extension: the migration raises `VectorExtensionMissingError` (a `RetrievalError` added to `domain/retrieval.py` in plan
  step 3; message starts `VECTOR_EXTENSION_MISSING`) before creating anything, because a migration cannot return `Unavailable`; at
  runtime a repository call that finds `vector` unavailable maps to `Unavailable(VECTOR_EXTENSION_MISSING)`.
- Invariant: every `/api/embed` request, on the document and the query path alike, sends `truncate: false` (also part of the
  config id, section 6). No code path omits it or sends `true`. One request per call; no retry, no shortening, no partial input.
- Provider failures, most specific classification first:
  - model absent from `/api/tags` or reported missing by the server: `Unavailable(EMBEDDING_MODEL_MISSING)`;
  - HTTP 400 `the input length exceeds the context length` (observed on Ollama 0.24.0): `RetrievalInputError` naming the
    query, or the chunk `(source_id, chunk_index)` when the ingest call holds one chunk (several chunks: section 4), with
    nothing persisted;
  - any other HTTP error, a timeout or a connection failure: `Unavailable(EMBEDDING_PROVIDER_UNAVAILABLE)`.
- Order: cosine distance asc (`score = 1 - distance`, display only, never re-sorted), then `published_at`, `source_id` (`COLLATE "C"`, code-point order, independent of the database's
  default collation), `chunk_index`, `chunk_id` asc. Same data, vector and cutoff on one pgvector build: same order. Embeddings and float32 arithmetic may differ across hardware, builds
  or model versions; the config id is recorded, not guaranteed.

## 8. Audit guarantees and limits
Guarantees: no returned chunk has `published_at > cutoff`; counts are exact for this user's data at call time; the unfiltered count comes from an exact unfiltered nearest search.
Limits: it trusts the stored `published_at`; it cannot detect text that describes later events; it is not knowledge-time proof; scores are model-dependent.
Known limitations (owner-accepted, 2026-10-16; no lock, snapshot or constraint is implemented): ingests for one user must be serialised by the caller, because ingest checks keys and
embedding identity before inserting. A race can mix identities (every search is then `EMBEDDING_INCOMPATIBLE`; storage is append-only) or raise a raw `IntegrityError` (all-or-nothing
holds; a retry reports `unchanged`). Counts, search and the unfiltered scan are separate statements, so concurrent writes can make audit counts inconsistent: with no violation detected
that raises `RetrievalInputError`; a detected violation is always `CutoffViolationError` (`audit=None` when the audit cannot be built).
Ollama adapter (documented 2026-10-16 after the final review; no code change): `OllamaEmbedder.embed` calls `GET /api/tags` on every embedding request (the listing is never cached) to
confirm the model is listed with the verified manifest digest, then sends `POST /api/embed` naming the mutable tag `nomic-embed-text:latest`. If the tag was already repointed before the
check, the digest mismatch returns `Unavailable(EMBEDDING_INCOMPATIBLE)`. The two requests are separate, so a residual race remains: a repoint between them may go undetected, and that
embedding would be stored under the verified `embedding_config_id` although another model produced it. The per-request digest check narrows this window; it does not close it, and drift
is not always detected.

## 9. Acceptance
Leakage at `cutoff + 1 microsecond` and equality at `cutoff`; NULL/naive dates; forced-violation raises; idempotency, conflict and incompatible-identity cases; user isolation at
repository and service level; tie order; each Unavailable reachable; boundary and float-scope tests. Live PostgreSQL+pgvector and Ollama tests must RUN and pass: skipped live tests are
not integration verification.
Embedding: every DOCUMENT and QUERY request carries `truncate: false` (fake transport and live); an over-cap chunk and an over-cap query each raise `RetrievalInputError` with zero
provider calls; a context-length 400 raises `RetrievalInputError` on the document path and on the query path; a multi-chunk ingest with one oversized chunk, or with one conflicting
chunk, persists nothing; a missing model is `EMBEDDING_MODEL_MISSING`, never `EMBEDDING_PROVIDER_UNAVAILABLE`. Cap boundary on both paths: 4,000 characters is sent (with the prefix
added), 4,001 raises `RetrievalInputError` with zero provider calls.
Migration (live PostgreSQL, must run): with the extension absent (separate disposable database; PASSED 2026-10-16 on `alterfolio_novector_test`, never weakened), upgrade fails with
`VECTOR_EXTENSION_MISSING` and creates no 009 object; with it present, upgrade creates `document_chunks`, and after downgrade that table is gone and the extension is still installed.
Offline render: the existing offline test keeps every current assertion unmodified; a new, separate test asserts the `document_chunks` DDL with `vector(768)` and no `CREATE
EXTENSION`/`DROP EXTENSION`, and claims nothing about availability. The existing SQLite migration tests pass unmodified.

## 10. Gates before implementation
VERIFIED (owner, 2026-10-15): `POST /api/embed`, tag `nomic-embed-text:latest`, `truncate: false` returned 768 finite values.
VERIFIED (controlled probe, 2026-10-15; Ollama 0.24.0; prefix `search_document: `; `truncate: false`; synthetic text; 31 requests): `/api/show` nomic-bert, 137M, F16, embedding 768,
`num_ctx` 8192, GGUF context_length 2048; `/api/tags` digest `0a109f42...e59f` equals the local manifest sha256 (server and local file agree; this does NOT establish upstream model
provenance); short inputs returned 768 finite values; successful responses include `prompt_eval_count` (probe evidence only; the implementation does not consume it); oversized inputs
return HTTP 400 `{"error":"the input length exceeds the context length"}`. Largest accepted (chars / reported tokens): English 8,000 / 1,169; digit-heavy 2,000 / 1,183; Devanagari 8,000
/ 1,011. Smallest rejected: 16,000 / 4,000 / 16,000 chars. Each edge size was run 3 times, all agreeing. These are observed acceptance points, not token boundaries.
VERIFIED (owner-run read-only inspection, 2026-10-15; reported by the owner, no output file in the repository): PostgreSQL 16.14, port 5432, database `alterfolio_test`, role
`alterfolio_test_user` (not a superuser; has database CREATE privilege and schema USAGE); pgvector 0.8.7 installed in schema `public`, owned by `postgres`; SQLAlchemy `CAST(:q AS
vector)` named binding works; cosine distance of identical vectors 0.0, orthogonal 1.0, opposite 2.0; a 768-dimensional vector is accepted; a zero vector gives NaN cosine distance, so
application validation must reject it (section 7). Nothing is recorded about any other database.
UNVERIFIED (recorded, not claimed; owner: non-blocking): the role that ran `CREATE EXTENSION`; the extension's absolute maximum dimension (768 is accepted; the limit itself is not
verified); error texts and SQLSTATEs for invalid vector inputs (empty, non-numeric, NaN, Infinity, dimension mismatch, wrong typmod); the server's exact missing-model response; the
exact token limit and the effective server context (`num_ctx` 8192 vs GGUF 2048); the `search_query: ` prefix; behaviour after unload or restart; real corpus chunks.
OWNER-CONFIRMED (2026-10-15): `MAX_CHUNK_TEXT_LENGTH` = 4,000 Python characters for chunks and queries, counted before the role prefix; prefix format exactly one space
(`search_document: <text>`, `search_query: <text>`). The cap is a product decision, not a proven runtime limit: in the probe, digit-heavy text of 4,000 characters plus the prefix was
rejected 3/3, so in-cap text can still fail with the context-length `RetrievalInputError` (section 7). OWNER-SELECTED, PROVISIONAL: `\n` as the chunk-combining separator (unused in 009,
section 6).
RESOLVED (owner, 2026-10-16): the disposable database without `vector` (`alterfolio_novector_test`) was provisioned; it is not dropped.
GATE: implementation proceeds one plan step at a time on explicit owner authorisation. Owner, 2026-10-16: Steps 1-4 docs accepted; `EmbeddingBatch.model`, `user_id` in the fingerprint,
one embedding request per ingest confirmed (sections 4-5); Steps 5, 6, C and the Step 7 audit fix authorised and implemented.
VERIFIED 2026-10-16 (PostgreSQL 16.14, pgvector 0.8.7, live Ollama; detail in plan step 6): acceptance ONE node
`test_upgrade_without_the_extension_fails_with_vector_extension_missing_and_creates_nothing` on `alterfolio_novector_test`: 1 passed, 0 skipped, 0 failed, 0.81 s. Full suite, all live
variables: 2,135 passed, 0 failed, 0 skipped (HISTORICAL, pre-fix); no live variables: 2,052 passed, 83 skipped (HISTORICAL, pre-fix). Both databases left clean (`vector` absent /
0.8.7, empty `alembic_version`). HISTORICAL, before that test ran: focused portable tests: 227 passed; live files 23 passed, 1 skipped; full live 2,134 passed, 1 skipped.
AFTER THE `audit_cutoff` FIX (section 4), 2026-10-16: 5 new service tests (2 failed before the fix). Targeted live run (post-fix): 87 passed, 0 failed, 0 skipped. Full suite, two-stage:
portable (all live variables unset) 2,057 passed, 83 skipped (all live-gated); full live (both databases, Ollama) 2,140 passed, 0 failed, 0 skipped, 39.65 s. Both databases unchanged
afterwards (`alterfolio_test`: `vector` 0.8.7, only an empty `alembic_version`; `alterfolio_novector_test`: no `vector`, only an empty `alembic_version`). The 2,135 / 2,052 counts above
are HISTORICAL (pre-fix). NOT COMPLETE: final review and owner decisions (scratch files, commit) remain.
