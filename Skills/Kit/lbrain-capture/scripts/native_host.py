#!/usr/bin/env python3
"""On-demand Chrome Native Messaging host for LBrain Capture Bundles."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import html
import json
import mimetypes
import quopri
import re
import shutil
import struct
import sys
import tempfile
import xml.sax
from email import policy
from email.parser import BytesHeaderParser
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote, urlsplit, urlunsplit

from operations import (
    CAPTURE_DISK_RESERVE_BYTES,
    OperationError,
    capture_bundle,
    operation_lock,
    replace_exact_url,
    safe_asset_path,
)


STREAM_PROTOCOL = "lbrain.capture.stream.v1"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_CAPTURE_ASSET_BYTES = 256 * 1024 * 1024
MAX_CAPTURE_STREAM_BYTES = 512 * 1024 * 1024


def read_message(stream: BinaryIO) -> dict[str, Any]:
    header = stream.read(4)
    if len(header) != 4:
        raise OperationError("native message header is missing")
    length = struct.unpack("=I", header)[0]
    if length > MAX_MESSAGE_BYTES:
        raise OperationError("native message exceeds Chrome's 1 MiB host input limit")
    raw = stream.read(length)
    if len(raw) != length:
        raise OperationError("native message body is incomplete")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise OperationError("native message must be a JSON object")
    return value


def write_message(stream: BinaryIO, value: dict[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(raw) > MAX_MESSAGE_BYTES:
        value = {
            key: item for key, item in value.items()
            if key not in {"affected_paths"}
        }
        value["affected_paths"] = []
        value["receipt_warning"] = "affected_paths omitted from oversized browser receipt"
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise OperationError("native response exceeds Chrome's 1 MiB host output limit")
    stream.write(struct.pack("=I", len(raw)))
    stream.write(raw)
    stream.flush()


def required_stream_value(message: dict[str, Any], key: str, expected: type) -> Any:
    value = message.get(key)
    if not isinstance(value, expected) or isinstance(value, bool):
        raise OperationError(f"stream {key} is invalid")
    return value


def write_with_disk_reserve(output: BinaryIO, body: bytes) -> None:
    if not body:
        return
    directory = Path(str(output.name)).resolve().parent
    if len(body) + CAPTURE_DISK_RESERVE_BYTES > shutil.disk_usage(directory).free:
        raise OperationError("not enough disk space for capture staging")
    output.write(body)
    output.flush()


def normalized_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = quote(parsed.path, safe="/%:@-._~!$&'()*+,;=")
    path = re.sub(
        r"%([0-9A-Fa-f]{2})",
        lambda match: chr(int(match.group(1), 16))
        if chr(int(match.group(1), 16)) in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        else f"%{match.group(1).upper()}",
        path,
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def mime_headers(stream: BinaryIO) -> Any:
    lines: list[bytes] = []
    size = 0
    while True:
        line = stream.readline(128 * 1024 + 1)
        size += len(line)
        if size > 128 * 1024:
            raise OperationError("MHTML part headers are too large")
        if line in {b"", b"\n", b"\r\n"}:
            break
        lines.append(line)
    return BytesHeaderParser(policy=policy.default).parsebytes(b"".join(lines))


def decode_mime_body(source: Path, target: Path, encoding: str) -> None:
    with source.open("rb") as encoded, target.open("wb") as decoded:
        if encoding == "base64":
            remainder = b""
            for chunk in iter(lambda: encoded.read(64 * 1024), b""):
                compact = remainder + b"".join(chunk.split())
                boundary = len(compact) // 4 * 4
                if boundary:
                    try:
                        write_with_disk_reserve(decoded, base64.b64decode(compact[:boundary], validate=True))
                    except binascii.Error as error:
                        raise OperationError("MHTML part is not valid base64") from error
                remainder = compact[boundary:]
            if remainder:
                raise OperationError("MHTML part is not valid base64")
        elif encoding == "quoted-printable":
            while True:
                line = encoded.readline(128 * 1024 + 1)
                if not line:
                    break
                if len(line) > 128 * 1024:
                    raise OperationError("MHTML quoted-printable line is too large")
                write_with_disk_reserve(decoded, quopri.decodestring(line))
        elif encoding in {"", "7bit", "8bit", "binary"}:
            for chunk in iter(lambda: encoded.read(1024 * 1024), b""):
                write_with_disk_reserve(decoded, chunk)
        else:
            raise OperationError("MHTML part uses an unsupported transfer encoding")


def copy_mime_body(stream: BinaryIO, output: BinaryIO | None, marker: bytes, closing: bytes) -> bytes:
    buffer = b""
    keep = len(marker) + 8
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            raise OperationError("MHTML part is incomplete")
        buffer += chunk
        starts = [0] if buffer.startswith(marker) else []
        index = buffer.find(b"\n" + marker)
        if index >= 0:
            starts.append(index + 1)
        if starts:
            start = min(starts)
            prefix = buffer[:start]
            if prefix.endswith(b"\r\n"):
                prefix = prefix[:-2]
            elif prefix.endswith(b"\n"):
                prefix = prefix[:-1]
            remainder = buffer[start:]
            end = remainder.find(b"\n")
            if end < 0:
                if len(remainder) > len(marker) + 1024:
                    if output is not None:
                        write_with_disk_reserve(output, buffer[:start + 1])
                    buffer = buffer[start + 1:]
                continue
            boundary_line = remainder[:end].rstrip(b"\r")
            if boundary_line not in {marker, closing}:
                if output is not None:
                    write_with_disk_reserve(output, buffer[:start + 1])
                buffer = buffer[start + 1:]
                continue
            unread = len(remainder) - end - 1
            if unread:
                stream.seek(stream.tell() - unread)
            if output is not None and prefix:
                write_with_disk_reserve(output, prefix)
            return boundary_line
        if len(buffer) > keep:
            if output is not None:
                write_with_disk_reserve(output, buffer[:-keep])
            buffer = buffer[-keep:]


def archive_parts(
    path: Path, wanted: set[str], directory: Path
) -> dict[str, tuple[Path, str]]:
    wanted_keys = wanted | {normalized_url(item) for item in wanted}
    parts: dict[str, tuple[Path, str]] = {}
    with path.open("rb") as stream:
        message = mime_headers(stream)
        boundary = message.get_boundary()
        if not isinstance(boundary, str) or not boundary or len(boundary) > 200 or "\n" in boundary or "\r" in boundary:
            raise OperationError("MHTML boundary is invalid")
        marker = b"--" + boundary.encode("ascii", errors="strict")
        closing = marker + b"--"
        boundary_line = copy_mime_body(stream, None, marker, closing)
        index = 0
        while boundary_line != closing:
            headers = mime_headers(stream)
            location = str(headers.get("Content-Location", "")).strip()
            selected = location in wanted_keys or normalized_url(location) in wanted_keys
            encoded_path = directory / f"archive-{index:04d}.encoded"
            output = encoded_path.open("wb") if selected else None
            try:
                boundary_line = copy_mime_body(stream, output, marker, closing)
            finally:
                if output is not None:
                    output.close()
            if selected:
                decoded_path = directory / f"archive-{index:04d}.bin"
                decode_mime_body(encoded_path, decoded_path, str(headers.get("Content-Transfer-Encoding", "")).lower())
                encoded_path.unlink()
                item = (decoded_path, headers.get_content_type())
                parts[location] = item
                parts[normalized_url(location)] = item
                index += 1
            if boundary_line == closing:
                break
    return parts


def video_binary(body: bytes, media_type: str) -> bool:
    lowered = media_type.lower()
    brands = body[8:32] if len(body) >= 32 and body[4:8] == b"ftyp" else b""
    still_image = lowered.startswith("image/") and any(brand in brands for brand in (b"avif", b"avis", b"heic", b"heix", b"mif1"))
    audio_mp4 = lowered.startswith("audio/") and any(brand in brands for brand in (b"M4A ", b"M4B ", b"M4P "))
    return (
        lowered.startswith("video/")
        or (bool(brands) and not still_image and not audio_mp4)
        or body.startswith(b"\x1aE\xdf\xa3")
        or (len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"AVI ")
        or body.startswith(b"FLV\x01")
        or (len(body) > 376 and body[0] == body[188] == body[376] == 0x47)
        or (body.startswith(b"OggS") and b"theora" in body.lower())
        or body.startswith(b"0&\xb2u\x8ef\xcf\x11\xa6\xd9\x00\xaa\x00b\xcel")
    )


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_file(path: Path, media_type: str) -> bool:
    with path.open("rb") as file:
        return video_binary(file.read(4096), media_type)


class SafeSvg(xml.sax.handler.ContentHandler):
    def processingInstruction(self, target: str, data: str) -> None:
        raise OperationError("SVG processing instructions are not allowed")

    def startElement(self, name: str, attributes: Any) -> None:
        if name.lower().split(":")[-1] in {
            "animate", "animatemotion", "animatetransform", "discard", "foreignobject", "iframe",
            "mpath", "object", "script", "set", "style",
        }:
            raise OperationError("SVG active content is not allowed")
        for key in attributes.getNames():
            lowered = key.lower().split(":")[-1]
            value = re.sub(
                r"\\([0-9a-fA-F]{1,6})[ \t\r\n\f]?|\\(.)",
                lambda match: chr(int(match.group(1), 16)) if match.group(1) else (match.group(2) or ""),
                str(attributes.getValue(key)),
            ).strip().lower()
            if lowered.startswith("on") or (lowered == "style" and ("url(" in value or "@import" in value)):
                raise OperationError("SVG active content is not allowed")
            if lowered == "href" and value and not value.startswith("#"):
                raise OperationError("SVG external content is not allowed")
            if lowered == "base" and value:
                raise OperationError("SVG external content is not allowed")
            urls = [item.strip(" \t\r\n'\"") for item in re.findall(r"url\s*\(([^)]*)\)", value)]
            if "javascript:" in value or "data:text/html" in value or any(
                item and not item.startswith("#") for item in urls
            ):
                raise OperationError("SVG active content is not allowed")


def safe_svg_file(path: Path) -> bool:
    try:
        tail = b""
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(64 * 1024), b""):
                lowered = (tail + chunk).lower()
                if b"<!doctype" in lowered or b"<!entity" in lowered:
                    return False
                tail = lowered[-32:]
        parser = xml.sax.make_parser()
        parser.setFeature(xml.sax.handler.feature_external_ges, False)
        parser.setFeature(xml.sax.handler.feature_external_pes, False)
        parser.setContentHandler(SafeSvg())
        parser.parse(str(path))
    except (OSError, xml.sax.SAXException, OperationError):
        return False
    return True


def permitted_media_type(body: bytes, actual: str, declared: str) -> str:
    actual = actual.split(";", 1)[0].strip().lower()
    declared = declared.split(";", 1)[0].strip().lower()
    if video_binary(body, actual) or video_binary(body, declared):
        return ""
    if declared == "image/svg+xml" and b"<svg" in body.lower():
        return "image/svg+xml"
    def signature(media_type: str) -> bool:
        if media_type == "text/vtt":
            return body.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"WEBVTT")
        if media_type == "application/x-subrip":
            return re.search(rb"\d+\s*\r?\n\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->", body) is not None
        if media_type.startswith("text/") or media_type == "application/json":
            return b"\x00" not in body
        if media_type == "image/jpeg":
            return body.startswith(b"\xff\xd8\xff")
        if media_type == "image/png":
            return body.startswith(b"\x89PNG\r\n\x1a\n")
        if media_type == "image/gif":
            return body.startswith((b"GIF87a", b"GIF89a"))
        if media_type == "image/webp":
            return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
        if media_type == "image/svg+xml":
            lowered = body.lower()
            unsafe = re.search(
                br"<(?:script|foreignobject|iframe|object|embed)\b|\bon[a-z]+\s*=|"
                br"(?:href|xlink:href)\s*=\s*['\"]\s*(?:https?:|javascript:|data:text/html)|"
                br"(?:url\s*\(|@import)\s*['\"]?\s*https?:",
                lowered,
            )
            return b"<svg" in lowered[:4096] and unsafe is None
        if media_type in {"image/avif", "image/heic", "image/heif"}:
            return len(body) >= 12 and body[4:8] == b"ftyp" and not video_binary(body, media_type)
        if media_type == "image/bmp":
            return body.startswith(b"BM")
        if media_type in {"image/tiff", "image/x-tiff"}:
            return body.startswith((b"II*\x00", b"MM\x00*"))
        if media_type in {"image/x-icon", "image/vnd.microsoft.icon"}:
            return body.startswith(b"\x00\x00\x01\x00")
        if media_type in {"audio/mpeg", "audio/mp3"}:
            return body.startswith(b"ID3") or (len(body) >= 2 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0)
        if media_type in {"audio/wav", "audio/wave", "audio/x-wav"}:
            return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WAVE"
        if media_type == "audio/flac":
            return body.startswith(b"fLaC")
        if media_type in {"audio/ogg", "application/ogg"}:
            return body.startswith(b"OggS") and b"theora" not in body.lower()
        if media_type in {"audio/mp4", "audio/x-m4a"}:
            return len(body) >= 12 and body[4:8] == b"ftyp" and not video_binary(body, media_type)
        if media_type == "application/pdf":
            return body.startswith(b"%PDF")
        if media_type == "application/rtf":
            return body.startswith(b"{\\rtf")
        if media_type in {
            "application/pdf", "application/epub+zip", "application/json", "application/rtf",
            "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
            "application/vnd.oasis.opendocument.presentation", "application/vnd.oasis.opendocument.spreadsheet",
            "application/vnd.oasis.opendocument.text", "application/x-subrip",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            return body.startswith(b"PK") or body.startswith(b"\xd0\xcf\x11\xe0")
        return False

    for subtitle_type in (actual, declared):
        if subtitle_type in {"text/vtt", "application/x-subrip"} and signature(subtitle_type):
            return subtitle_type
    safe_text_types = {"text/plain", "text/csv", "text/markdown", "text/tab-separated-values"}
    if actual in safe_text_types and declared in {*safe_text_types, "", "application/octet-stream"}:
        return declared if declared in safe_text_types else actual
    def media_family(media_type: str) -> str:
        if media_type.startswith("image/"):
            return "image"
        if media_type.startswith("audio/") or media_type == "application/ogg":
            return "audio"
        if media_type == "application/json":
            return "json"
        if media_type.startswith("text/") or media_type == "application/x-subrip":
            return "text"
        if media_type.startswith("application/"):
            return "document"
        return ""

    compatible_actual = declared in {"", "application/octet-stream"} or (
        media_family(actual) and media_family(actual) == media_family(declared)
    )
    if (actual and not actual.startswith("text/") and actual != "application/octet-stream"
            and compatible_actual and signature(actual)):
        return actual
    if declared and not declared.startswith("text/") and declared != "application/octet-stream":
        return declared if signature(declared) else ""
    if actual not in {"", "application/octet-stream"}:
        return ""
    return declared if signature(declared) else ""


def permitted_media_file(path: Path, actual: str, declared: str) -> str:
    actual_type = actual.split(";", 1)[0].strip().lower()
    declared_type = declared.split(";", 1)[0].strip().lower()
    if "image/svg+xml" in {actual_type, declared_type}:
        return "image/svg+xml" if safe_svg_file(path) else ""
    with path.open("rb") as file:
        media_type = permitted_media_type(file.read(4096), actual, declared)
    return media_type if media_type != "image/svg+xml" or safe_svg_file(path) else ""


def stored_asset_name(raw: dict[str, Any], media_type: str) -> str:
    name = safe_asset_path(raw.get("name"), "asset name")
    extension = mimetypes.guess_extension(media_type, strict=False)
    current_type = mimetypes.guess_type(name.name, strict=False)[0] or ""
    mismatched_type = bool(current_type and current_type != media_type)
    if extension and (name.suffix.lower() in {"", ".bin"} or mismatched_type):
        name = name.with_suffix(extension) if name.suffix else name.with_name(name.name + extension)
    return name.as_posix()


def stored_asset(directory: Path, raw: dict[str, Any], body: bytes, media_type: str = "") -> dict[str, Any]:
    asset_id = raw.get("id")
    if not isinstance(asset_id, str) or not asset_id:
        raise OperationError("remote asset requires a stable id")
    stored_type = media_type or str(raw.get("media_type") or "application/octet-stream")
    name = stored_asset_name(raw, stored_type)
    staged_name = f"assets/{name}"
    target = directory.joinpath(*Path(staged_name).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        write_with_disk_reserve(output, body)
    return {
        "name": name,
        "staged_name": staged_name,
        "placeholder": raw.get("placeholder") or f"lbrain-asset://{asset_id}",
        "media_type": stored_type,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size": len(body),
    }


def stored_asset_file(directory: Path, raw: dict[str, Any], source: Path, media_type: str = "") -> dict[str, Any]:
    asset_id = raw.get("id")
    if not isinstance(asset_id, str) or not asset_id:
        raise OperationError("remote asset requires a stable id")
    stored_type = media_type or str(raw.get("media_type") or "application/octet-stream")
    name = stored_asset_name(raw, stored_type)
    staged_name = f"assets/{name}"
    target = directory.joinpath(*Path(staged_name).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_file, target.open("wb") as output:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            write_with_disk_reserve(output, chunk)
    return {
        "name": name,
        "staged_name": staged_name,
        "placeholder": raw.get("placeholder") or f"lbrain-asset://{asset_id}",
        "media_type": stored_type,
        "sha256": file_hash(target),
        "size": target.stat().st_size,
    }


def prepare_snapshot(
    payload: dict[str, Any],
    snapshot: Path,
    kind: str,
    snapshot_type: str,
    directory: Path,
    streamed: dict[str, tuple[Path, str]],
) -> dict[str, Any]:
    remote = payload.pop("remote_assets", [])
    if not isinstance(remote, list) or any(not isinstance(item, dict) for item in remote):
        raise OperationError("remote_assets must be a list of objects")
    assets: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    replacements: list[tuple[str, str]] = []
    content_replacements: list[tuple[str, str]] = []

    if kind == "binary":
        if len(remote) != 1:
            raise OperationError("a direct file stream requires exactly one asset")
        if streamed:
            raise OperationError("a direct file stream cannot include attachments")
        item = remote[0]
        declared_type = str(item.get("media_type", ""))
        media_type = permitted_media_file(snapshot, snapshot_type, declared_type)
        if not media_type:
            raise OperationError("direct file type is not an allowed non-video asset")
        asset = stored_asset_file(directory, item, snapshot, media_type)
        assets.append(asset)
        content_replacements.append((str(item.get("url", "")), str(asset["placeholder"])))
    elif kind in {"mhtml", "none"}:
        remote_ids = {item.get("id") for item in remote if isinstance(item.get("id"), str)}
        if not set(streamed).issubset(remote_ids):
            raise OperationError("stream attachment is not declared by remote_assets")
        needs_archive = any(
            item.get("id") not in streamed and not str(item.get("media_type", "")).startswith("video/")
            for item in remote
        )
        wanted = {
            str(item.get("url")) for item in remote
            if item.get("id") not in streamed and not str(item.get("media_type", "")).startswith("video/")
        }
        parts = archive_parts(snapshot, wanted, directory) if kind == "mhtml" and needs_archive else {}
        for item in remote:
            asset_id, source = item.get("id"), item.get("url")
            if not isinstance(asset_id, str) or not isinstance(source, str) or not source:
                raise OperationError("remote asset requires id and url")
            media_type = str(item.get("media_type") or "application/octet-stream")
            if media_type.startswith("video/"):
                if asset_id in streamed:
                    raise OperationError("video binaries are not accepted")
                continue
            if asset_id in streamed:
                path, streamed_type = streamed[asset_id]
                archived_type = streamed_type
                effective_type = permitted_media_file(path, archived_type, media_type)
                if not path.stat().st_size or not effective_type:
                    failures.append({"id": asset_id, "url": source})
                    continue
                asset = stored_asset_file(directory, item, path, effective_type)
            else:
                found = parts.get(source) or parts.get(normalized_url(source))
                if found is None:
                    failures.append({"id": asset_id, "url": source})
                    continue
                path, archived_type = found
                effective_type = permitted_media_file(path, archived_type, media_type)
                if not path.stat().st_size or not effective_type:
                    failures.append({"id": asset_id, "url": source})
                    continue
                asset = stored_asset_file(directory, item, path, effective_type)
            assets.append(asset)
            replacements.append((source, f"../{quote(str(asset['name']), safe='/')}"))
            content_replacements.append((source, str(asset["placeholder"])))
    else:
        raise OperationError("snapshot_kind must be none, binary, or mhtml")

    html_replacements = {
        item["url"]: f"about:blank#lbrain-missing-{item['id']}" for item in failures
    }
    html_replacements.update(replacements)
    markdown_replacements = {
        item["url"]: f"lbrain-missing://{item['id']}" for item in failures
    }
    markdown_replacements.update(content_replacements)
    snapshot_html = payload.pop("snapshot_html", "")
    if not isinstance(snapshot_html, str):
        raise OperationError("snapshot_html must be text")
    if snapshot_html:
        for source, local in sorted(html_replacements.items(), key=lambda item: len(item[0]), reverse=True):
            snapshot_html = replace_exact_url(snapshot_html, source, local)
            snapshot_html = replace_exact_url(snapshot_html, html.escape(source, quote=True), local)
        assets.append(
            stored_asset(
                directory,
                {
                    "id": "html-snapshot",
                    "name": "snapshot/page.html",
                    "placeholder": "lbrain-asset://html-snapshot",
                },
                snapshot_html.encode("utf-8"),
                "text/html",
            )
        )

    content = payload.get("content_markdown", "")
    if not isinstance(content, str):
        raise OperationError("content_markdown must be text")
    for source, placeholder in sorted(markdown_replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if source:
            content = replace_exact_url(content, source, placeholder)
    if failures:
        warnings = "\n".join(f"- Media could not be preserved: {item['id']}" for item in failures)
        content = f"{content}\n\n## Capture warnings\n\n{warnings}".strip()
        if payload.get("extraction_status") == "complete":
            payload["pre_media_extraction_status"] = "complete"
            payload["extraction_status"] = "partial"
    payload["content_markdown"] = content
    payload["assets"] = assets
    payload["failed_remote_assets"] = failures
    return payload


def receive_stream(
    first: dict[str, Any], stream: BinaryIO, responses: BinaryIO, directory: Path
) -> tuple[dict[str, Any], Path, str, str, dict[str, tuple[Path, str]]]:
    stream_id = required_stream_value(first, "stream_id", str)
    acknowledgements = first.get("acknowledgements") is True
    chunk_integrity = first.get("integrity") == "sha256-chunks"
    if acknowledgements != chunk_integrity:
        raise OperationError("capture stream integrity negotiation is invalid")
    payload_size = required_stream_value(first, "payload_size", int)
    snapshot_size = required_stream_value(first, "snapshot_size", int)
    if (
        not 0 <= payload_size <= MAX_PAYLOAD_BYTES
        or not 0 <= snapshot_size <= MAX_CAPTURE_ASSET_BYTES
    ):
        raise OperationError("capture stream exceeds its size limit")
    payload_hash = required_stream_value(first, "payload_sha256", str)
    snapshot_hash = required_stream_value(first, "snapshot_sha256", str)
    if not re.fullmatch(r"[0-9a-f]{64}", payload_hash) or (
        not chunk_integrity and not re.fullmatch(r"[0-9a-f]{64}", snapshot_hash)
    ) or (chunk_integrity and snapshot_hash and not re.fullmatch(r"[0-9a-f]{64}", snapshot_hash)):
        raise OperationError("capture stream hashes are invalid")
    kind = required_stream_value(first, "snapshot_kind", str)
    snapshot_type = required_stream_value(first, "snapshot_media_type", str)
    attachments = first.get("attachments", [])
    if not isinstance(attachments, list) or len(attachments) > 1000:
        raise OperationError("stream attachments are invalid")
    attachment_values: dict[str, tuple[int, str, str]] = {}
    for item in attachments:
        if not isinstance(item, dict):
            raise OperationError("stream attachment is invalid")
        asset_id, size, sha256, media_type = (
            item.get("id"), item.get("size"), item.get("sha256", ""), item.get("media_type", "")
        )
        if (
            not isinstance(asset_id, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]+", asset_id)
            or asset_id in attachment_values
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 0 <= size <= MAX_CAPTURE_ASSET_BYTES
            or not isinstance(sha256, str)
            or (not chunk_integrity and not re.fullmatch(r"[0-9a-f]{64}", sha256))
            or (chunk_integrity and sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256))
            or not isinstance(media_type, str)
        ):
            raise OperationError("stream attachment metadata is invalid")
        attachment_values[asset_id] = (size, sha256, media_type)
    required_bytes = payload_size + snapshot_size + sum(
        size for size, _, _ in attachment_values.values()
    )
    if required_bytes > MAX_CAPTURE_STREAM_BYTES:
        raise OperationError("capture stream exceeds its aggregate size limit")
    if required_bytes + CAPTURE_DISK_RESERVE_BYTES > shutil.disk_usage(directory).free:
        raise OperationError("not enough disk space for capture stream")
    payload_path, snapshot_path = directory / "payload.json", directory / "snapshot.bin"
    attachment_paths = {
        asset_id: directory / f"attachment-{index:04d}.bin"
        for index, asset_id in enumerate(attachment_values)
    }
    paths = {
        "payload": payload_path,
        "snapshot": snapshot_path,
        **{f"asset:{asset_id}": path for asset_id, path in attachment_paths.items()},
    }
    expected = {
        "payload": payload_size,
        "snapshot": snapshot_size,
        **{f"asset:{asset_id}": value[0] for asset_id, value in attachment_values.items()},
    }
    counts = dict.fromkeys(paths, 0)
    sequences = dict.fromkeys(paths, 0)
    hashes = {channel: hashlib.sha256() for channel in paths}
    for path in paths.values():
        path.touch()
    while True:
        message = read_message(stream)
        if message.get("protocol") != STREAM_PROTOCOL or message.get("stream_id") != stream_id:
            raise OperationError("capture stream identity changed")
        if message.get("type") == "end":
            break
        if message.get("type") != "chunk" or message.get("channel") not in paths:
            raise OperationError("capture stream message is invalid")
        channel = str(message["channel"])
        if message.get("sequence") != sequences[channel]:
            raise OperationError("capture stream chunk is out of order")
        data = message.get("data")
        if not isinstance(data, str):
            raise OperationError("capture stream chunk data is invalid")
        try:
            chunk = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as error:
            raise OperationError("capture stream chunk is not valid base64") from error
        if not chunk:
            raise OperationError("capture stream chunk must not be empty")
        chunk_hash = message.get("sha256")
        if chunk_integrity and (
            not isinstance(chunk_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", chunk_hash)
            or hashlib.sha256(chunk).hexdigest() != chunk_hash
        ):
            raise OperationError("capture stream chunk hash mismatch")
        counts[channel] += len(chunk)
        if counts[channel] > expected[channel]:
            raise OperationError("capture stream is larger than declared")
        with paths[channel].open("ab") as output:
            write_with_disk_reserve(output, chunk)
        hashes[channel].update(chunk)
        if acknowledgements:
            write_message(responses, {
                "protocol": STREAM_PROTOCOL,
                "type": "ack",
                "stream_id": stream_id,
                "channel": channel,
                "sequence": sequences[channel],
            })
        sequences[channel] += 1
    if counts != expected:
        raise OperationError("capture stream is incomplete")
    if hashes["payload"].hexdigest() != payload_hash:
        raise OperationError("capture payload hash mismatch")
    if snapshot_hash and hashes["snapshot"].hexdigest() != snapshot_hash:
        raise OperationError("capture snapshot hash mismatch")
    for asset_id, path in attachment_paths.items():
        expected_hash = attachment_values[asset_id][1]
        if expected_hash and hashes[f"asset:{asset_id}"].hexdigest() != expected_hash:
            raise OperationError("capture attachment hash mismatch")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OperationError("capture payload must be an object")
    return payload, snapshot_path, kind, snapshot_type, {
        asset_id: (path, attachment_values[asset_id][2]) for asset_id, path in attachment_paths.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--staging-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        first = read_message(sys.stdin.buffer)
        staging_root = args.staging_root.resolve() if args.staging_root else None
        if first.get("protocol") == STREAM_PROTOCOL:
            if first.get("type") != "begin":
                raise OperationError("capture stream must begin with a begin message")
            if staging_root is not None:
                staging_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="lbrain-stream-", dir=staging_root) as temporary:
                directory = Path(temporary)
                payload, snapshot, kind, snapshot_type, attachments = receive_stream(
                    first, sys.stdin.buffer, sys.stdout.buffer, directory
                )
                payload = prepare_snapshot(payload, snapshot, kind, snapshot_type, directory, attachments)
                with operation_lock(root):
                    result = capture_bundle(root, payload, directory)
        else:
            with operation_lock(root):
                result = capture_bundle(root, first, staging_root)
        write_message(sys.stdout.buffer, result)
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, OperationError) as error:
        write_message(
            sys.stdout.buffer,
            {
                "operation": "capture.bundle",
                "status": "failed",
                "target": "",
                "affected_paths": [],
                "error": str(error),
                "validation": {"ok": False, "message": "operation rejected"},
                "rollback": None,
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
