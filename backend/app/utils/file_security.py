"""Upload validation and private file serving.

Uploads are identified by their first bytes, never by the client's Content-Type or file name. They're stored
under random names outside any public folder and are only ever sent back through authenticated endpoints.
"""

import hashlib
import io
import re
import unicodedata
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

JPEG, PNG, WEBP, PDF = "image/jpeg", "image/png", "image/webp", "application/pdf"
# KYC and title deeds: the formats the spec allows, nothing else.
DOCUMENT_TYPES = (JPEG, PNG, PDF)
# Condition, repair and dispute photos; phones commonly produce WebP as well.
PHOTO_TYPES = (JPEG, PNG, WEBP)

_EXTENSIONS = {JPEG: ".jpg", PNG: ".png", WEBP: ".webp", PDF: ".pdf"}
_HEADER_BYTES = 2048
_CHUNK_BYTES = 64 * 1024
# PDF features that run code or smuggle files when an admin opens the document.
_PDF_ACTIVE_CONTENT = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|XFA|OpenAction|AA)\b")


def detect_type(header: bytes) -> str | None:
    if header.startswith(b"\xff\xd8\xff"):
        return JPEG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if header.startswith(b"%PDF-"):
        return PDF
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return WEBP
    return None


def _check_image(content: bytes) -> None:
    # The header alone can be faked (a script with a PNG prefix); make sure the whole file decodes as an image.
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That image file is damaged or isn't really an image")


def _check_pdf(content: bytes) -> None:
    if b"%%EOF" not in content[-2048:]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That PDF is incomplete or damaged")
    if _PDF_ACTIVE_CONTENT.search(content):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "PDFs with scripts, launch actions or embedded files aren't accepted. Export or scan it again as a plain PDF.",
        )


def safe_display_name(filename: str | None, fallback: str) -> str:
    """The original name, for display only: no directories, control characters or odd Unicode, max 120 chars."""
    name = unicodedata.normalize("NFKC", filename or "")
    name = re.split(r"[\\/]", name)[-1]
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    return name[:120] or fallback


