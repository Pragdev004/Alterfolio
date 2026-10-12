"""Streaming reader for the tradebook upload (plan 002a A-4).

`UploadFile` parses and spools the whole body before the handler runs, so the size cap cannot be enforced while
reading, and it reports malformed multipart as a framework 400. This reader pulls `request.stream()` through
python-multipart and stops as soon as a rule is broken, so a hostile or oversized upload costs at most the cap plus
one chunk. Every transport/parsing failure is an `InvalidImportFileError` (422 `invalid_import_file`).
"""
import unicodedata
from dataclasses import dataclass

from python_multipart import MultipartParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect, Request

from app.domain import limits
from app.services.errors import InvalidImportFileError

FILE_FIELD = "file"


@dataclass(frozen=True)
class UploadedFile:
    file_name: str
    content: bytes


def _file_name(raw: bytes | None) -> str:
    """Base name after splitting on both '/' and '\'; must be non-empty, printable-safe and <= 255 characters."""
    if raw is None:
        raise InvalidImportFileError("the file part has no filename")
    text = raw.decode("utf-8", "strict")  # a UnicodeDecodeError is mapped by the caller
    name = text.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if name in ("", ".", ".."):
        raise InvalidImportFileError("the file part has an empty filename")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise InvalidImportFileError("the filename contains control characters")
    if len(name) > limits.MAX_IMPORT_FILE_NAME_LENGTH:
        raise InvalidImportFileError(f"the filename is longer than {limits.MAX_IMPORT_FILE_NAME_LENGTH} characters")
    return name


async def read_tradebook_upload(
    request: Request, *, max_bytes: int = limits.MAX_IMPORT_FILE_BYTES
) -> UploadedFile:
    """Read exactly one multipart part named `file`; the part content-type is deliberately not checked."""
    main, options = parse_options_header(request.headers.get("content-type", "").encode("latin-1", "replace"))
    boundary = options.get(b"boundary")
    if main != b"multipart/form-data" or not boundary:
        raise InvalidImportFileError("the request must be multipart/form-data with a boundary")

    parts = 0
    header_name = bytearray()
    header_value = bytearray()
    headers: dict[bytes, bytes] = {}
    file_name = ""
    content = bytearray()
    ended = False

    def on_part_begin() -> None:
        nonlocal parts
        parts += 1
        if parts > 1:
            raise InvalidImportFileError("the upload must contain exactly one part named 'file'")
        headers.clear()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        header_value.extend(data[start:end])

    def on_header_end() -> None:
        headers[bytes(header_name).lower()] = bytes(header_value)
        header_name.clear()
        header_value.clear()

    def on_headers_finished() -> None:
        nonlocal file_name
        disposition = headers.get(b"content-disposition")
        if disposition is None:
            raise InvalidImportFileError("the part has no Content-Disposition")
        _, params = parse_options_header(disposition)
        if params.get(b"name") != FILE_FIELD.encode():
            raise InvalidImportFileError("the upload must contain exactly one part named 'file'")
        file_name = _file_name(params.get(b"filename"))

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if len(content) + (end - start) > max_bytes:
            raise InvalidImportFileError(f"the file is larger than {max_bytes} bytes")
        content.extend(data[start:end])

    def on_end() -> None:
        nonlocal ended
        ended = True

    parser = MultipartParser(
        boundary,
        callbacks={
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_end": on_end,
        },
    )
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
    except InvalidImportFileError:
        raise
    except ClientDisconnect:
        raise InvalidImportFileError("the upload was interrupted") from None
    except (FormParserError, ValueError):  # includes UnicodeDecodeError
        raise InvalidImportFileError("the upload is not valid multipart/form-data") from None
    if not ended or parts != 1:
        raise InvalidImportFileError("the upload must contain exactly one complete part named 'file'")
    if not content:
        raise InvalidImportFileError("the file is empty")
    return UploadedFile(file_name=file_name, content=bytes(content))
