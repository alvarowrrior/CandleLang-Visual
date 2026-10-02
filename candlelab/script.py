"""SCR1: bits Fibonacci CVL2 + velas reservadas para palabras de programación."""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

from .vector import Candle, CandleError, read_svg, save_svg

MAGIC = b"SCR1"
MAX_BYTES = 16_384
BASE = 8
SYNC_TEXT = "10+-1+0-+01-"
MACROS = {
    "variable": Candle(True, BASE * 3),
    "mientras": Candle(False, BASE * 3),
    "sea": Candle(True, BASE * 4),
    "verdadero": Candle(True, BASE * 5),
    "falso": Candle(False, BASE * 5),
    "entonces": Candle(False, BASE * 4),
    "mostrar": Candle(True, BASE * 6),
    "fin": Candle(False, BASE * 6),
    "si": Candle(True, BASE * 7),
    "valor": Candle(False, BASE * 7),
    "encontes": Candle(False, BASE * 8),
}
REVERSE = {v: (keyword, n) for n, (keyword, v) in enumerate(MACROS.items())}
INDEX = {keyword: n for n, keyword in enumerate(MACROS)}
KEYWORD = re.compile("|".join(re.escape(k) for k in sorted(MACROS, key=len, reverse=True)))
MAX_CANDLES = len(SYNC_TEXT) + (12 + MAX_BYTES) * 8


class State:
    def __init__(self):
        self.a, self.b, self.head = 13, 21, 0

    def parameters(self):
        return (self.a + self.head) % 3 == 0, (self.a + self.b + self.head) & 1

    def advance(self, value: int):
        self.a, self.b = self.b, (self.a + self.b + value) & 255
        self.head += 1


def _binary_symbol(bit: int, state: State) -> Candle:
    large, mask = state.parameters()
    candle = Candle(bool(bit ^ mask), BASE * (2 if large else 1))
    state.advance(bit)
    return candle


def _byte_candles(data: bytes, state: State) -> list[Candle]:
    return [_binary_symbol((byte >> shift) & 1, state)
            for byte in data for shift in range(7, -1, -1)]


def _sync():
    return [Candle(symbol in "1+", BASE * (2 if symbol in "+-" else 1))
            for symbol in SYNC_TEXT]


def _lex(source: str):
    """Palabras reservadas fuera de cadenas; todo lo demás queda intacto."""
    i, begin, quote, escaped = 0, 0, None, False
    while i < len(source):
        c = source[i]
        if quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            i += 1
            continue
        match = KEYWORD.match(source, i)
        if (match and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == "_"))
            and (match.end() == len(source) or not (source[match.end()].isalnum() or source[match.end()] == "_"))):
            if begin < i:
                yield None, source[begin:i]
            yield match.group(), None
            i = begin = match.end()
        else:
            i += 1
    if begin < len(source):
        yield None, source[begin:]


def encode(source: str) -> list[Candle]:
    payload = source.encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise CandleError(f"Máximo {MAX_BYTES} bytes UTF-8 por programa.")
    if not payload:
        return []
    frame = MAGIC + struct.pack(">II", len(payload), zlib.crc32(payload))
    state = State()
    result = _sync() + _byte_candles(frame, state)
    for keyword, raw in _lex(source):
        if keyword is None:
            result.extend(_byte_candles(raw.encode("utf-8"), state))
        else:
            result.append(MACROS[keyword])
            state.advance(INDEX[keyword] & 1)
    return result


def _read_bit(candle: Candle, state: State) -> int:
    large, mask = state.parameters()
    if candle.height != BASE * (2 if large else 1):
        raise CandleError(f"Desincronización Fibonacci en cabezal {state.head}.")
    plain = int(candle.up) ^ mask
    state.advance(plain)
    return plain


def decode(candles: list[Candle]) -> str:
    if not candles:
        return ""
    sync = _sync()
    if candles[:len(sync)] != sync or len(candles) < len(sync) + 96:
        raise CandleError("Sincronización SCR1 incorrecta.")
    state = State()
    header_bits = [_read_bit(c, state) for c in candles[len(sync):len(sync) + 96]]
    header = bytes(sum(header_bits[n + j] << (7 - j) for j in range(8))
                   for n in range(0, len(header_bits), 8))
    if header[:4] != MAGIC:
        raise CandleError("Firma SCR1 incorrecta.")
    length, crc = struct.unpack(">II", header[4:])
    if length > MAX_BYTES:
        raise CandleError("Longitud de código excesiva.")
    output = bytearray()
    current = count = 0
    for candle in candles[len(sync) + 96:]:
        if candle in REVERSE:
            if count:
                raise CandleError("Palabra reservada interrumpe un byte.")
            keyword, index = REVERSE[candle]
            output.extend(keyword.encode("utf-8"))
            state.advance(index & 1)
        else:
            bit = _read_bit(candle, state)
            current = (current << 1) | bit
            count += 1
            if count == 8:
                output.append(current)
                current = count = 0
        if len(output) > length:
            raise CandleError("Hay datos adicionales tras la longitud declarada.")
    if count or len(output) != length or zlib.crc32(output) != crc:
        raise CandleError("Programa alterado o incompleto; CRC incorrecto.")
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CandleError("El programa no es UTF-8 válido.") from exc


def save(source: str, path: str | Path):
    save_svg(encode(source), path, "SCR1")


def open_image(path: str | Path) -> str:
    return decode(read_svg(path, "SCR1", MAX_CANDLES))
