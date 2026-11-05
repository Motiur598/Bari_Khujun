"""Automated ID card checks (Feature 1): photo-quality "silly mistakes", reading the name and ID number, and the
fingerprints duplicate detection compares (Feature 20).

Everything in this module is server-side only. API responses carry nothing from it except the plain-language
mistake messages in MISTAKES: no scores, hashes, coordinates, thresholds or model names.

Each side of the card is found in the photo, straightened to a flat rectangle, and checked for blur, darkness, glare
and being cut off. The front must show the holder's portrait (found with OpenCV's YuNet face detector and described
with its SFace recogniser, so the same face on another account's card can be spotted) and readable text (EasyOCR,
English and Bengali). Models are downloaded on first use into settings.vision_model_dir.
"""

import hashlib
import io
import logging
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from rapidfuzz import fuzz
from rapidfuzz import utils as fuzz_utils

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- thresholds (never sent to clients)

MAX_EDGE = 1600
BLUR_MIN_VARIANCE = 70
DARK_MAX_BRIGHTNESS = 55
GLARE_LEVEL = 248
GLARE_MAX_SHARE = 0.04
CARD_MIN_SHARE = 0.15
BORDER_MARGIN = 0.02
NAME_MIN_SIMILARITY = 50
# Cards are straightened to this size (ID-1 proportions), long side horizontal.
CARD_SIZE = (856, 540)
FACE_MIN_SCORE = 0.7

# ---------------------------------------------------------------- what users are told

MISTAKES = {
    "BLURRY": "The photo is too blurry. Please hold your camera steady and tap on the ID card to focus.",
    "DARK": "The photo is too dark. Please take the picture in a well-lit room.",
    "GLARE": "Camera flash or light glare is covering part of the card. Turn off flash and tilt the card slightly.",
    "CUT_OFF": "Your ID card is either too far away or the edges are cut off. Place the entire card flat inside the camera frame.",
    "UNREADABLE": "We couldn't clearly read your Name or ID Number. Make sure your fingers aren't covering the text and the card is right-side up.",
    "NAME_MISMATCH": "The name on this ID card does not match the name on your Bari Khujun profile. Please fix any spelling typos in your profile name or upload your own ID card.",
    "NO_PHOTO": "We couldn't see your photo on the front of the card. Photograph the side with your picture, right-side up and without glare on it.",
    "NOT_AN_IMAGE": "This file isn't a photo we can open. Take a new picture of the card, or upload a JPEG, PNG or WebP photo.",
}


@dataclass
class Mistake:
    side: str  # "front" or "back"
    code: str

    @property
    def message(self) -> str:
        return MISTAKES[self.code]


@dataclass
class SideScan:
    """One side of the card, straightened. `card` is None when no card could be found in the photo."""

    image: np.ndarray
    card: np.ndarray | None
    card_bbox: list[int] | None
    mistakes: list[str] = field(default_factory=list)


@dataclass
class CardReading:
    """The result of checking both sides. `mistakes` empty means the photos are good enough to verify."""

    mistakes: list[Mistake]
    extracted_name: str | None = None
    extracted_id_number: str | None = None
    name_similarity: float | None = None
    front: dict | None = None
    back: dict | None = None
    face: dict | None = None


# ---------------------------------------------------------------- models (downloaded once, loaded lazily)

# (file name, download URL, SHA-256): a download that doesn't match is discarded rather than loaded.
_MODELS = {
    "yunet": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "sface": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}
_lock = threading.Lock()
_loaded: dict = {}


def _model_file(key: str) -> Path:
    name, url, sha256 = _MODELS[key]
    path = settings.vision_model_dir / name
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s", url)
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(url, partial)  # noqa: S310 (fixed https URL)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != sha256:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Downloaded {name} doesn't match its expected SHA-256")
        partial.replace(path)
    return path


def _face_models():
    with _lock:
        if "faces" not in _loaded:
            detector = cv2.FaceDetectorYN.create(str(_model_file("yunet")), "", (320, 320), FACE_MIN_SCORE, 0.3, 5000)
            recogniser = cv2.FaceRecognizerSF.create(str(_model_file("sface")), "")
            _loaded["faces"] = (detector, recogniser)
        return _loaded["faces"]


