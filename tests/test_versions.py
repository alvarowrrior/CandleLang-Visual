import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from candlelab import dsl, hexadecimal as hx, script as sc
from candlelab.runtime import execute
from candlelab.vector import Candle, CandleError, positions, read_svg


class HexTests(unittest.TestCase):
    def test_zero_negative_and_powers(self):
        self.assertEqual(hx.SYNC[:4], [Candle(True, 1), Candle(False, 1), Candle(True, 2), Candle(False, 2)])
        self.assertEqual(hx.decode(hx.encode("Árbol 📈\n")), "Árbol 📈\n")
        self.assertEqual(hx.decode([]), "")
        for candle in hx.encode("A"):
            self.assertEqual(candle.height & (candle.height - 1), 0)
            self.assertLessEqual(candle.height, 32768)

    def test_hex_svg_round_trip_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "msg.svg"
            hx.save("Hola, ñ 📈", path)
            self.assertEqual(hx.open_image(path), "Hola, ñ 📈")
            chart = read_svg(path, "HEX1", hx.MAX_CANDLES)
            coords, _, _ = positions(chart)
            self.assertTrue(all(finish == next_start for (_, finish), (next_start, _) in zip(coords, coords[1:])))
            tree = ET.parse(path)
            group = next(node for node in tree.getroot() if node.get("id") == "candles")
            group[3].set("y", str(int(group[3].get("y")) + 1))
            tree.write(path, encoding="utf-8")
            with self.assertRaises(CandleError):
                hx.open_image(path)


class ScriptTests(unittest.TestCase):
    def test_keyword_velas_and_exact_round_trip(self):
        source = 'variable("nombre usado") = verdadero\nmostrar(valor("nombre usado"))\n'
        chart = sc.encode(source)
        self.assertIn(Candle(True, 24), chart)
        self.assertIn(Candle(True, 48), chart)
        self.assertEqual(sc.decode(chart), source)
        self.assertEqual(dsl.run(source), "verdadero")
        self.assertEqual(sc.decode(sc.encode('mostrar("variable mientras")')), 'mostrar("variable mientras")')

    def test_svg_round_trip_and_languages(self):
        source = '#Bash python\nprint(3 + 7)\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.svg"
            sc.save(source, path)
            self.assertEqual(sc.open_image(path), source)
        self.assertIn("10", execute(source))

    def test_loop_alias_and_limit(self):
        source = ("variable(a) = verdadero\nvariable(n) = 0\n"
                  "mientras a sea verdadero encontes\n"
                  "mostrar(n)\nvariable(n) = n + 1\n"
                  "si n sea 3 entonces\nvariable(a) = falso\nfin\nfin\n")
        self.assertEqual(dsl.run(source), "0\n1\n2")
        with self.assertRaisesRegex(CandleError, "Límite"):
            dsl.run("mientras verdadero sea verdadero entonces\nfin", max_steps=12)
        with self.assertRaises(CandleError):
            dsl.run("mostrar(__import__('os').getcwd())")

    def test_sync_or_macro_damage_rejected(self):
        encoded = sc.encode("variable(a) = 1")
        encoded[0] = Candle(False, 8)
        with self.assertRaises(CandleError):
            sc.decode(encoded)
        encoded = sc.encode("variable(a) = 1")
        i = encoded.index(Candle(True, 24))
        encoded[i] = Candle(True, 88)
        with self.assertRaises(CandleError):
            sc.decode(encoded)


if __name__ == "__main__":
    unittest.main()
