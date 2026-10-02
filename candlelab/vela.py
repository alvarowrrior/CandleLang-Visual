"""VELA1: un lenguaje de programación en el que cada vela japonesa es una instrucción.

Una vela se reduce a su *firma*: color (V verde, R roja, D doji), cuerpo, mecha
superior y mecha inferior, todo medido en unidades enteras. Las mechas eligen la
familia, el color el grupo y el cuerpo la instrucción concreta.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from .vector import CandleError

MAX_SOURCE = 32_768
MAX_FRAME = 200_000


@dataclass(frozen=True)
class Sig:
    kind: str   # "V" alcista, "R" bajista, "D" doji
    body: int
    upper: int
    lower: int

    def __str__(self):
        return f"{self.kind}{self.body}·{self.upper}/{self.lower}"


# Familia: (nombre, patrón, color, mecha superior, mecha inferior, instrucciones por cuerpo 1..n)
FAMILIES = [
    ("aritmética", "Estrella fugaz", "V", 1, 0, ["+", "-", "*", "/", "%", "neg", "^", "abs"]),
    ("pila", "Estrella fugaz", "R", 1, 0, ["dup", "quita", "cambia", "copia", "rota", "profundidad"]),
    ("comparación", "Martillo", "V", 0, 1, ["==", "!=", "<", ">", "<=", ">="]),
    ("lógica", "Martillo", "R", 0, 1, ["y", "o", "no", "verdadero", "falso"]),
    ("memoria", "Peonza", "V", 1, 1, ["guarda", "lee"]),
    ("funciones", "Peonza", "R", 1, 1, ["llama"]),
    ("texto", "Estrella fugaz larga", "V", 2, 0,
     ["longitud", "caracter", "codigo", "une", "letra", "mayusculas", "minusculas"]),
    ("conversión", "Estrella fugaz larga", "R", 2, 0, ["numero", "texto"]),
    ("entrada/salida", "Martillo largo", "V", 0, 2, ["mostrar", "escribe", "entrada", "salto"]),
    ("sistema", "Martillo largo", "R", 0, 2, ["aleatorio", "indice"]),
]

# Doji (cuerpo cero): control de flujo. (mecha superior, mecha inferior, patrón)
DOJIS = {
    "nada": (0, 0, "Doji plano"),
    "si": (0, 2, "Doji libélula"),
    "sino": (2, 2, "Doji de piernas largas"),
    "fin": (2, 0, "Doji lápida"),
    "mientras": (1, 1, "Doji estrella"),
    "hacer": (1, 2, "Doji ancla"),
    "veces": (2, 1, "Doji farol"),
    "define": (3, 0, "Doji antena"),
    "retorna": (0, 3, "Doji raíz"),
    "alto": (3, 3, "Doji cruz"),
}

QUOTE_OPEN = Sig("V", 1, 2, 2)    # «  abre texto
QUOTE_CLOSE = Sig("R", 1, 2, 2)   # »  cierra texto
FRAME_START = Sig("V", 2, 3, 3)   # ⟦  inicio de trama
FRAME_END = Sig("R", 2, 3, 3)     # ⟧  fin de trama

OPCODES: dict[str, Sig] = {}
INFO: dict[str, tuple[str, str]] = {}   # mnemónico -> (familia, patrón)
for family, pattern, color, up, low, names in FAMILIES:
    for body, name in enumerate(names, 1):
        OPCODES[name] = Sig(color, body, up, low)
        INFO[name] = (family, pattern)
for name, (up, low, pattern) in DOJIS.items():
    OPCODES[name] = Sig("D", 0, up, low)
    INFO[name] = ("control", pattern)
MNEMONIC = {sig: name for name, sig in OPCODES.items()}

ALIASES = {"muestra": "mostrar", "imprime": "mostrar", "duplica": "dup", "intercambia": "cambia",
           "descarta": "quita", "repite": "veces", "funcion": "define", "función": "define"}
STATEMENT_END = {"guarda", "mostrar", "escribe", "salto", "quita", "retorna", "alto", "nada"}

TOKEN = re.compile(r'\s+|#[^\n]*|"(?:[^"\\\n]|\\.)*"|[^\s"#]+|"', re.S)
NAME = re.compile(r"[^\W\d]\w*")
EXPLICIT = re.compile(r"([vf])(\d+)")
ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def digit(value: int, first: bool) -> Sig:
    return Sig("V" if first else "R", value + 1, 0, 0)


def number_candles(digits: str) -> list[Sig]:
    return [digit(int(d), n == 0) for n, d in enumerate(digits)]


def string_candles(text: str) -> list[Sig]:
    result = [QUOTE_OPEN]
    for byte in text.encode("utf-8"):
        result += [Sig("V", (byte >> 4) + 1, 0, 0), Sig("R", (byte & 15) + 1, 0, 0)]
    return result + [QUOTE_CLOSE]


def _unescape(literal: str, line: int) -> str:
    out, i = [], 1
    while i < len(literal) - 1:
        c = literal[i]
        if c == "\\":
            nxt = literal[i + 1]
            if nxt not in ESCAPES:
                raise CandleError(f"Línea {line}: secuencia de escape desconocida \\{nxt}.")
            out.append(ESCAPES[nxt])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _tokens(source: str):
    line = 1
    for match in TOKEN.finditer(source):
        text = match.group()
        if text == '"':
            raise CandleError(f"Línea {line}: texto sin cerrar.")
        if not text.isspace() and not text.startswith("#"):
            yield text, line
        line += text.count("\n")


@dataclass
class Listing:
    """Cada palabra del código fuente con las velas que genera."""
    word: str
    line: int
    candles: list[Sig]


def compile_listing(source: str) -> list[Listing]:
    if len(source.encode("utf-8")) > MAX_SOURCE:
        raise CandleError(f"El programa supera {MAX_SOURCE} bytes.")
    tokens = list(_tokens(source))
    functions = {tokens[i + 1][0] for i, (t, _) in enumerate(tokens[:-1])
                 if ALIASES.get(t.lower(), t.lower()) == "define"}
    ids: dict[str, dict[str, int]] = {"v": {}, "f": {}}
    reserved = {"v": set(), "f": set()}
    for text, _ in tokens:
        explicit = EXPLICIT.fullmatch(text.lstrip("="))
        if explicit:
            reserved[explicit.group(1)].add(int(explicit.group(2)))

    def ident(space: str, name: str, line: int) -> list[Sig]:
        if not NAME.fullmatch(name):
            raise CandleError(f"Línea {line}: nombre inválido '{name}'.")
        if name.lower() in OPCODES or name.lower() in ALIASES:
            raise CandleError(f"Línea {line}: '{name}' es una palabra reservada.")
        explicit = EXPLICIT.fullmatch(name)
        if explicit and explicit.group(1) == space:
            number = int(explicit.group(2))
        else:
            table = ids[space]
            if name not in table:
                n = 0
                while n in reserved[space] or n in table.values():
                    n += 1
                table[name] = n
            number = table[name]
        return number_candles(str(number))

    result: list[Listing] = []
    pending_define = None
    for text, line in tokens:
        if pending_define is not None:
            result.append(Listing(f"define {text}", line, ident("f", text, line) + [OPCODES["define"]]))
            pending_define = None
            continue
        word = ALIASES.get(text.lower(), text.lower())
        if text.startswith('"'):
            result.append(Listing(text, line, string_candles(_unescape(text, line))))
        elif re.fullmatch(r"-?[0-9]+", text):
            candles = number_candles(text.lstrip("-"))
            if text.startswith("-"):
                candles.append(OPCODES["neg"])
            result.append(Listing(text, line, candles))
        elif word == "define":
            pending_define = line
        elif word in OPCODES:
            result.append(Listing(word, line, [OPCODES[word]]))
        elif text.startswith("=") and len(text) > 1:
            result.append(Listing(text, line, ident("v", text[1:], line) + [OPCODES["guarda"]]))
        elif text in functions or (EXPLICIT.fullmatch(text) and text[0] == "f"):
            result.append(Listing(text, line, ident("f", text, line) + [OPCODES["llama"]]))
        elif NAME.fullmatch(text):
            result.append(Listing(text, line, ident("v", text, line) + [OPCODES["lee"]]))
        else:
            raise CandleError(f"Línea {line}: palabra desconocida '{text}'.")
    if pending_define is not None:
        raise CandleError(f"Línea {pending_define}: falta el nombre tras 'define'.")
    return result


def compile_source(source: str) -> list[Sig]:
    return [c for entry in compile_listing(source) for c in entry.candles]


# ----------------------------------------------------------------- lectura de velas

@dataclass
class Instr:
    op: str          # "num", "txt" o un mnemónico
    arg: object      # dígitos (str) o texto
    index: int       # posición de la primera vela


def decode(candles: list[Sig]) -> list[Instr]:
    """Agrupa las velas en instrucciones: números, textos y mnemónicos."""
    result: list[Instr] = []
    i = 0
    while i < len(candles):
        c = candles[i]
        if c.upper == c.lower == 0 and c.kind != "D":
            if not 1 <= c.body <= 10:
                raise CandleError(f"Vela {i}: Marubozu de cuerpo {c.body} fuera de un texto (máx. 10).")
            if c.kind == "V":
                result.append(Instr("num", str(c.body - 1), i))
            elif result and result[-1].op == "num" and result[-1].index + len(result[-1].arg) == i:
                result[-1].arg += str(c.body - 1)
            else:
                raise CandleError(f"Vela {i}: dígito rojo sin número verde que lo inicie.")
            i += 1
        elif c == QUOTE_OPEN:
            start, i, data = i, i + 1, bytearray()
            while i < len(candles) and candles[i] != QUOTE_CLOSE:
                pair = candles[i:i + 2]
                if (len(pair) < 2 or any(p.upper or p.lower or not 1 <= p.body <= 16 for p in pair)
                        or (pair[0].kind, pair[1].kind) != ("V", "R")):
                    raise CandleError(f"Vela {i}: texto mal formado (se esperan parejas verde/roja).")
                data.append(((pair[0].body - 1) << 4) | (pair[1].body - 1))
                i += 2
            if i >= len(candles):
                raise CandleError(f"Vela {start}: texto sin vela de cierre.")
            try:
                result.append(Instr("txt", data.decode("utf-8"), start))
            except UnicodeDecodeError as exc:
                raise CandleError(f"Vela {start}: texto UTF-8 inválido.") from exc
            i += 1
        elif c in MNEMONIC:
            result.append(Instr(MNEMONIC[c], None, i))
            i += 1
        else:
            raise CandleError(f"Vela {i}: firma {c} sin instrucción asignada.")
    return result


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def disassemble(instrs: list[Instr]) -> str:
    """Devuelve código VELA legible. Los nombres viajan como números: v0, v1, f0…"""
    lines: list[str] = []
    current: list[str] = []
    depth = 0

    def flush():
        nonlocal current
        if current:
            lines.append("    " * depth + " ".join(current))
            current = []

    i = 0
    while i < len(instrs):
        ins = instrs[i]
        nxt = instrs[i + 1].op if i + 1 < len(instrs) else None
        if ins.op == "num" and nxt in ("guarda", "lee", "llama", "define"):
            n = int(ins.arg)
            word = {"guarda": f"=v{n}", "lee": f"v{n}", "llama": f"f{n}", "define": f"define f{n}"}[nxt]
            i += 2
            if nxt == "define":
                flush()
                lines.append("    " * depth + word)
                depth += 1
                continue
            current.append(word)
            if nxt == "guarda":
                flush()
            continue
        i += 1
        if ins.op == "num":
            current.append(ins.arg)
        elif ins.op == "txt":
            current.append(_quote(ins.arg))
        elif ins.op == "mientras":
            flush()
            current.append("mientras")
        elif ins.op in ("si", "hacer", "veces"):
            current.append(ins.op)
            flush()
            depth += 1
        elif ins.op == "sino":
            flush()
            lines.append("    " * max(depth - 1, 0) + "sino")
        elif ins.op == "fin":
            flush()
            depth = max(depth - 1, 0)
            lines.append("    " * depth + "fin")
        else:
            current.append(ins.op)
            if ins.op in STATEMENT_END:
                flush()
    flush()
    return "\n".join(lines) + ("\n" if lines else "")


# ----------------------------------------------------------------- tramas

def checksum(candles: list[Sig]) -> int:
    codes = {"V": 0, "R": 1, "D": 2}
    data = bytes(v for c in candles for v in (codes[c.kind], c.body, c.upper, c.lower))
    return zlib.crc32(data) & 0xFFFF


def frame(candles: list[Sig]) -> list[Sig]:
    """⟦ programa ⟧ + 4 velas de CRC-16 (nibbles alternando verde/roja)."""
    crc = checksum(candles)
    tail = [Sig("V" if n % 2 == 0 else "R", ((crc >> (12 - 4 * n)) & 15) + 1, 0, 0) for n in range(4)]
    return [FRAME_START] + candles + [FRAME_END] + tail


def unframe(candles: list[Sig]) -> list[Sig]:
    if FRAME_START not in candles:
        raise CandleError("No aparece la vela de inicio de trama ⟦.")
    start = candles.index(FRAME_START) + 1
    try:
        end = candles.index(FRAME_END, start)
    except ValueError as exc:
        raise CandleError("Falta la vela de fin de trama ⟧.") from exc
    body, tail = candles[start:end], candles[end + 1:end + 5]
    if len(tail) != 4 or any(t.upper or t.lower or not 1 <= t.body <= 16 for t in tail):
        raise CandleError("Faltan las 4 velas de control tras ⟧.")
    crc = 0
    for t in tail:
        crc = (crc << 4) | (t.body - 1)
    if crc != checksum(body):
        raise CandleError("Control CRC incorrecto: el gráfico está alterado o incompleto.")
    return body


def compile_frame(source: str) -> list[Sig]:
    return frame(compile_source(source))


def message_program(text: str) -> str:
    """Programa mínimo que muestra un mensaje de texto."""
    return _quote(text) + " mostrar\n"


class Receiver:
    """Lee un flujo de velas (firmas) y devuelve cada trama completa y verificada."""

    def __init__(self):
        self.buffer: list[Sig] | None = None
        self.tail = 0

    def push(self, candle: Sig):
        """Devuelve (velas, error) cuando se cierra una trama, o None."""
        if candle == FRAME_START:
            self.buffer, self.tail = [candle], 0
            return None
        if self.buffer is None:
            return None
        self.buffer.append(candle)
        if self.tail:
            self.tail -= 1
            if self.tail == 0:
                received, self.buffer = self.buffer, None
                try:
                    return unframe(received), None
                except CandleError as exc:
                    return None, str(exc)
        elif candle == FRAME_END:
            self.tail = 4
        elif len(self.buffer) > MAX_FRAME:
            self.buffer = None
        return None
