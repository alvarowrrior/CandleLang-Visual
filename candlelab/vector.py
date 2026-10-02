"""Geometría SVG compartida: cada apertura coincide con el cierre anterior."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
LEFT, TOP, BOTTOM, STEP, WICK = 32, 24, 24, 10, 2
GREEN, RED = "#19da91", "#ff536f"
BACKGROUND = "#0b1320"
BODY_WIDTH = 5


class CandleError(ValueError):
    pass


@dataclass(frozen=True)
class Candle:
    up: bool
    height: int


def positions(candles: list[Candle]):
    price = low = high = 0
    result = []
    for candle in candles:
        next_price = price - candle.height if candle.up else price + candle.height
        result.append((price, next_price))
        price = next_price
        low, high = min(low, price), max(high, price)
    return result, low, high


def dimensions(candles: list[Candle]):
    if not candles:
        return 800, 120, 0
    _, low, high = positions(candles)
    return LEFT * 2 + len(candles) * STEP, TOP + BOTTOM + high - low + 2 * WICK, TOP + WICK - low


def save_svg(candles: list[Candle], path: str | Path, protocol: str):
    coords, low, high = positions(candles)
    width, height, offset = dimensions(candles)
    root = ET.Element(f"{{{NS}}}svg", {
        "width": str(width), "height": str(height), "viewBox": f"0 0 {width} {height}",
        "data-protocol": protocol,
    })
    ET.SubElement(root, f"{{{NS}}}rect", {
        "x": "0", "y": "0", "width": str(width), "height": str(height), "fill": BACKGROUND,
    })
    group = ET.SubElement(root, f"{{{NS}}}g", {"id": "candles"})
    for n, (candle, (start, finish)) in enumerate(zip(candles, coords)):
        x = LEFT + n * STEP + 4
        top = offset + min(start, finish)
        color = GREEN if candle.up else RED
        ET.SubElement(group, f"{{{NS}}}line", {
            "x1": str(x), "x2": str(x), "y1": str(top - WICK),
            "y2": str(top + candle.height + WICK - 1), "stroke": color,
        })
        ET.SubElement(group, f"{{{NS}}}rect", {
            "x": str(x - 2), "y": str(top), "width": str(BODY_WIDTH),
            "height": str(candle.height), "fill": color,
        })
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def read_svg(path: str | Path, protocol: str, max_candles: int) -> list[Candle]:
    path = Path(path)
    if path.stat().st_size > 30_000_000:
        raise CandleError("SVG demasiado grande.")
    try:
        root = ET.parse(path).getroot()
        if root.tag != f"{{{NS}}}svg" or root.get("data-protocol") != protocol:
            raise CandleError("Protocolo SVG incorrecto.")
        width, height = int(root.get("width")), int(root.get("height"))
        groups = [node for node in root if node.tag == f"{{{NS}}}g" and node.get("id") == "candles"]
        if len(groups) != 1:
            raise CandleError("No se encontró la cinta de velas.")
        nodes = list(groups[0])
        if len(nodes) % 2 or len(nodes) // 2 > max_candles:
            raise CandleError("Número de velas inválido.")
        candles = []
        previous_close = first_open = None
        for n in range(0, len(nodes), 2):
            wick, body = nodes[n:n + 2]
            if wick.tag != f"{{{NS}}}line" or body.tag != f"{{{NS}}}rect":
                raise CandleError("Formas SVG incompatibles.")
            x = LEFT + (n // 2) * STEP + 4
            top, size = int(body.get("y")), int(body.get("height"))
            color = body.get("fill")
            if (size < 1 or color not in (GREEN, RED) or int(body.get("x")) != x - 2
                or int(body.get("width")) != BODY_WIDTH or int(wick.get("x1")) != x
                or int(wick.get("x2")) != x or int(wick.get("y1")) != top - WICK
                or int(wick.get("y2")) != top + size + WICK - 1
                or wick.get("stroke") != color):
                raise CandleError(f"Vela {n // 2} con geometría incorrecta.")
            up = color == GREEN
            open_y, close_y = (top + size, top) if up else (top, top + size)
            if previous_close is not None and previous_close != open_y:
                raise CandleError(f"La vela {n // 2} no abre al cierre anterior.")
            if first_open is None:
                first_open = open_y
            previous_close = close_y
            candles.append(Candle(up, size))
        expected_width, expected_height, expected_open = dimensions(candles)
        if (width, height) != (expected_width, expected_height) or (candles and first_open != expected_open):
            raise CandleError("Dimensiones incoherentes con el trazado.")
        return candles
    except CandleError:
        raise
    except (OSError, ET.ParseError, ValueError, TypeError) as exc:
        raise CandleError(f"Imagen ilegible: {exc}") from exc


def preview(candles: list[Candle], schematic: bool = False) -> Image.Image:
    """Vista parcial legible; HEX comprime potencias solo en pantalla."""
    if schematic:
        candles = [Candle(c.up, 5 + (c.height.bit_length() - 1) * 4) for c in candles]
    coords, low, high = positions(candles)
    width = max(400, LEFT * 2 + len(candles) * STEP)
    height = max(120, TOP + BOTTOM + high - low + 2 * WICK)
    image = Image.new("RGB", (width, height), (11, 19, 32))
    draw = ImageDraw.Draw(image)
    offset = TOP + WICK - low + (height - (TOP + BOTTOM + high - low + 2 * WICK)) // 2
    for y in range(20, height - 20, 40):
        draw.line((22, y, width - 22, y), fill=(31, 46, 66))
    for n, (candle, (start, finish)) in enumerate(zip(candles, coords)):
        x = LEFT + n * STEP + 4
        top = offset + min(start, finish)
        color = (25, 218, 145) if candle.up else (255, 83, 111)
        draw.line((x, top - WICK, x, top + candle.height + WICK - 1), fill=color)
        draw.rectangle((x - 2, top, x + 2, top + candle.height - 1), fill=color)
    image.thumbnail((650, 500), Image.Resampling.LANCZOS)
    return image
