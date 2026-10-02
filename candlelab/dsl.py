"""Intérprete pequeño de CandleScript. Las expresiones se evalúan sin eval/exec."""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field

from .vector import CandleError

ASSIGN = re.compile(r"^variable\((.+)\)(?:\s*=\s*(.+))?$")
PRINT = re.compile(r"^mostrar\((.*)\)$")
BLOCK = re.compile(r"^(mientras|si)\s+(.+?)\s+(?:entonces|encontes)$")
EQUALITY = re.compile(r"^(.+?)\s+sea\s+(.+)$")
BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod,
}
COMPARISONS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


@dataclass
class Statement:
    kind: str
    line: int
    first: str = ""
    second: str = ""
    body: list[Statement] = field(default_factory=list)


def parse(source: str) -> list[Statement]:
    root: list[Statement] = []
    stack = [root]
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "fin":
            if len(stack) == 1:
                raise CandleError(f"Línea {number}: 'fin' sin bloque abierto.")
            stack.pop()
            continue
        match = ASSIGN.fullmatch(line)
        if match:
            stack[-1].append(Statement("variable", number, match.group(1), match.group(2) or "falso"))
            continue
        match = PRINT.fullmatch(line)
        if match:
            stack[-1].append(Statement("mostrar", number, match.group(1)))
            continue
        match = BLOCK.fullmatch(line)
        if match:
            entry = Statement(match.group(1), number, match.group(2))
            stack[-1].append(entry)
            stack.append(entry.body)
            continue
        raise CandleError(f"Línea {number}: instrucción desconocida: {line}")
    if len(stack) != 1:
        raise CandleError("Falta 'fin' para cerrar un bloque.")
    return root


def _value(node: ast.AST, env: dict):
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in ("verdadero", "falso"):
            return node.id == "verdadero"
        if node.id not in env:
            raise CandleError(f"Variable desconocida: {node.id}")
        return env[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "valor" and len(node.args) == 1 and not node.keywords):
        key = _value(node.args[0], env)
        if not isinstance(key, str) or key not in env:
            raise CandleError(f"Variable desconocida: {key}")
        return env[key]
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        return BINARY[type(node.op)](_value(node.left, env), _value(node.right, env))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_value(node.operand, env)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _value(node.operand, env)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return all(bool(_value(term, env)) for term in node.values)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return any(bool(_value(term, env)) for term in node.values)
    if isinstance(node, ast.Compare):
        left = _value(node.left, env)
        for op, part in zip(node.ops, node.comparators):
            if type(op) not in COMPARISONS:
                raise CandleError("Comparación no permitida.")
            right = _value(part, env)
            if not COMPARISONS[type(op)](left, right):
                return False
            left = right
        return True
    raise CandleError("Expresión no permitida. Use números, texto, variables y operaciones sencillas.")


def evaluate(expr: str, env: dict):
    match = EQUALITY.fullmatch(expr)
    if match:
        return evaluate(match.group(1), env) == evaluate(match.group(2), env)
    try:
        return _value(ast.parse(expr, mode="eval").body, env)
    except (SyntaxError, TypeError, ZeroDivisionError, OverflowError) as exc:
        raise CandleError(f"Expresión inválida '{expr}': {exc}") from exc


def _name(expr: str):
    try:
        result = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise CandleError(f"Nombre de variable inválido: {expr}") from exc
    if isinstance(result, ast.Name):
        return result.id
    if isinstance(result, ast.Constant) and isinstance(result.value, str) and result.value:
        return result.value
    raise CandleError("Use variable(a) o variable(\"nombre con espacios\").")


def run(source: str, max_steps: int = 2000) -> str:
    statements = parse(source)
    env: dict = {}
    output: list[str] = []
    steps = 0

    def perform(block: list[Statement]):
        nonlocal steps
        for statement in block:
            steps += 1
            if steps > max_steps:
                raise CandleError(f"Límite de {max_steps} pasos alcanzado; revise el bucle.")
            try:
                if statement.kind == "variable":
                    env[_name(statement.first)] = evaluate(statement.second, env)
                elif statement.kind == "mostrar":
                    result = evaluate(statement.first, env)
                    output.append("verdadero" if result is True else "falso" if result is False else str(result))
                    if sum(map(len, output)) > 12000:
                        raise CandleError("La salida supera los 12 000 caracteres.")
                elif statement.kind == "si":
                    if evaluate(statement.first, env):
                        perform(statement.body)
                elif statement.kind == "mientras":
                    while evaluate(statement.first, env):
                        steps += 1
                        if steps > max_steps:
                            raise CandleError(f"Límite de {max_steps} pasos alcanzado; revise el bucle.")
                        perform(statement.body)
            except CandleError as exc:
                raise CandleError(f"Línea {statement.line}: {exc}") from exc
    perform(statements)
    return "\n".join(output)
