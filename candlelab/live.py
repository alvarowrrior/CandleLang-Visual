"""Gráfico VELA en vivo: un servidor emite velas OHLC y cualquier receptor las lee.

El flujo /flujo solo transporta precios (apertura, máximo, mínimo, cierre). Ni el
navegador ni `vela escucha` reciben el texto: lo reconstruyen leyendo las velas.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import vela, vm
from .chart import BASE_PRICE, TICK, signature
from .vela import FRAME_START, Sig
from .vector import CandleError

WEB = Path(__file__).with_name("web")
STATIC = {"/": ("vivo.html", "text/html"), "/vela.js": ("vela.js", "text/javascript"),
          "/lightweight-charts.js": ("lightweight-charts.js", "text/javascript")}
MAX_QUEUE = 20_000
HISTORY = 3_000


class Station:
    """Genera una vela por intervalo: la siguiente de la cola o ruido de mercado."""

    def __init__(self, interval: float = 1.0, noise: bool = True, seed=None):
        self.interval, self.noise = interval, noise
        self.queue: deque[Sig] = deque()
        self.history: list[dict] = []
        self.sequence = 0
        self.cond = threading.Condition()
        self.price = 0
        self.time = int(time.time()) // 60 * 60
        self.rng = random.Random(seed)

    def enqueue(self, candles: list[Sig]) -> float:
        with self.cond:
            if len(self.queue) + len(candles) > MAX_QUEUE:
                raise CandleError("La cola de transmisión está llena; espere a que se vacíe.")
            self.queue.extend(candles)
            return len(self.queue) * self.interval

    def _noise(self) -> Sig:
        while True:
            pull = -0.35 if self.price > 30 else 0.35 if self.price < -30 else 0
            roll = self.rng.random() + pull
            kind = "D" if self.rng.random() < 0.08 else "V" if roll > 0.5 else "R"
            body = 0 if kind == "D" else self.rng.randint(1, 6)
            sig = Sig(kind, body, self.rng.randint(0, 3), self.rng.randint(0, 3))
            if sig != FRAME_START:
                return sig

    def tick(self):
        with self.cond:
            if self.queue:
                sig = self.queue.popleft()
            elif self.noise:
                sig = self._noise()
            else:
                return
            close = self.price + (sig.body if sig.kind == "V" else -sig.body if sig.kind == "R" else 0)
            o, c = self.price, close
            bar = {"time": self.time, "open": o, "high": max(o, c) + sig.upper,
                   "low": min(o, c) - sig.lower, "close": c}
            bar = {k: (v if k == "time" else round(BASE_PRICE + v * TICK, 4)) for k, v in bar.items()}
            self.price, self.time = close, self.time + 60
            self.history.append(bar)
            self.sequence += 1
            del self.history[:-HISTORY]
            self.cond.notify_all()

    def loop(self, stop: threading.Event):
        while not stop.wait(self.interval):
            self.tick()

    def since(self, seen: int, timeout: float = 15.0):
        """Velas nuevas desde el número de secuencia `seen`."""
        with self.cond:
            self.cond.wait_for(lambda: self.sequence > seen, timeout)
            fresh = min(self.sequence - seen, len(self.history))
            return self.sequence, self.history[len(self.history) - fresh:] if fresh else []


def handler_for(station: Station):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, kind: str):
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data):
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in STATIC:
                name, kind = STATIC[path]
                self._send(200, (WEB / name).read_bytes(), kind)
            elif path == "/estado":
                with station.cond:
                    self._json(200, {"cola": len(station.queue), "intervalo": station.interval,
                                     "base": BASE_PRICE, "tick": TICK})
            elif path == "/flujo":
                self._stream()
            else:
                self._send(404, b"No encontrado", "text/plain")

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with station.cond:
                    seen, history = station.sequence, list(station.history)
                self.wfile.write(f"event: historia\ndata: {json.dumps(history)}\n\n".encode())
                self.wfile.flush()
                while True:
                    seen, bars = station.since(seen)
                    payload = "".join(f"data: {json.dumps(bar)}\n\n" for bar in bars) or ": latido\n\n"
                    self.wfile.write(payload.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

        def do_POST(self):
            if self.path != "/enviar":
                self._send(404, b"No encontrado", "text/plain")
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if size > 200_000:
                    raise CandleError("Mensaje demasiado grande.")
                data = json.loads(self.rfile.read(size) or b"{}")
                text = str(data.get("texto", ""))
                if not text.strip():
                    raise CandleError("Escriba un mensaje o programa.")
                source = vela.message_program(text) if data.get("modo") != "programa" else text
                candles = vela.compile_frame(source)
                vm.match_blocks(vela.decode(vela.unframe(candles)))
                seconds = station.enqueue(candles)
                self._json(200, {"velas": len(candles), "segundos": round(seconds, 1)})
            except (CandleError, ValueError) as exc:
                self._json(400, {"error": str(exc)})

    return Handler


def serve(port: int = 8765, interval: float = 1.0, noise: bool = True, open_browser: bool = True):
    station = Station(interval, noise)
    for _ in range(60):
        station.tick()
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_for(station))
    server.daemon_threads = True
    stop = threading.Event()
    threading.Thread(target=station.loop, args=(stop,), daemon=True).start()
    url = f"http://localhost:{port}/"
    print(f"Gráfico VELA en vivo: {url}")
    print(f"Desde otro equipo de la red: http://<IP de este equipo>:{port}/")
    print("Ctrl+C para detener.")
    if open_browser:
        threading.Timer(0.8, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


def send(text: str, url: str = "http://localhost:8765", program: bool = False) -> dict:
    body = json.dumps({"texto": text, "modo": "programa" if program else "mensaje"}).encode("utf-8")
    request = urllib.request.Request(url.rstrip("/") + "/enviar", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise CandleError(json.loads(exc.read()).get("error", str(exc))) from exc


def listen(url: str = "http://localhost:8765", on_event=print, history: bool = False, limit: int | None = None):
    """Lee el flujo OHLC, reconstruye las tramas y ejecuta cada programa recibido."""
    receiver = vela.Receiver()
    received = 0

    def feed(bar):
        nonlocal received
        units = [round((bar[k] - BASE_PRICE) / TICK) for k in ("open", "high", "low", "close")]
        result = receiver.push(signature(*units))
        if result is None:
            return False
        candles, error = result
        if error:
            on_event(f"✗ Trama dañada: {error}")
            return False
        code = vela.decode(candles)
        on_event("─" * 60 + f"\n⟦ Trama recibida · {len(candles)} velas · CRC correcto\n"
                 + vela.disassemble(code).rstrip())
        try:
            on_event("▶ Salida:\n" + vm.run(code).output.rstrip())
        except CandleError as exc:
            on_event(f"✗ Error al ejecutar: {exc}")
        received += 1
        return limit is not None and received >= limit

    with urllib.request.urlopen(url.rstrip("/") + "/flujo", timeout=60) as stream:
        event = None
        for raw in stream:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
                bars = data if event == "historia" else [data]
                if event == "historia" and not history:
                    bars = []
                for bar in bars:
                    if feed(bar):
                        return
            elif not line:
                event = None