def _ocr_reader():
    with _lock:
        if "ocr" not in _loaded:
            import easyocr  # heavy (PyTorch): imported only when the first card is read

            folder = settings.vision_model_dir / "easyocr"
            folder.mkdir(parents=True, exist_ok=True)
            _loaded["ocr"] = easyocr.Reader(["en", "bn"], gpu=False, model_storage_directory=str(folder), verbose=False)
        return _loaded["ocr"]


def read_text(card: np.ndarray) -> list[str]:
    """The lines of text EasyOCR reads on a straightened card."""
    return [text.strip() for text in _ocr_reader().readtext(card, detail=0, paragraph=False) if text.strip()]


# ---------------------------------------------------------------- image helpers


def decode(content: bytes) -> np.ndarray | None:
    """An upload as a BGR array, turned upright (phone EXIF) and at most MAX_EDGE pixels on its long side."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > 40_000_000:
                return None
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return None
    image.thumbnail((MAX_EDGE, MAX_EDGE))
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def _order_corners(points: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    points = points.reshape(4, 2).astype(np.float32)
    total, diff = points.sum(axis=1), np.diff(points, axis=1).ravel()
    return np.array([points[np.argmin(total)], points[np.argmin(diff)], points[np.argmax(total)], points[np.argmax(diff)]], dtype=np.float32)


def find_card(image: np.ndarray) -> np.ndarray | None:
    """The four corners of the largest card-shaped quadrilateral in the photo, or None.

    Edges come from every colour channel, so a card whose colour differs from the table only in hue (a green band on
    brown wood looks the same in grey) still stands out. Cards have rounded corners, so a contour that isn't a clean
    four-pointed polygon still counts when it fills its rotated bounding rectangle.
    """
    height, width = image.shape[:2]
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    best, best_area = None, 0.0
    for low, high in ((30, 100), (50, 150), (75, 200)):
        edges = np.max([cv2.Canny(blurred[:, :, channel], low, high) for channel in range(3)], axis=0)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(contour)
            if area < 0.02 * width * height:
                break
            approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                corners = approx.reshape(4, 2)
            else:
                (_, _), (box_w, box_h), _ = rect = cv2.minAreaRect(contour)
                if area < 0.9 * box_w * box_h:
                    continue
                corners = cv2.boxPoints(rect)
            _, _, w, h = cv2.boundingRect(corners.astype(np.int32))
            # ID-1 cards are about 1.59:1; allow for perspective and portrait-style staff and student cards.
            if 1.15 <= max(w, h) / max(min(w, h), 1) <= 2.2 and area > best_area:
                best, best_area = corners, area
    return None if best is None else _order_corners(np.asarray(best))


def straighten(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """The card warped flat, as it was held: landscape cards landscape, portrait ones (some staff and student IDs)
    portrait. A card held sideways stays sideways, so its portrait isn't found and the user is asked to retake it."""
    top = np.linalg.norm(corners[1] - corners[0])
    side = np.linalg.norm(corners[3] - corners[0])
    size = CARD_SIZE if top >= side else CARD_SIZE[::-1]
    target = np.array([[0, 0], [size[0] - 1, 0], [size[0] - 1, size[1] - 1], [0, size[1] - 1]], dtype=np.float32)
    return cv2.warpPerspective(image, cv2.getPerspectiveTransform(corners, target), size)


def _sharpness(gray: np.ndarray, width: int = 1000) -> float:
    """Laplacian variance at a fixed width, so photos of any resolution are measured alike."""
    height = max(1, round(gray.shape[0] * width / gray.shape[1]))
    return float(cv2.Laplacian(cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA), cv2.CV_64F).var())