async def _read_limited(upload: UploadFile, max_bytes: int | None = None) -> bytes:
    """Read in chunks and stop as soon as the size limit is passed, rather than loading an unbounded file."""
    max_bytes = max_bytes or settings.upload_max_bytes
    chunks, size = [], 0
    while chunk := await upload.read(_CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


# Phone photos of ID cards are often larger than other uploads.
ID_PHOTO_MAX_BYTES = 10 * 1024 * 1024


async def read_id_photo(upload: UploadFile) -> tuple[bytes, str | None]:
    """An ID card photo's bytes and its type (JPEG, PNG or WebP by its first bytes; None for anything else, which the
    verifier reports as a photo it can't open)."""
    content = await _read_limited(upload, ID_PHOTO_MAX_BYTES)
    content_type = detect_type(content[:_HEADER_BYTES]) if content else None
    return content, content_type if content_type in PHOTO_TYPES else None


async def store_bytes(content: bytes, content_type: str, folder: Path, filename: str | None) -> dict:
    """Save already-validated content like store_upload does, returning the same metadata."""
    file_id = uuid4().hex
    storage_path = _inside_uploads(folder / f"{file_id}{_EXTENSIONS[content_type]}")
    await run_in_threadpool(storage_path.parent.mkdir, parents=True, exist_ok=True)
    await run_in_threadpool(storage_path.write_bytes, content)
    return {
        "file_id": file_id,
        "original_filename": safe_display_name(filename, f"{file_id}{_EXTENSIONS[content_type]}"),
        "content_type": content_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "storage_path": str(storage_path),
    }


def _inside_uploads(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(settings.upload_dir.resolve()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid file location")
    return resolved


async def store_upload(file: UploadFile, folder: Path, allowed: tuple[str, ...] = DOCUMENT_TYPES) -> dict:
    """Validate an upload and save it as <uuid4 hex><extension> under `folder` (inside the uploads directory).

    Returns metadata including a SHA-256 fingerprint, so either party can show later that a file wasn't swapped.
    """
    content = await _read_limited(file)
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    content_type = detect_type(content[:_HEADER_BYTES])
    if content_type not in allowed:
        kinds = " or ".join({JPEG: "JPEG", PNG: "PNG", WEBP: "WebP", PDF: "PDF"}[t] for t in allowed)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Only {kinds} files are accepted")
    if content_type == PDF:
        _check_pdf(content)
    else:
        await run_in_threadpool(_check_image, content)
    return await store_bytes(content, content_type, folder, file.filename)


# Listing photos are re-encoded: at most this many pixels on the long edge, plus a thumbnail for cards and map pins.
PHOTO_MAX_EDGE = 1600
THUMB_MAX_EDGE = 640
# Refuse images that would take too much memory to decode (a small file can still be a huge PNG).
MAX_PHOTO_PIXELS = 40_000_000


def render_listing_photo(content: bytes, full: Path, thumb: Path) -> tuple[int, int]:
    """Re-encode a listing photo as JPEG: turned upright, metadata (including a phone's GPS position) dropped, resized,
    with a thumbnail. Only decoded pixels are written, so nothing else from the uploaded file ever reaches a browser."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > MAX_PHOTO_PIXELS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That photo's resolution is too high. Upload a smaller copy.")
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA", "P"):
                # Transparent areas become white rather than black.
                image = image.convert("RGBA")
                flattened = Image.new("RGB", image.size, "white")
                flattened.paste(image, mask=image.getchannel("A"))
                image = flattened
            else:
                image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That image file is damaged or isn't really an image")
    image.thumbnail((PHOTO_MAX_EDGE, PHOTO_MAX_EDGE))
    image.save(full, "JPEG", quality=82, optimize=True, progressive=True)
    width, height = image.size
    image.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
    image.save(thumb, "JPEG", quality=78, optimize=True, progressive=True)
    return width, height


def listing_photo_paths(folder: Path, photo_id: str) -> tuple[Path, Path]:
    return _inside_uploads(folder / f"{photo_id}.jpg"), _inside_uploads(folder / f"{photo_id}_thumb.jpg")


async def store_listing_photo(file: UploadFile, folder: Path) -> dict:
    """Validate a listing photo (JPEG, PNG or WebP, by its bytes) and store it re-encoded. Returns {id, width, height}."""
    content = await _read_limited(file)
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if detect_type(content[:_HEADER_BYTES]) not in PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only JPEG, PNG or WebP photos are accepted")
    photo_id = uuid4().hex
    full, thumb = listing_photo_paths(folder, photo_id)
    await run_in_threadpool(full.parent.mkdir, parents=True, exist_ok=True)
    width, height = await run_in_threadpool(render_listing_photo, content, full, thumb)
    return {"id": photo_id, "width": width, "height": height}


# Listing videos are MP4 / QuickTime (what phones record), kept as uploaded apart from their metadata.
VIDEO_TYPES = ("video/mp4", "video/quicktime")
MAX_VIDEO_SECONDS = 180
# Boxes that can hold a phone's GPS position, owner names or XMP. Turned into `free` boxes of the same size, so no
# offset in the file moves and the video plays exactly as before.
_VIDEO_METADATA_BOXES = {b"udta", b"meta", b"uuid"}
# Containers searched for those boxes: the file itself, the movie and each track.
_VIDEO_CONTAINERS = {b"moov", b"trak"}


def _video_boxes(f, start: int, end: int) -> list[tuple[bytes, int, int, int]]:
    """(type, offset, header size, total size) for each box between `start` and `end`. Raises ValueError unless the
    boxes are well formed and fill the range exactly, which is what an MP4 (ISO BMFF) file is made of."""
    boxes, offset = [], start
    while offset < end:
        f.seek(offset)
        header = f.read(8)
        if len(header) < 8:
            raise ValueError("truncated box header")
        size, kind = int.from_bytes(header[:4], "big"), header[4:]
        header_size = 8
        if size == 1:
            size, header_size = int.from_bytes(f.read(8), "big"), 16
        elif size == 0:
            size = end - offset
        # Box types are four printable characters (QuickTime also uses a leading copyright sign).
        if not all(0x20 <= byte <= 0x7E or byte == 0xA9 for byte in kind) or size < header_size or offset + size > end:
            raise ValueError("malformed box")
        boxes.append((kind, offset, header_size, size))
        offset += size
    return boxes


def _movie_duration(f, mvhd: tuple[bytes, int, int, int]) -> float | None:
    _, offset, header_size, _ = mvhd
    f.seek(offset + header_size)
    version = f.read(4)[0]
    f.seek(16 if version == 1 else 8, 1)  # creation and modification times
    timescale = int.from_bytes(f.read(4), "big")
    duration = int.from_bytes(f.read(8 if version == 1 else 4), "big")
    # Fragmented files can leave the duration at 0 (or all ones); then it simply isn't known.
    if not timescale or not duration or duration == (1 << (64 if version == 1 else 32)) - 1:
        return None
    return round(duration / timescale, 1)


def _clean_video(path: Path) -> float | None:
    """Check that the file is an MP4 / QuickTime movie, blank out its metadata boxes in place and return its length in
    seconds (None if the file doesn't say)."""
    size = path.stat().st_size
    with path.open("r+b") as f:
        try:
            top = _video_boxes(f, 0, size)
            if top[0][0] != b"ftyp":
                raise ValueError("no ftyp box first")
            moov = next((box for box in top if box[0] == b"moov"), None)
            if moov is None or not any(box[0] == b"mdat" for box in top):
                raise ValueError("no movie or media data")
            movie = _video_boxes(f, moov[1] + moov[2], moov[1] + moov[3])
            mvhd = next((box for box in movie if box[0] == b"mvhd"), None)
            if mvhd is None:
                raise ValueError("no movie header")
            duration = _movie_duration(f, mvhd)

            pending = list(top)
            while pending:
                kind, offset, header_size, box_size = pending.pop()
                if kind in _VIDEO_CONTAINERS:
                    pending.extend(_video_boxes(f, offset + header_size, offset + box_size))
                elif kind in _VIDEO_METADATA_BOXES:
                    f.seek(offset + header_size - 4)
                    f.write(b"free")
                    remaining = box_size - header_size
                    while remaining > 0:
                        step = min(remaining, _CHUNK_BYTES)
                        f.write(bytes(step))
                        remaining -= step
        except (ValueError, IndexError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That video file is damaged or isn't an MP4 or MOV video")
    if duration is not None and duration > MAX_VIDEO_SECONDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Keep the video under {MAX_VIDEO_SECONDS // 60} minutes")
    return duration


def listing_video_path(folder: Path, video_id: str) -> Path:
    return _inside_uploads(folder / f"{video_id}.mp4")


async def store_listing_video(file: UploadFile, folder: Path) -> dict:
    """Stream a listing video to disk (never more than video_max_bytes), check it really is an MP4 / QuickTime movie
    and strip the metadata that can carry where it was filmed. Returns {id, size_bytes, duration_seconds}."""
    video_id = uuid4().hex
    final = listing_video_path(folder, video_id)
    partial = _inside_uploads(folder / f"{video_id}.part")
    await run_in_threadpool(folder.mkdir, parents=True, exist_ok=True)
    size = 0
    try:
        with partial.open("wb") as out:
            while chunk := await file.read(_CHUNK_BYTES):
                size += len(chunk)
                if size > settings.video_max_bytes:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE, f"Videos can be up to {settings.video_max_bytes // (1024 * 1024)} MB"
                    )
                await run_in_threadpool(out.write, chunk)
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
        duration = await run_in_threadpool(_clean_video, partial)
        await run_in_threadpool(partial.replace, final)
    except BaseException:
        await run_in_threadpool(partial.unlink, missing_ok=True)
        raise
    return {"id": video_id, "size_bytes": size, "duration_seconds": duration}


def public_video_response(path: Path) -> FileResponse:
    """A listing video, public like the photos. FileResponse answers Range requests, so players can seek."""
    path = _inside_uploads(path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "public, max-age=31536000, immutable"})


def public_photo_response(path: Path) -> FileResponse:
    """A listing photo. Photos are public and their file names never change, so browsers may cache them for good."""
    path = _inside_uploads(path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return FileResponse(path, media_type=JPEG, headers={"Cache-Control": "public, max-age=31536000, immutable"})


def private_file_response(document: dict) -> FileResponse:
    """Stream a stored upload to an already-authorised requester. Callers must check access first."""
    path_value = document.get("storage_path") or document.get("path")
    if not path_value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    path = _inside_uploads(Path(path_value))
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(
        path,
        media_type=document.get("content_type", "application/octet-stream"),
        filename=safe_display_name(document.get("original_filename"), path.name),
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
