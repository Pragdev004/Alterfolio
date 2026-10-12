"""Streaming tradebook upload reader (plan 002a A-4): one part named `file`, 2 MiB cap enforced while reading."""
import asyncio
import json

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.uploads import UploadedFile, read_tradebook_upload
from app.domain import limits

CAP = limits.MAX_IMPORT_FILE_BYTES
CHUNK = 64 * 1024
BOUNDARY = "TESTBOUNDARY"
END = f"--{BOUNDARY}--\r\n".encode()


def part(name: str, content: bytes, filename: str | None = None, content_type: str | None = None) -> bytes:
    header = f'Content-Disposition: form-data; name="{name}"'
    if filename is not None:
        header += f'; filename="{filename}"'
    if content_type:
        header += f"\r\nContent-Type: {content_type}"
    return f"--{BOUNDARY}\r\n{header}\r\n\r\n".encode() + content + b"\r\n"


def file_body(content: bytes = b"a,b\n1,2\n", filename: str | None = "t.csv", **kw) -> bytes:
    return part("file", content, filename, **kw) + END


class Meter:
    """Feeds a body in 64 KiB chunks and counts how much of it the application actually pulled."""

    def __init__(self, body: bytes):
        self.chunks = [body[i:i + CHUNK] for i in range(0, len(body), CHUNK)] or [b""]
        self.consumed = 0
        self.total = len(body)

    async def receive(self):
        if not self.chunks:
            return {"type": "http.disconnect"}
        chunk = self.chunks.pop(0)
        self.consumed += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(self.chunks)}


def read(body: bytes, content_type: str | None = f"multipart/form-data; boundary={BOUNDARY}", disconnect=False):
    """Run the reader against a raw ASGI request; return (result_or_exception, bytes consumed, bytes sent)."""
    meter = Meter(body)
    headers = [(b"host", b"t")]
    if content_type is not None:
        headers.append((b"content-type", content_type.encode()))
    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers, "query_string": b"", "scheme": "http",
             "server": ("t", 80), "client": ("c", 1), "http_version": "1.1", "root_path": ""}

    async def receive():
        if disconnect:
            return {"type": "http.disconnect"}
        return await meter.receive()

    async def run():
        try:
            return await read_tradebook_upload(Request(scope, receive))
        except Exception as exc:  # noqa: BLE001 - the test inspects the exception
            return exc

    return asyncio.run(run()), meter.consumed, meter.total


def assert_invalid(result):
    from app.services.errors import InvalidImportFileError

    assert isinstance(result, InvalidImportFileError), result
    assert result.code == "invalid_import_file"


# ---- accepted -------------------------------------------------------------------------------------------------------

def test_valid_file_with_any_part_content_type():
    result, _, _ = read(file_body(b"symbol,isin\nA,B\n", content_type="application/x-anything"))
    assert result == UploadedFile("t.csv", b"symbol,isin\nA,B\n")


def test_file_of_exactly_two_mebibytes_is_accepted():
    result, consumed, total = read(file_body(b"x" * CAP))
    assert isinstance(result, UploadedFile) and len(result.content) == CAP == 2 * 1024 * 1024
    assert consumed == total


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dir/x.csv", "x.csv"),
        ("C:\\Users\\me\\x.csv", "x.csv"),
        ("../../etc/x.csv", "x.csv"),
        ("mixed/dir\\x.csv", "x.csv"),
        ("  x.csv ", "x.csv"),
        ("trade\u00e9.csv", "trade\u00e9.csv"),
    ],
)
def test_filename_is_reduced_to_its_basename_on_both_separators(raw, expected):
    result, _, _ = read(file_body(filename=raw))
    assert isinstance(result, UploadedFile) and result.file_name == expected


# ---- the size cap is enforced while reading -------------------------------------------------------------------------

def test_one_byte_over_the_cap_is_rejected():
    result, _, _ = read(file_body(b"x" * (CAP + 1)))
    assert_invalid(result)


def test_oversized_upload_stops_reading_the_body_early():
    body = file_body(b"y" * (8 * 1024 * 1024))
    result, consumed, total = read(body)
    assert_invalid(result)
    assert consumed <= CAP + CHUNK + 4096, (consumed, total)  # cap + one chunk + part headers
    assert consumed < total / 3