def scan_side(content: bytes) -> SideScan:
    """Find and straighten the card, and note the photo-quality mistakes on this side."""
    image = decode(content)
    if image is None:
        return SideScan(image=np.zeros((1, 1, 3), np.uint8), card=None, card_bbox=None, mistakes=["NOT_AN_IMAGE"])
    height, width = image.shape[:2]
    mistakes = []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.mean() < DARK_MAX_BRIGHTNESS:
        mistakes.append("DARK")

    corners = find_card(image)
    if corners is None:
        # No card edges found. A photo too blurry or too dark to show them is told that; otherwise the card is cut
        # off, or too far away to make out.
        if not mistakes and _sharpness(gray) < BLUR_MIN_VARIANCE:
            mistakes.append("BLURRY")
        return SideScan(image=image, card=None, card_bbox=None, mistakes=mistakes or ["CUT_OFF"])
    x, y, w, h = cv2.boundingRect(corners.astype(np.int32))
    margin_x, margin_y = width * BORDER_MARGIN, height * BORDER_MARGIN
    touches_edge = x <= margin_x or y <= margin_y or x + w >= width - margin_x or y + h >= height - margin_y
    too_small = cv2.contourArea(corners) < CARD_MIN_SHARE * width * height
    if too_small or touches_edge:
        mistakes.append("CUT_OFF")

    card = straighten(image, corners)
    card_gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    # A card too small in the frame looks soft once enlarged ("move closer" covers it), and so does a dark one.
    if not too_small and "DARK" not in mistakes and cv2.Laplacian(card_gray, cv2.CV_64F).var() < BLUR_MIN_VARIANCE:
        mistakes.append("BLURRY")
    if (card_gray > GLARE_LEVEL).mean() > GLARE_MAX_SHARE:
        mistakes.append("GLARE")
    return SideScan(image=image, card=card, card_bbox=[int(x), int(y), int(w), int(h)], mistakes=mistakes)


# ---------------------------------------------------------------- fingerprints


def _signature(gray: np.ndarray) -> list[float]:
    """16x16 grayscale thumbnail, mean-centred and unit length, so a dot product is a cosine similarity."""
    small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    small -= small.mean()
    norm = float(np.linalg.norm(small))
    return [round(float(value), 5) for value in (small / norm if norm else small)]


def card_fingerprint(scan: SideScan) -> dict:
    rgb = cv2.cvtColor(scan.card, cv2.COLOR_BGR2RGB)
    picture = Image.fromarray(rgb)
    return {
        "card_bbox": scan.card_bbox,
        "mean_rgb_pixels": [round(float(value), 2) for value in rgb.reshape(-1, 3).mean(axis=0)],
        "pixel_signature_256": _signature(cv2.cvtColor(scan.card, cv2.COLOR_BGR2GRAY)),
        "phash": str(imagehash.phash(picture)),
        "dhash": str(imagehash.dhash(picture)),
    }


def face_fingerprint(card: np.ndarray) -> dict | None:
    """The holder's portrait on the card: where it is, its SFace identity embedding, and a pixel fingerprint of the
    aligned face. None when no face is found."""
    detector, recogniser = _face_models()
    height, width = card.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(card)
    if faces is None or len(faces) == 0:
        return None
    face = max(faces, key=lambda row: row[2] * row[3])
    aligned = recogniser.alignCrop(card, face)
    embedding = recogniser.feature(aligned).ravel()
    embedding = embedding / (np.linalg.norm(embedding) or 1.0)
    return {
        "face_bbox": [int(value) for value in face[:4]],
        "embedding": [round(float(value), 6) for value in embedding],
        "pixel_signature_256": _signature(cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)),
        "phash": str(imagehash.phash(Image.fromarray(cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)))),
    }


# ---------------------------------------------------------------- reading the name and ID number

_BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NID_NUMBER = re.compile(r"(?<!\d)(\d{17}|\d{13}|\d{10})(?!\d)")
_ID_LABEL = re.compile(
    r"\b(?:nid|id|card|student|employee|staff|roll|reg(?:istration)?)\b[\s.]*(?:id|no|number|#)?[\s.:#\-]*([A-Z0-9][A-Z0-9/\-]{3,24})",
    re.IGNORECASE,
)
_NAME_LABEL = re.compile(r"^\s*name\s*[:.\-]?\s*(.*)$", re.IGNORECASE)
_NOT_A_NAME = re.compile(
    r"\b(government|republic|bangladesh|people|national|identity|card|university|college|institute|school|limited|ltd|"
    r"company|student|employee|staff|department|dept|date|birth|issue|valid|expiry|signature|holder|father|mother|"
    r"blood|address|id|nid|no|session|program|designation)\b",
    re.IGNORECASE,
)


def _compact_digits(line: str) -> str:
    # "123 456 7890" and "123-456-7890" are one number.
    return re.sub(r"(?<=\d)[\s\-](?=\d)", "", line.translate(_BENGALI_DIGITS))


