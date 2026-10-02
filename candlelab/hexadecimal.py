"""HEX1: comunicación UTF-8 con dígitos hexadecimales firmados en SVG."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .vector import Candle, CandleError, read_svg, save_svg

MAGIC = b"HEX1"
MAX_BYTES = 16_384
SYNC = [Candle(True, 1), Candle(False, 1), Candle(True, 2),
        Candle(False, 2), Candle(True, 4), Candle(False, 4)]
MAX_CANDLES = len(SYNC) + (12 + MAX_BYTES) * 2


class State:
    def __init__(self):
        self.a, self.b, self.head = 1, 1, 0

    def mask(self) -> int:
        return (self.a + self.b + self.head) & 15

    def advance(self, plain: int):
        self.a, self.b = self.b, (self.a + self.b + plain) & 15
        self.head += 1


def encode(text: str) -> list[Candle]:
    payload = text.encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise CandleError(f"El mensaje no puede exceder {MAX_BYTES} bytes UTF-8.")
    if not payload:
        return []
    frame = MAGIC + struct.pack(">II", len(payload), zlib.crc32(payload)) + payload
    state = State()
    result = SYNC.copy()
    for byte in frame:
        for plain in (byte >> 4, byte & 15):
            digit = (plain + state.mask()) & 15
            result.append(Candle(state.head % 2 == 0, 1 << digit))
            state.advance(plain)
    return result


def decode(candles: list[Candle]) -> str:
    if not candles:
        return ""
    if candles[:len(SYNC)] != SYNC or len(candles) < len(SYNC) + 24:
        raise CandleError("Sincronización HEX1 incorrecta.")
    content = candles[len(SYNC):]
    if len(content) % 2 or len(content) > (12 + MAX_BYTES) * 2:
        raise CandleError("Longitud hexadecimal inválida.")
    state = State()
    nibbles = []
    for candle in content:
        if candle.up != (state.head % 2 == 0):
            raise CandleError(f"Signo de la vela {state.head} incorrecto.")
        height = candle.height
        if height & (height - 1) or height > 1 << 15:
            raise CandleError(f"Altura de vela {state.head} incompatible con 0-F.")
        plain = ((height.bit_length() - 1) - state.mask()) & 15
        nibbles.append(plain)
        state.advance(plain)
    data = bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))
    if data[:4] != MAGIC:
        raise CandleError("Firma HEX1 incorrecta.")
    length, crc = struct.unpack(">II", data[4:12])
    payload = data[12:]
    if length > MAX_BYTES or len(payload) != length or zlib.crc32(payload) != crc:
        raise CandleError("Trama hexadecimal dañada o de longitud incorrecta.")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CandleError("Texto UTF-8 inválido.") from exc


def save(text: str, path: str | Path):
    save_svg(encode(text), path, "HEX1")


def open_image(path: str | Path) -> str:
    return decode(read_svg(path, "HEX1", MAX_CANDLES))
