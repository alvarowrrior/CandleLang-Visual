"""Ejecución explícita de CandleScript y compatibilidad con #Bash python/bash."""

import re
import shutil
import subprocess
import sys
import tempfile

from . import dsl
from .vector import CandleError

MARKER = re.compile(r"\A#Bash\s+(python|bash)\s*\r?\n", re.IGNORECASE)


def execute(source: str) -> str:
    if not source.startswith("#Bash"):
        return dsl.run(source)
    marker = MARKER.match(source)
    if not marker:
        raise CandleError("Use '#Bash python' o '#Bash bash' en la primera línea.")
    body = source[marker.end():]
    if not body.strip():
        raise CandleError("El programa está vacío.")
    if marker.group(1).lower() == "python":
        command = [sys.executable, "-I", "-c", body]
    else:
        bash = shutil.which("bash")
        if bash is None:
            raise CandleError("Bash no está instalado en este equipo.")
        command = [bash, "-c", body]
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        try:
            status = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            status = -1
        output.seek(0)
        text = output.read(12000)
        if output.read(1):
            text += "\n[Salida truncada.]"
        if status == -1:
            text += "\n[Interrumpido tras 10 segundos.]"
        return f"Proceso terminado con código {status}.\n{text}"
