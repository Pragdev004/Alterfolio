# Spec 002-1: Streaming tradebook upload reader

Status: delivered, not yet used by a route. Plan: `docs/plans/002-zerodha-tradebook-import.md`, decision A-4 and OPEN-8/9 in
`002a-decisions.md`. Code: `backend/app/api/uploads.py`. Tests: `backend/tests/test_upload_reader.py`.

## Purpose
Read the multipart body of `POST /imports/tradebook` while enforcing the 2 MiB limit during reading, never after buffering
the whole file. FastAPI's `UploadFile` could not guarantee that, so the reader uses `request.stream()` with
`python-multipart`.

## Interface
`read_tradebook_upload(request) -> UploadedFile(file_name, content: bytes)`. It is async, API layer only, and does no
parsing of the CSV.

## Rules
- Exactly one part, named `file`. Missing file, a second part, any extra form field, a duplicate `file` part, or a
  malformed multipart body is a failure.
- The file name is reduced to its basename on both `/` and `\`. A missing or empty name after reduction is a failure.
- The part content type is not validated.
- Exactly 2 MiB (`MAX_IMPORT_FILE_BYTES`) is accepted; more is rejected while reading, before the rest of the body is read.
- An empty file is a failure.
- Every failure raises `InvalidImportFileError` (code `invalid_import_file`), which maps to 422. Nothing is persisted.

## Dependencies
`python-multipart==0.0.32` pinned in `backend/constraints.txt` (declared `>=0.0.32` in `pyproject.toml`). The install, `pip check`
and full suite were verified on Python 3.14.5 and 3.12.

## Not included
The route, the 422 handler registration, SHA-256, decoding and CSV parsing.
