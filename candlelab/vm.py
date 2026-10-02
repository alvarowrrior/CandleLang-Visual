"""Máquina de pila que ejecuta directamente las instrucciones leídas de las velas.

No usa eval/exec ni accede a ficheros, red o procesos: un programa VELA solo puede
calcular, leer las líneas de entrada que se le den y escribir texto.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .vela import Instr, Sig, decode
from .vector import CandleError

MAX_STEPS = 200_000
MAX_STACK = 10_000
MAX_OUTPUT = 50_000
MAX_CALLS = 1_000
MAX_TEXT = 100_000
MAX_BITS = 100_000


@dataclass
class Result:
    output: str
    stack: list
    steps: int
    halted: bool = False


@dataclass
class Blocks:
    end: dict[int, int] = field(default_factory=dict)      # apertura -> fin
    opener: dict[int, int] = field(default_factory=dict)   # fin -> apertura
    otherwise: dict[int, int] = field(default_factory=dict)  # si -> sino
    do: dict[int, int] = field(default_factory=dict)       # mientras -> hacer
    owner: dict[int, int] = field(default_factory=dict)    # sino/hacer -> apertura


def match_blocks(code: list[Instr]) -> Blocks:
    blocks, stack = Blocks(), []
    for i, ins in enumerate(code):
        where = f"Vela {ins.index} ({ins.op})"
        if ins.op in ("si", "mientras", "veces", "define"):
            stack.append(i)
        elif ins.op == "sino":
            if not stack or code[stack[-1]].op != "si" or stack[-1] in blocks.otherwise:
                raise CandleError(f"{where}: 'sino' sin 'si' abierto.")
            blocks.otherwise[stack[-1]] = i
            blocks.owner[i] = stack[-1]
        elif ins.op == "hacer":
            if not stack or code[stack[-1]].op != "mientras" or stack[-1] in blocks.do:
                raise CandleError(f"{where}: 'hacer' sin 'mientras' abierto.")
            blocks.do[stack[-1]] = i
            blocks.owner[i] = stack[-1]
        elif ins.op == "fin":
            if not stack:
                raise CandleError(f"{where}: 'fin' sin bloque abierto.")
            start = stack.pop()
            if code[start].op == "mientras" and start not in blocks.do:
                raise CandleError(f"Vela {code[start].index}: 'mientras' necesita 'hacer'.")
            blocks.end[start], blocks.opener[i] = i, start
    if stack:
        ins = code[stack[-1]]
        raise CandleError(f"Vela {ins.index}: falta 'fin' para '{ins.op}'.")
    return blocks


def show(value) -> str:
    if value is True:
        return "verdadero"
    if value is False:
        return "falso"
    return str(value)


def _int(value, op):
    if isinstance(value, bool) or not isinstance(value, int):
        raise CandleError(f"'{op}' necesita números, recibió {show(value)!r}.")
    return value


def _text(value, op):
    if not isinstance(value, str):
        raise CandleError(f"'{op}' necesita texto, recibió {show(value)!r}.")
    return value


def _checked(value):
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > MAX_BITS:
        raise CandleError("Número demasiado grande.")
    if isinstance(value, str) and len(value) > MAX_TEXT:
        raise CandleError("Texto demasiado largo.")
    return value


def _add(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return show(a) + show(b)
    return _int(a, "+") + _int(b, "+")


def _mul(a, b):
    if isinstance(a, str):
        n = _int(b, "*")
        if len(a) * max(n, 0) > MAX_TEXT:
            raise CandleError("Texto demasiado largo.")
        return a * n
    return _int(a, "*") * _int(b, "*")


def _div(a, b, op):
    a, b = _int(a, op), _int(b, op)
    if b == 0:
        raise CandleError("División entre cero.")
    return a // b if op == "/" else a % b


def _pow(a, b):
    a, b = _int(a, "^"), _int(b, "^")
    if not 0 <= b <= 4096:
        raise CandleError("El exponente debe estar entre 0 y 4096.")
    return a ** b


def _compare(a, b, op):
    if op in ("==", "!="):
        return (a == b and type(a) is type(b)) == (op == "==")
    if not (isinstance(a, str) and isinstance(b, str)):
        a, b = _int(a, op), _int(b, op)
    return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _letter(text, i):
    text, i = _text(text, "letra"), _int(i, "letra")
    if not -len(text) <= i < len(text):
        raise CandleError(f"'letra' fuera de rango: {i}.")
    return text[i]


def _char(n):
    n = _int(n, "caracter")
    if not 0 <= n <= 0x10FFFF:
        raise CandleError("Código de carácter fuera de rango.")
    return chr(n)


def _code(text):
    text = _text(text, "codigo")
    if not text:
        raise CandleError("'codigo' necesita al menos un carácter.")
    return ord(text[0])


def _number(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = _text(value, "numero").strip()
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        raise CandleError(f"'{value}' no es un número entero.")
    return int(text)


BINARY = {
    "+": _add, "-": lambda a, b: _int(a, "-") - _int(b, "-"), "*": _mul,
    "/": lambda a, b: _div(a, b, "/"), "%": lambda a, b: _div(a, b, "%"), "^": _pow,
    "==": lambda a, b: _compare(a, b, "=="), "!=": lambda a, b: _compare(a, b, "!="),
    "<": lambda a, b: _compare(a, b, "<"), ">": lambda a, b: _compare(a, b, ">"),
    "<=": lambda a, b: _compare(a, b, "<="), ">=": lambda a, b: _compare(a, b, ">="),
    "y": lambda a, b: bool(a) and bool(b), "o": lambda a, b: bool(a) or bool(b),
    "une": lambda a, b: show(a) + show(b), "letra": _letter,
}
UNARY = {
    "neg": lambda a: -_int(a, "neg"), "abs": lambda a: abs(_int(a, "abs")), "no": lambda a: not a,
    "longitud": lambda a: len(_text(a, "longitud")), "caracter": _char, "codigo": _code,
    "mayusculas": lambda a: _text(a, "mayusculas").upper(),
    "minusculas": lambda a: _text(a, "minusculas").lower(),
    "numero": _number, "texto": show,
}


def run(code: list[Instr] | list[Sig], inputs: list[str] | tuple = (), seed=None,
        max_steps: int = MAX_STEPS) -> Result:
    if code and isinstance(code[0], Sig):
        code = decode(code)
    blocks = match_blocks(code)
    rng = random.Random(seed)
    lines = list(inputs)
    stack: list = []
    variables: dict[int, object] = {}
    functions: dict[int, int] = {}
    calls: list[tuple[int, int]] = []     # (retorno, profundidad de bucles)
    loops: list[list[int]] = []           # [índice, total, apertura]
    output: list[str] = []
    size = steps = pc = 0

    def pop():
        if not stack:
            raise CandleError("La pila está vacía.")
        return stack.pop()

    def push(value):
        if len(stack) >= MAX_STACK:
            raise CandleError("Desbordamiento de pila.")
        stack.append(_checked(value))

    def write(text):
        nonlocal size
        size += len(text)
        if size > MAX_OUTPUT:
            raise CandleError("La salida supera 50 000 caracteres.")
        output.append(text)

    def leave():
        ret, depth = calls.pop()
        del loops[depth:]
        return ret

    while pc < len(code):
        ins = code[pc]
        steps += 1
        if steps > max_steps:
            raise CandleError(f"Límite de {max_steps} pasos alcanzado; ¿bucle infinito?")
        op, nxt = ins.op, pc + 1
        try:
            if op == "num":
                push(int(ins.arg))
            elif op == "txt":
                push(ins.arg)
            elif op in BINARY:
                b = pop()
                push(BINARY[op](pop(), b))
            elif op in UNARY:
                push(UNARY[op](pop()))
            elif op == "dup":
                v = pop(); push(v); push(v)
            elif op == "quita":
                pop()
            elif op == "cambia":
                b, a = pop(), pop(); push(b); push(a)
            elif op == "copia":
                b, a = pop(), pop(); push(a); push(b); push(a)
            elif op == "rota":
                c, b, a = pop(), pop(), pop(); push(b); push(c); push(a)
            elif op == "profundidad":
                push(len(stack))
            elif op in ("verdadero", "falso"):
                push(op == "verdadero")
            elif op == "guarda":
                key = _int(pop(), "guarda")
                variables[key] = pop()
            elif op == "lee":
                key = _int(pop(), "lee")
                if key not in variables:
                    raise CandleError(f"La variable v{key} no tiene valor.")
                push(variables[key])
            elif op == "mostrar":
                write(show(pop()) + "\n")
            elif op == "escribe":
                write(show(pop()))
            elif op == "salto":
                write("\n")
            elif op == "entrada":
                push(lines.pop(0) if lines else "")
            elif op == "aleatorio":
                n = _int(pop(), "aleatorio")
                if n < 1:
                    raise CandleError("'aleatorio' necesita un número mayor que 0.")
                push(rng.randrange(n))
            elif op == "indice":
                if len(loops) <= (calls[-1][1] if calls else 0):
                    raise CandleError("'indice' solo funciona dentro de 'veces'.")
                push(loops[-1][0])
            elif op == "si":
                if not pop():
                    nxt = blocks.otherwise.get(pc, blocks.end[pc]) + 1
            elif op == "sino":
                nxt = blocks.end[blocks.owner[pc]] + 1
            elif op == "hacer":
                if not pop():
                    nxt = blocks.end[blocks.owner[pc]] + 1
            elif op == "veces":
                n = _int(pop(), "veces")
                if n > 0:
                    loops.append([0, n, pc])
                else:
                    nxt = blocks.end[pc] + 1
            elif op == "define":
                functions[_int(pop(), "define")] = pc + 1
                nxt = blocks.end[pc] + 1
            elif op == "llama":
                key = _int(pop(), "llama")
                if key not in functions:
                    raise CandleError(f"La función f{key} no está definida.")
                if len(calls) >= MAX_CALLS:
                    raise CandleError("Demasiadas llamadas anidadas.")
                calls.append((pc + 1, len(loops)))
                nxt = functions[key]
            elif op == "retorna":
                if not calls:
                    return Result("".join(output), stack, steps, True)
                nxt = leave()
            elif op == "fin":
                start = blocks.opener[pc]
                kind = code[start].op
                if kind == "mientras":
                    nxt = start + 1
                elif kind == "veces":
                    loop = loops[-1]
                    loop[0] += 1
                    if loop[0] < loop[1]:
                        nxt = start + 1
                    else:
                        loops.pop()
                elif kind == "define" and calls:
                    nxt = leave()
            elif op == "alto":
                return Result("".join(output), stack, steps, True)
            # "nada" y "mientras" no hacen nada por sí mismas
        except CandleError as exc:
            raise CandleError(f"Vela {ins.index} ({_label(ins)}): {exc}") from None
        except (ArithmeticError, ValueError, MemoryError) as exc:
            raise CandleError(f"Vela {ins.index} ({_label(ins)}): {exc}") from None
        pc = nxt
    return Result("".join(output), stack, steps)


def _label(ins: Instr) -> str:
    return {"num": "número", "txt": "texto"}.get(ins.op, ins.op)
