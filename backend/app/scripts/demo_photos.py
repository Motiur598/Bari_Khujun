"""Drawn stand-in photos for the demo listings: simple rooms and building fronts, each marked DEMO PHOTO.

They go through the same pipeline as real uploads (app.utils.file_security.render_listing_photo).
"""

import io
import random

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 800
WALLS = [(236, 226, 208), (214, 228, 222), (232, 214, 206), (222, 222, 236), (240, 232, 214)]
FLOORS = [(168, 128, 92), (190, 182, 170), (150, 110, 80), (204, 196, 180)]
FURNITURE = [(90, 120, 160), (150, 90, 80), (110, 140, 100), (200, 180, 140)]
FACADES = [(226, 220, 210), (200, 190, 175), (230, 214, 190), (210, 214, 220)]


def _shade(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, channel + amount)) for channel in color)


def _label(draw: ImageDraw.ImageDraw) -> None:
    font = ImageFont.load_default(size=30)
    left, top, right, bottom = draw.textbbox((0, 0), "DEMO PHOTO", font=font)
    x, y = WIDTH - (right - left) - 36, HEIGHT - (bottom - top) - 36
    draw.rectangle((x - 14, y - 10, x + right - left + 14, y + bottom - top + 16), fill=(27, 36, 48))
    draw.text((x, y), "DEMO PHOTO", font=font, fill=(255, 255, 255))


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def room(rng: random.Random) -> bytes:
    wall, floor, sofa = rng.choice(WALLS), rng.choice(FLOORS), rng.choice(FURNITURE)
    image = Image.new("RGB", (WIDTH, HEIGHT), wall)
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 300, 140, 900, 520  # the back wall
    draw.polygon([(0, 0), (left, top), (left, bottom), (0, HEIGHT)], fill=_shade(wall, -22))
    draw.polygon([(WIDTH, 0), (right, top), (right, bottom), (WIDTH, HEIGHT)], fill=_shade(wall, -22))
    draw.polygon([(0, 0), (WIDTH, 0), (right, top), (left, top)], fill=_shade(wall, 12))
    draw.polygon([(0, HEIGHT), (left, bottom), (right, bottom), (WIDTH, HEIGHT)], fill=floor)
    window = rng.randint(left + 40, right - 260)
    draw.rectangle((window, top + 50, window + 220, top + 230), fill=(170, 205, 230), outline=(255, 255, 255), width=10)
    draw.line((window + 110, top + 50, window + 110, top + 230), fill=(255, 255, 255), width=6)
    seat = rng.randint(left - 120, right - 340)
    draw.rectangle((seat, bottom - 110, seat + 360, bottom - 60), fill=_shade(sofa, -30))
    draw.rectangle((seat, bottom - 60, seat + 360, bottom + 90), fill=sofa)
    draw.polygon([(right + 60, top + 70), (right + 170, top + 40), (right + 170, bottom + 120), (right + 60, bottom + 40)], fill=(140, 100, 70))
    _label(draw)
    return _encode(image)


def building(rng: random.Random, floors: int) -> bytes:
    facade = rng.choice(FACADES)
    image = Image.new("RGB", (WIDTH, HEIGHT), (178, 208, 230))
    draw = ImageDraw.Draw(image)
    storeys = max(2, min(floors, 7))
    storey_height = 560 // storeys
    left, right, ground = 300, 900, 700
    draw.rectangle((0, ground, WIDTH, HEIGHT), fill=(150, 150, 140))
    draw.rectangle((left, ground - storey_height * storeys, right, ground), fill=facade)
    for storey in range(storeys):
        y = ground - storey_height * (storey + 1)
        draw.line((left, y, right, y), fill=_shade(facade, -25), width=4)
        for column in range(4):
            x = left + 40 + column * 140
            if storey == 0 and column == 1:
                draw.rectangle((x, y + 30, x + 90, ground), fill=(110, 80, 60))  # the gate
            else:
                draw.rectangle((x, y + 25, x + 90, y + storey_height - 20), fill=(120, 150, 170), outline=(255, 255, 255), width=4)
    _label(draw)
    return _encode(image)


def demo_photos(seed: int, floors: int) -> list[bytes]:
    """The building front first (the cover), then two rooms."""
    rng = random.Random(seed)
    return [building(rng, floors), room(rng), room(rng)]