def test_extra_part_stops_reading_immediately():
    body = part("file", b"a", "a.csv") + part("other", b"z" * (4 * 1024 * 1024)) + END
    result, consumed, total = read(body)
    assert_invalid(result)
    assert consumed <= 2 * CHUNK


# ---- every transport failure is invalid_import_file -----------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    [
        pytest.param(part("other", b"v") + END, id="only-a-text-field"),
        pytest.param(part("upload", b"a", "a.csv") + END, id="wrong-part-name"),
        pytest.param(END, id="no-parts"),
        pytest.param(part("file", b"a", "a.csv") + part("note", b"v") + END, id="extra-field-after"),
        pytest.param(part("note", b"v") + part("file", b"a", "a.csv") + END, id="extra-field-before"),
        pytest.param(part("file", b"a", "a.csv") + part("file", b"b", "b.csv") + END, id="two-file-parts"),
        pytest.param(part("file", b"a") + END, id="missing-filename"),
        pytest.param(part("file", b"a", "") + END, id="empty-filename"),
        pytest.param(part("file", b"a", "dir/") + END, id="empty-after-basename-slash"),
        pytest.param(part("file", b"a", "dir\\") + END, id="empty-after-basename-backslash"),
        pytest.param(part("file", b"a", "..") + END, id="dotdot-filename"),
        pytest.param(part("file", b"a", "a\x07b.csv") + END, id="control-char-filename"),
        pytest.param(part("file", b"a", "a" * 252 + ".csv") + END, id="filename-too-long"),
        pytest.param(part("file", b"", "a.csv") + END, id="empty-file"),
        pytest.param(part("file", b"abc", "a.csv"), id="truncated-no-closing-boundary"),
        pytest.param(b"not multipart at all", id="garbage"),
        pytest.param(b"", id="empty-body"),
        pytest.param(
            part("file", b"a", "a").replace(b'filename="a"', b'filename="\xff\xfe.csv"') + END, id="non-utf8-filename"
        ),
    ],
)
def test_malformed_missing_or_extra_parts_are_rejected(body):
    result, _, _ = read(body)
    assert_invalid(result)


@pytest.mark.parametrize("content_type", ["application/json", "multipart/form-data", "multipart/mixed; boundary=x", None])
def test_wrong_or_missing_content_type_is_rejected(content_type):
    result, _, _ = read(file_body(), content_type=content_type)
    assert_invalid(result)


def test_client_disconnect_mid_upload_is_rejected():
    result, _, _ = read(file_body(), disconnect=True)
    assert_invalid(result)


# ---- through the real application error handler ---------------------------------------------------------------------

@pytest.fixture
def client():
    app = create_app(session_factory=lambda: None)

    async def echo(request: Request):
        uploaded = await read_tradebook_upload(request)
        return {"file_name": uploaded.file_name, "size": len(uploaded.content)}

    app.add_api_route("/_upload_probe", echo, methods=["POST"])
    return TestClient(app)


def test_http_valid_upload(client):
    response = client.post("/_upload_probe", files={"file": ("x.csv", b"a,b\n", "text/csv")})
    assert response.status_code == 200 and response.json() == {"file_name": "x.csv", "size": 4}


@pytest.mark.parametrize(
    "files",
    [
        {"other": ("x.csv", b"a")},
        {"file": ("x.csv", b"")},
        {"file": ("", b"a")},
    ],
)
def test_http_failures_are_422_invalid_import_file(client, files):
    response = client.post("/_upload_probe", files=files)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_import_file"


def test_http_extra_form_field_is_422(client):
    response = client.post("/_upload_probe", files={"file": ("x.csv", b"a")}, data={"note": "v"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid_import_file"


def test_http_non_multipart_body_is_422(client):
    response = client.post("/_upload_probe", content=b"a,b\n", headers={"content-type": "text/csv"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid_import_file"


def test_http_oversized_upload_is_422(client):
    response = client.post("/_upload_probe", files={"file": ("x.csv", b"x" * (CAP + 1))})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid_import_file"
    assert json.loads(response.text)["detail"]["code"] == "invalid_import_file"
