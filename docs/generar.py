"""Regenera las imágenes de docs/:  py docs/generar.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from candlelab import chart, vela
from candlelab.chart import BACKGROUND, COLORS, MUTED, _font

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
U = 7


def candle(draw, x, base, sig):
    color = COLORS[sig.kind]
    top = base - (sig.body + sig.upper) * U
    draw.line((x, top, x, base + sig.lower * U), fill=color, width=2)
    if sig.kind == "D":
        draw.rectangle((x - 7, base - 1, x + 7, base + 1), fill=color)
    else:
        draw.rectangle((x - 7, base - sig.body * U, x + 7, base - 1), fill=color)


def alphabet():
    rows = [(f"{fam} · {pat} · {'verde' if col == 'V' else 'roja'} · mechas {up}/{low}",
             [(n, vela.OPCODES[n]) for n in names]) for fam, pat, col, up, low, names in vela.FAMILIES]
    rows.insert(0, ("números · Marubozu · verde inicia, roja añade dígito",
                    [(f"{'V' if d < 5 else 'R'} {d}", vela.digit(d, d < 5)) for d in range(10)]))
    rows.append(("control · doji (cuerpo 0)", [(n, vela.OPCODES[n]) for n in vela.DOJIS]))
    rows.append(("texto y trama · peonzas largas",
                 [("« abre", vela.QUOTE_OPEN), ("» cierra", vela.QUOTE_CLOSE),
                  ("[[ inicio", vela.FRAME_START), ("]] final", vela.FRAME_END)]))
    width, row_h = 1240, 150
    image = Image.new("RGB", (width, 90 + row_h * len(rows)), BACKGROUND)
    draw = ImageDraw.Draw(image)
    title, small, label = _font(26), _font(13), _font(14)
    draw.text((30, 24), "Alfabeto VELA1 — cada vela es una instrucción", fill=(230, 238, 248), font=title)
    for r, (heading, items) in enumerate(rows):
        y0 = 80 + r * row_h
        draw.line((30, y0, width - 30, y0), fill=(28, 42, 64))
        draw.text((30, y0 + 8), heading, fill=MUTED, font=small)
        for i, (name, sig) in enumerate(items):
            x = 70 + i * 108
            candle(draw, x, y0 + 95, sig)
            draw.text((x + 16, y0 + 70), name, fill=(214, 222, 235), font=label)
            draw.text((x + 16, y0 + 90), str(sig), fill=MUTED, font=small)
    image.save(HERE / "alfabeto.png", optimize=True)


def examples():
    for name in ("hola", "fizzbuzz", "factorial"):
        candles = vela.compile_frame((ROOT / "ejemplos" / f"{name}.vela").read_text(encoding="utf-8"))
        chart.save_png(candles, HERE / f"{name}.png", labels=True)
        chart.save_svg(candles, HERE / f"{name}.svg")


if __name__ == "__main__":
    alphabet()
    examples()
    print("Imágenes regeneradas en", HERE)
