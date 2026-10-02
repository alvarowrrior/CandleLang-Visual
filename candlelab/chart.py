"""Gráficos VELA: OHLC, SVG, PNG, CSV y Pine Script, con sus lectores.

Los lectores solo miran la geometría de las velas (cuerpo, mechas, color y
continuidad apertura = cierre anterior); ninguna imagen guarda el código como texto.
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .vela import FRAME_END, FRAME_START, MNEMONIC, QUOTE_CLOSE, QUOTE_OPEN, Sig
from .vector import CandleError

NS = "http://www.w3.org/2000/svg"
PROTOCOL = "VELA1"
UNIT, STEP, BODY, LEFT, TOP, BOTTOM = 6, 14, 9, 40, 36, 36
LABEL_SPACE = 70
COLORS = {"V": (25, 218, 145), "R": (255, 83, 111), "D": (214, 222, 235)}
BACKGROUND, GRID, MUTED = (11, 19, 32), (24, 36, 54), (96, 116, 146)
BASE_PRICE, TICK = 1000.0, 0.25


def hexcolor(rgb) -> str:
    return "#%02x%02x%02x" % rgb


# ----------------------------------------------------------------- geometría

def ohlc(candles: list[Sig], start: int = 0) -> list[tuple[int, int, int, int]]:
    """Precios en unidades enteras; cada vela abre donde cerró la anterior."""
    result, price = [], start
    for c in candles:
        close = price + c.body if c.kind == "V" else price - c.body if c.kind == "R" else price
        result.append((price, max(price, close) + c.upper, min(price, close) - c.lower, close))
        price = close
    return result


def signature(o: int, h: int, l: int, c: int) -> Sig:
    if h < max(o, c) or l > min(o, c):
        raise CandleError(f"OHLC imposible: {o}, {h}, {l}, {c}.")
    kind = "V" if c > o else "R" if c < o else "D"
    return Sig(kind, abs(c - o), h - max(o, c), min(o, c) - l)


def candle_labels(candles: list[Sig]) -> list[str]:
    """Nombre legible de cada vela según su contexto (número, texto, trama o instrucción)."""
    result, in_text, crc = [], False, 0
    for c in candles:
        if crc:
            result.append(f"crc {c.body - 1:X}")
            crc -= 1
        elif c == FRAME_START:
            result.append("inicio")
        elif c == FRAME_END:
            result.append("final")
            crc = 4
        elif c == QUOTE_OPEN:
            result.append("«")
            in_text = True
        elif c == QUOTE_CLOSE:
            result.append("»")
            in_text = False
        elif in_text:
            result.append(f"{c.body - 1:X}")
        elif not (c.upper or c.lower or c.kind == "D"):
            result.append(str(c.body - 1))
        else:
            result.append(MNEMONIC.get(c, str(c)))
    return result


def _layout(candles: list[Sig], labels: bool):
    bars = ohlc(candles)
    high = max((b[1] for b in bars), default=1)
    low = min((b[2] for b in bars), default=0)
    width = LEFT * 2 + max(len(candles), 1) * STEP
    height = TOP + BOTTOM + (high - low) * UNIT + (LABEL_SPACE if labels else 0)

    def y(price: int) -> int:
        return TOP + (high - price) * UNIT
    return bars, width, height, y


# ----------------------------------------------------------------- SVG

def svg(candles: list[Sig], labels: bool = False) -> str:
    bars, width, height, y = _layout(candles, labels)
    out = [f'<svg xmlns="{NS}" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'data-protocol="{PROTOCOL}">',
           f'<rect x="0" y="0" width="{width}" height="{height}" fill="{hexcolor(BACKGROUND)}"/>',
           '<g id="rejilla">']
    for gy in range(TOP, height - BOTTOM, 48):
        out.append(f'<line x1="{LEFT - 12}" x2="{width - LEFT + 12}" y1="{gy}" y2="{gy}" '
                   f'stroke="{hexcolor(GRID)}"/>')
    out.append('</g><g id="velas">')
    for n, (c, (o, h, l, cl)) in enumerate(zip(candles, bars)):
        x = LEFT + n * STEP + STEP // 2
        color = hexcolor(COLORS[c.kind])
        out.append(f'<line x1="{x}" x2="{x}" y1="{y(h)}" y2="{y(l)}" stroke="{color}" stroke-width="1.5"/>')
        if c.kind == "D":
            out.append(f'<rect x="{x - BODY // 2}" y="{y(o) - 1}" width="{BODY}" height="2" fill="{color}"/>')
        else:
            out.append(f'<rect x="{x - BODY // 2}" y="{y(max(o, cl))}" width="{BODY}" '
                       f'height="{c.body * UNIT}" fill="{color}" rx="1"/>')
    out.append('</g>')
    if labels:
        out.append(f'<g id="etiquetas" font-family="Consolas, monospace" font-size="10" '
                   f'fill="{hexcolor(MUTED)}">')
        base = height - LABEL_SPACE + 8
        for n, text in enumerate(candle_labels(candles)):
            x = LEFT + n * STEP + STEP // 2
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            out.append(f'<text transform="translate({x + 3},{base}) rotate(90)">{text}</text>')
        out.append('</g>')
    out.append(f'<text x="{LEFT - 12}" y="22" font-family="Consolas, monospace" font-size="12" '
               f'fill="{hexcolor(MUTED)}">VELA1 · {len(candles)} velas</text></svg>')
    return "\n".join(out)


def save_svg(candles: list[Sig], path, labels: bool = False):
    Path(path).write_text(svg(candles, labels), encoding="utf-8")


def read_svg(path) -> list[Sig]:
    path = Path(path)
    if path.stat().st_size > 40_000_000:
        raise CandleError("SVG demasiado grande.")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise CandleError(f"SVG ilegible: {exc}") from exc
    if root.tag != f"{{{NS}}}svg" or root.get("data-protocol") != PROTOCOL:
        raise CandleError("El SVG no es un gráfico VELA1.")
    group = next((g for g in root if g.tag == f"{{{NS}}}g" and g.get("id") == "velas"), None)
    if group is None or len(group) % 2:
        raise CandleError("No se encontró la cinta de velas.")
    palette = {hexcolor(v): k for k, v in COLORS.items()}
    rows = []
    try:
        for wick, body in zip(group[::2], group[1::2]):
            kind = palette.get(body.get("fill"))
            if kind is None or wick.get("stroke") != body.get("fill"):
                raise CandleError(f"Vela {len(rows)}: color desconocido.")
            top, size = float(body.get("y")), float(body.get("height"))
            open_, close = ((top + 1, top + 1) if kind == "D" else
                            (top + size, top) if kind == "V" else (top, top + size))
            rows.append((kind, open_, float(wick.get("y1")), float(wick.get("y2")), close))
    except (TypeError, ValueError) as exc:
        raise CandleError(f"Geometría SVG inválida: {exc}") from exc
    return _from_rows(rows, UNIT)


def _from_rows(rows, unit: float, tolerance: float = 0.34) -> list[Sig]:
    """Convierte coordenadas de pantalla (y crece hacia abajo) en firmas."""
    if not rows:
        return []
    origin = rows[0][1]

    def units(y: float, n: int) -> int:
        value = (origin - y) / unit
        if abs(value - round(value)) > tolerance:
            raise CandleError(f"Vela {n}: medida que no es múltiplo de la unidad ({value:.2f}).")
        return round(value)

    result, previous = [], None
    for n, (kind, o, h, l, c) in enumerate(rows):
        o, h, l, c = units(o, n), units(h, n), units(l, n), units(c, n)
        if previous is not None and o != previous:
            raise CandleError(f"Vela {n}: no abre en el cierre de la anterior.")
        sig = signature(o, h, l, c)
        if sig.kind != kind:
            raise CandleError(f"Vela {n}: el color no coincide con la dirección.")
        result.append(sig)
        previous = c
    return result


# ----------------------------------------------------------------- PNG

def _font(size: int):
    for name in ("consola.ttf", "DejaVuSansMono.ttf", "seguisym.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(candles: list[Sig], labels: bool = False, highlight: int | None = None) -> Image.Image:
    bars, width, height, y = _layout(candles, labels)
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for gy in range(TOP, height - BOTTOM - (LABEL_SPACE if labels else 0), 48):
        draw.line((LEFT - 12, gy, width - LEFT + 12, gy), fill=GRID)
    font, names = _font(11), candle_labels(candles)
    draw.text((LEFT - 12, 12), f"VELA1 · {len(candles)} velas", fill=MUTED, font=font)
    for n, (c, (o, h, l, cl)) in enumerate(zip(candles, bars)):
        x = LEFT + n * STEP + STEP // 2
        color = COLORS[c.kind]
        if highlight == n:
            draw.rectangle((x - STEP // 2, TOP - 8, x + STEP // 2 - 1, height - BOTTOM), fill=(30, 46, 70))
        draw.line((x, y(h), x, y(l) - 1), fill=color)
        if c.kind == "D":
            draw.rectangle((x - BODY // 2, y(o) - 1, x + BODY // 2, y(o)), fill=color)
        else:
            draw.rectangle((x - BODY // 2, y(max(o, cl)), x + BODY // 2, y(min(o, cl)) - 1), fill=color)
        if labels:
            text = names[n]
            tile = Image.new("RGBA", (LABEL_SPACE, 14), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((0, 0), text, fill=MUTED, font=font)
            tile = tile.rotate(-90, expand=True)
            image.paste(tile, (x - 6, height - LABEL_SPACE - BOTTOM // 2), tile)
    return image


def save_png(candles: list[Sig], path, labels: bool = False):
    render(candles, labels).save(path, optimize=True)


def read_png(path, unit: int = UNIT) -> list[Sig]:
    """Lee un PNG a escala 1:1 (también un recorte) buscando columnas de color."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    if width * height > 80_000_000:
        raise CandleError("Imagen demasiado grande.")
    pixels = image.load()
    cache: dict = {}

    def kind(rgb):
        if rgb not in cache:
            cache[rgb] = next((k for k, ref in COLORS.items()
                               if sum(abs(a - b) for a, b in zip(rgb, ref)) < 60), None)
        return cache[rgb]

    columns = [[kind(pixels[x, yy]) for yy in range(height)] for x in range(width)]
    marked = [any(col) for col in columns]
    rows, x = [], 0
    while x < width:
        if not marked[x]:
            x += 1
            continue
        start = x
        while x < width and marked[x]:
            x += 1
        if x - start < 3:
            continue
        center = columns[(start + x - 1) // 2]
        edge = columns[start]
        wick = [yy for yy, k in enumerate(center) if k]
        body = [yy for yy, k in enumerate(edge) if k]
        if not body or not wick:
            continue
        k = max(COLORS, key=lambda name: sum(1 for v in edge if v == name))
        top, bottom = body[0], body[-1] + 1
        if k == "D":
            open_ = close = top + 1
        else:
            open_, close = (bottom, top) if k == "V" else (top, bottom)
        rows.append((k, open_, min(wick[0], top), max(wick[-1] + 1, bottom), close))
    if not rows:
        raise CandleError("No se encontraron velas VELA en la imagen.")
    return _from_rows(rows, unit)


# ----------------------------------------------------------------- CSV (datos de mercado)

def save_csv(candles: list[Sig], path, base: float = BASE_PRICE, tick: float = TICK,
             start: datetime | None = None):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "open", "high", "low", "close"])
        for n, bar in enumerate(ohlc(candles)):
            stamp = (start + timedelta(minutes=n)).strftime("%Y-%m-%dT%H:%M:%SZ")
            writer.writerow([stamp] + [f"{base + v * tick:.4f}" for v in bar])


