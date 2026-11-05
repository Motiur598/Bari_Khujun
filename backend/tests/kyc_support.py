"""Synthetic ID card photos, and a stand-in for the OCR and face models, for the automated KYC tests.

The photo-quality checks run for real on these images. Reading text and recognising faces need large models, so
tests swap `read_card` for `FakeCards`, which still takes real fingerprints of the card photos but lets each test say
what name, number and face the card shows.
"""

import io
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.utils import id_card_verifier as verifier


def card_photo(seed: int = 1, *, blur: float = 0, dark: bool = False) -> bytes:
    """A card lying on a desk. Each seed draws a different card face; the same seed draws the same one."""
    rng = random.Random(seed)
    card = Image.new("RGB", (856, 540), (232, 240, 228))
    draw = ImageDraw.Draw(card)
    draw.rectangle((0, 0, 856, 70), fill=(20, 110, 60))
    for _ in range(28):
        x, y = rng.randrange(20, 800), rng.randrange(90, 500)
        draw.rectangle((x, y, x + rng.randrange(20, 140), y + rng.randrange(8, 40)), fill=tuple(rng.randrange(0, 200) for _ in range(3)))
    desk = Image.new("RGB", (1280, 960), (92, 70, 52))
    desk.paste(card.resize((685, 432)), (300, 260))
    if blur:
        desk = desk.filter(ImageFilter.GaussianBlur(blur))
    if dark:
        desk = Image.eval(desk, lambda value: value // 6)
    buffer = io.BytesIO()
    desk.save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


def face_vector(seed: int) -> list[float]:
    vector = np.random.default_rng(seed).normal(size=128)
    return list(vector / np.linalg.norm(vector))


class FakeCards:
    """Replaces verifier.read_card. The photo checks and card fingerprints are real; the card then "shows" the name,
    number and face (`face_seed`, or None for no portrait) last given to show()."""

    def __init__(self):
        # A number and face of its own, so a card from one test never matches another test's.
        self.name, self.number, self.face_seed = "Test Owner", str(random.randrange(10**9, 10**10)), random.randrange(10**6)
        self.calls = 0

    def show(self, name: str, number: str, face_seed: int | None = 1) -> "FakeCards":
        self.name, self.number, self.face_seed = name, number, face_seed
        return self

    def __call__(self, front: bytes, back: bytes, doc_type: str, profile_name: str) -> verifier.CardReading:
        self.calls += 1
        sides = {"front": verifier.scan_side(front), "back": verifier.scan_side(back)}
        mistakes = [verifier.Mistake(side, code) for side, scan in sides.items() for code in scan.mistakes]
        if mistakes:
            return verifier.CardReading(mistakes=mistakes)
        if self.face_seed is None:
            return verifier.CardReading(mistakes=[verifier.Mistake("front", "NO_PHOTO")])
        similarity = verifier.name_similarity(self.name, profile_name)
        if similarity < verifier.NAME_MIN_SIMILARITY:
            return verifier.CardReading(mistakes=[verifier.Mistake("front", "NAME_MISMATCH")])
        face = {
            "face_bbox": [10, 10, 100, 120],
            "embedding": face_vector(self.face_seed),
            "pixel_signature_256": face_vector(1000 + self.face_seed) * 2,
            "phash": f"{random.Random(self.face_seed).getrandbits(64):016x}",
        }
        return verifier.CardReading(
            mistakes=[],
            extracted_name=self.name,
            extracted_id_number=self.number,
            name_similarity=similarity,
            front=verifier.card_fingerprint(sides["front"]),
            back=verifier.card_fingerprint(sides["back"]),
            face=face,
        )