def normalize_id(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper().translate(_BENGALI_DIGITS))


def extract_id_number(lines: list[str], doc_type: str) -> str | None:
    """The NID (10, 13 or 17 digits), or a student or job ID's number (after its label, or the longest token with
    at least 5 digits)."""
    compact = [_compact_digits(line) for line in lines]
    if doc_type == "NID":
        labelled = [line for line in compact if re.search(r"\b(id|nid)\b", line, re.IGNORECASE)]
        for line in labelled + compact:
            if match := _NID_NUMBER.search(line):
                return match.group(1)
        return None
    for line in compact:
        if (match := _ID_LABEL.search(line)) and sum(char.isdigit() for char in match.group(1)) >= 3:
            return normalize_id(match.group(1))
    tokens = [token for line in compact for token in re.findall(r"[A-Za-z0-9/\-]{5,}", line) if sum(c.isdigit() for c in token) >= 5]
    return normalize_id(max(tokens, key=len)) if tokens else None


# Titles many names start with. They're left out of comparisons, or every "Md. ..." would look half like every other.
_TITLES = re.compile(
    r"\b(md|mohd|mohammad|mohammed|muhammad|mst|most|mosammat|mr|mrs|ms|miss|sk|sheikh|shaikh|syed|sayed|dr|engr)\b\.?",
    re.IGNORECASE,
)


def _without_titles(name: str) -> str:
    stripped = _TITLES.sub(" ", name)
    return stripped if re.search(r"[A-Za-z]{2,}", stripped) else name


def name_similarity(a: str, b: str) -> float:
    """0-100, forgiving about word order, titles and a missing middle name ("Md. Abdur Rahim" vs "Abdur Rahim")."""
    return fuzz.token_set_ratio(_without_titles(a), _without_titles(b), processor=fuzz_utils.default_process)


def extract_name(lines: list[str], profile_name: str) -> tuple[str | None, float]:
    """The holder's name in Latin letters (after a "Name" label, or the line most like the profile name) and how
    similar it is to the profile name."""
    candidates = []
    for index, line in enumerate(lines):
        if match := _NAME_LABEL.match(line):
            after = match.group(1).strip() or (lines[index + 1] if index + 1 < len(lines) else "")
            candidates.append(after)
    for line in lines:
        words = re.findall(r"[A-Za-z][A-Za-z.']*", line)
        if len(words) >= 2 and not re.search(r"\d", line) and not _NOT_A_NAME.search(line):
            candidates.append(" ".join(words))
    candidates = [candidate for candidate in candidates if re.search(r"[A-Za-z]{2,}", candidate)]
    if not candidates:
        return None, 0.0
    best = max(candidates, key=lambda candidate: name_similarity(candidate, profile_name))
    return best, name_similarity(best, profile_name)


# ---------------------------------------------------------------- the whole check


def read_card(front: bytes, back: bytes, doc_type: str, profile_name: str) -> CardReading:
    """Check both sides for mistakes; if there are none, read the name and number and take the fingerprints."""
    sides = {"front": scan_side(front), "back": scan_side(back)}
    mistakes = [Mistake(side, code) for side, scan in sides.items() for code in scan.mistakes]
    if mistakes:
        # Photos that need retaking aren't read yet: the user hears about them straight away.
        return CardReading(mistakes=mistakes)

    front_scan = sides["front"]
    face = face_fingerprint(front_scan.card)
    if face is None:
        mistakes.append(Mistake("front", "NO_PHOTO"))
    lines = read_text(front_scan.card)
    if sides["back"].card is not None:
        lines += read_text(sides["back"].card)
    id_number = extract_id_number(lines, doc_type)
    name, similarity = extract_name(lines, profile_name)
    if not id_number or not name:
        mistakes.append(Mistake("front", "UNREADABLE"))
    elif similarity < NAME_MIN_SIMILARITY:
        mistakes.append(Mistake("front", "NAME_MISMATCH"))
    if mistakes:
        return CardReading(mistakes=mistakes)
    return CardReading(
        mistakes=[],
        extracted_name=name,
        extracted_id_number=id_number,
        name_similarity=similarity,
        front=card_fingerprint(front_scan),
        back=card_fingerprint(sides["back"]),
        face=face,
    )