HEADERS = {"open": ("open", "apertura", "o"), "high": ("high", "maximo", "máximo", "max", "h"),
           "low": ("low", "minimo", "mínimo", "min", "l"), "close": ("close", "cierre", "c")}


def read_csv(path, tick: float | None = None) -> list[Sig]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        table = list(csv.reader(handle))
    if not table:
        raise CandleError("CSV vacío.")
    header = [h.strip().lower() for h in table[0]]
    try:
        cols = [next(header.index(name) for name in HEADERS[key] if name in header) for key in HEADERS]
    except StopIteration as exc:
        raise CandleError("El CSV necesita columnas open, high, low y close.") from exc
    try:
        prices = [[float(row[i]) for i in cols] for row in table[1:] if row]
    except (ValueError, IndexError) as exc:
        raise CandleError(f"Precio inválido en el CSV: {exc}") from exc
    return from_prices(prices, tick)


def from_prices(prices: list[list[float]], tick: float | None = None) -> list[Sig]:
    """OHLC reales (float) -> firmas. Sin tick, se deduce del menor tramo distinto de cero."""
    if not prices:
        return []
    if tick is None:
        steps = [abs(d) for o, h, l, c in prices for d in (c - o, h - max(o, c), min(o, c) - l)]
        steps = [s for s in steps if s > 1e-9]
        if not steps:
            raise CandleError("No hay movimiento de precios para deducir el tick.")
        tick = min(steps)
    base = prices[0][0]
    rows = [("V" if c > o + tick / 2 else "R" if c < o - tick / 2 else "D",
             -(o - base) / tick, -(h - base) / tick, -(l - base) / tick, -(c - base) / tick)
            for o, h, l, c in prices]
    return _from_rows(rows, 1.0, tolerance=0.2)


