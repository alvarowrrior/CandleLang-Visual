import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from candlelab import chart, vela, vm
from candlelab.vector import CandleError
from candlelab.vela import Sig

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((ROOT / "ejemplos").glob("*.vela"))


def run(source, inputs=()):
    return vm.run(vela.compile_source(source), inputs=inputs, seed=7).output


class LanguageTests(unittest.TestCase):
    def test_every_opcode_is_unique(self):
        sigs = list(vela.OPCODES.values()) + [vela.QUOTE_OPEN, vela.QUOTE_CLOSE,
                                               vela.FRAME_START, vela.FRAME_END]
        self.assertEqual(len(sigs), len(set(sigs)))
        self.assertTrue(all(s.upper or s.lower or s.kind == "D" for s in sigs))

    def test_arithmetic_stack_and_text(self):
        self.assertEqual(run("2 3 + 4 * mostrar"), "20\n")
        self.assertEqual(run("7 -2 / mostrar 7 -2 % mostrar 2 10 ^ mostrar"), "-4\n-1\n1024\n")
        self.assertEqual(run("1 2 3 rota mostrar mostrar mostrar"), "1\n3\n2\n")
        self.assertEqual(run('"vela" mayusculas " " une 3 une mostrar'), "VELA 3\n")
        self.assertEqual(run('"ñandú" longitud mostrar "ab" 1 letra mostrar 65 caracter mostrar'), "5\nb\nA\n")
        self.assertEqual(run('"42" numero 1 + mostrar 1 2 == mostrar 3 3 == no mostrar'), "43\nfalso\nfalso\n")

    def test_control_flow_and_functions(self):
        self.assertEqual(run("3 veces indice escribe fin"), "012")
        self.assertEqual(run("0 =i mientras i 3 < hacer i escribe i 1 + =i fin"), "012")
        self.assertEqual(run("1 si 1 mostrar sino 2 mostrar fin 0 si 1 mostrar sino 2 mostrar fin"), "1\n2\n")
        self.assertEqual(run("define doble 2 * fin 21 doble mostrar"), "42\n")
        self.assertEqual(run("1 mostrar alto 2 mostrar"), "1\n")
        self.assertEqual(run("entrada mayusculas mostrar", ["hola"]), "HOLA\n")

    def test_errors_are_reported_with_candle_index(self):
        for source, message in [("1 0 /", "cero"), ("mostrar", "vacía"), ("si", "fin"),
                                ("mientras 1 fin", "hacer"), ("x", "v0"), ("mientras verdadero hacer fin", "Límite")]:
            with self.assertRaisesRegex(CandleError, message):
                run(source)
        with self.assertRaisesRegex(CandleError, "reservada"):
            vela.compile_source("=si")

    def test_examples_round_trip_through_disassembly(self):
        self.assertGreaterEqual(len(EXAMPLES), 6)
        for path in EXAMPLES:
            candles = vela.compile_source(path.read_text(encoding="utf-8"))
            text = vela.disassemble(vela.decode(candles))
            self.assertEqual(vela.compile_source(text), candles, path.name)


class ChartTests(unittest.TestCase):
    def test_frame_detects_tampering(self):
        framed = vela.compile_frame('"hola" mostrar')
        self.assertEqual(vela.unframe(framed), vela.compile_source('"hola" mostrar'))
        damaged = framed.copy()
        damaged[3] = Sig("V", damaged[3].body % 16 + 1, 0, 0)
        with self.assertRaisesRegex(CandleError, "CRC"):
            vela.unframe(damaged)

    def test_images_and_csv_round_trip(self):
        candles = vela.compile_frame((ROOT / "ejemplos" / "fizzbuzz.vela").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            for name, saver in [("a.svg", chart.save_svg), ("b.png", chart.save_png), ("c.csv", chart.save_csv)]:
                path = Path(folder) / name
                saver(candles, path)
                self.assertEqual(chart.read_any(path), candles, name)
            chart.save_png(candles, Path(folder) / "d.png", True)
            self.assertEqual(chart.read_png(Path(folder) / "d.png"), candles)

    def test_receiver_ignores_market_noise(self):
        noise = [Sig("V", 3, 1, 2), Sig("R", 5, 0, 3), Sig("D", 0, 2, 2)]
        receiver, frames = vela.Receiver(), []
        for candle in noise + vela.compile_frame('"ok" mostrar') + noise:
            result = receiver.push(candle)
            if result:
                frames.append(result)
        self.assertEqual(len(frames), 1)
        self.assertEqual(vm.run(frames[0][0]).output, "ok\n")

    def test_continuity_is_checked(self):
        bars = chart.ohlc(vela.compile_frame("1 mostrar"))
        prices = [[float(v) for v in bar] for bar in bars]
        prices[2][0] += 1
        with self.assertRaisesRegex(CandleError, "abre"):
            chart.from_prices(prices, 1.0)


@unittest.skipIf(shutil.which("node") is None, "Node.js no está instalado")
class JavaScriptTests(unittest.TestCase):
    def test_javascript_matches_python(self):
        cases = {p.name: p.read_text(encoding="utf-8") for p in EXAMPLES if p.stem != "dado"}
        expected = {name: {"candles": [[c.kind, c.body, c.upper, c.lower] for c in vela.compile_frame(src)],
                           "out": vm.run(vela.compile_source(src), inputs=["Ana"]).output}
                    for name, src in cases.items()}
        script = """
const V = require(process.argv[1]); const cases = JSON.parse(process.argv[2]); const res = {};
for (const [n, src] of Object.entries(cases)) res[n] = {
  candles: V.frame(V.compile(src)).map(s => [s.kind, s.body, s.upper, s.lower]),
  out: V.run(V.compile(src), {inputs: ["Ana"]}).output };
console.log(JSON.stringify(res));"""
        out = subprocess.run(["node", "-e", script, str(ROOT / "candlelab" / "web" / "vela.js"), json.dumps(cases)],
                             capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(out.stdout), expected)


if __name__ == "__main__":
    unittest.main()