# ----------------------------------------------------------------- Pine Script (TradingView)

def pine(candles: list[Sig], title: str = "VELA · mensaje") -> str:
    bars = ohlc(candles)
    series = {name: ",".join(str(bar[i]) for bar in bars) for i, name in enumerate("ohlc")}
    title = title.replace('"', "'")
    return f'''//@version=5
// Generado por CandleLab · VELA1. Dibuja {len(bars)} velas-instrucción en las últimas barras del gráfico.
// Cada vela es una instrucción: el receptor lee cuerpo, mechas y color.
indicator("{title}", overlay=false, max_bars_back=5000)
unidad = input.float(1.0, "Tamaño de la unidad")
var float[] O = array.new_float()
var float[] H = array.new_float()
var float[] L = array.new_float()
var float[] C = array.new_float()
cargar(float[] destino, string datos) =>
    for parte in str.split(datos, ",")
        array.push(destino, str.tonumber(parte))
if barstate.isfirst
    cargar(O, "{series["o"]}")
    cargar(H, "{series["h"]}")
    cargar(L, "{series["l"]}")
    cargar(C, "{series["c"]}")
n = array.size(O)
i = bar_index - (last_bar_index - n + 1)
dentro = i >= 0 and i < n
j = math.max(0, math.min(n - 1, i))
o = dentro ? array.get(O, j) * unidad : na
h = dentro ? array.get(H, j) * unidad : na
l = dentro ? array.get(L, j) * unidad : na
c = dentro ? array.get(C, j) * unidad : na
tono = c > o ? color.rgb(25, 218, 145) : c < o ? color.rgb(255, 83, 111) : color.rgb(214, 222, 235)
plotcandle(o, h, l, c, "VELA", tono, tono, bordercolor=tono)
'''


# ----------------------------------------------------------------- entrada genérica

def read_any(path) -> list[Sig]:
    suffix = Path(path).suffix.lower()
    if suffix == ".svg":
        return read_svg(path)
    if suffix == ".csv":
        return read_csv(path)
    if suffix in (".png", ".bmp", ".gif", ".webp"):
        return read_png(path)
    raise CandleError("Formato no admitido: use .svg, .png o .csv.")
