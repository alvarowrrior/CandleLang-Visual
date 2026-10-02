"""Editor de escritorio de VELA: escribe código, mira sus velas, ejecútalo y guárdalo."""

from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from . import chart, vela, vm
from .vector import CandleError

EXAMPLES = Path(__file__).resolve().parent.parent / "ejemplos"
WINDOW = 46
DARK = {"bg": "#101d2f", "fg": "#e6eef8", "insertbackground": "#e6eef8"}


class VelaApp:
    def __init__(self, root: tk.Tk):
        self.root, self.candles, self.listing = root, [], []
        self.pending, self.photo, self.server = None, None, None
        self.status = tk.StringVar(value="Escriba un programa VELA: cada palabra se convierte en velas.")
        root.title("CandleLab · VELA — programar con velas")
        root.geometry("1360x820")
        root.configure(bg="#0b1320")

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        buttons = [("▶ Ejecutar", self.execute), ("Abrir imagen…", self.open_image),
                   ("Guardar SVG", lambda: self.export(".svg")), ("Guardar PNG", lambda: self.export(".png")),
                   ("Exportar CSV", lambda: self.export(".csv")), ("Pine Script", lambda: self.export(".pine")),
                   ("Abrir .vela…", self.open_source), ("Guardar .vela", self.save_source),
                   ("📡 En vivo", self.live)]
        for text, command in buttons:
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=3)
        self.labels = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Etiquetas", variable=self.labels, command=self.draw).pack(side="left", padx=8)
        names = sorted(p.stem for p in EXAMPLES.glob("*.vela")) if EXAMPLES.exists() else []
        self.example = ttk.Combobox(bar, values=names, state="readonly", width=14)
        self.example.set("Ejemplos…")
        self.example.bind("<<ComboboxSelected>>", lambda _e: self.load_example())
        self.example.pack(side="right")

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=2)
        panes.add(right, weight=3)

        ttk.Label(left, text="Programa VELA").pack(anchor="w")
        self.editor = tk.Text(left, wrap="none", undo=True, font=("Consolas", 12), padx=12, pady=12, **DARK)
        self.editor.pack(fill="both", expand=True, pady=4)
        self.editor.bind("<<Modified>>", self.on_modified)
        self.editor.bind("<KeyRelease>", lambda _e: self.locate())
        self.editor.bind("<ButtonRelease-1>", lambda _e: self.locate())
        ttk.Label(left, text="Entrada (una línea por cada 'entrada')").pack(anchor="w")
        self.inputs = tk.Text(left, height=3, font=("Consolas", 11), padx=8, pady=6, **DARK)
        self.inputs.pack(fill="x", pady=(2, 6))

        ttk.Label(right, text="Gráfico del programa · trama ⟦ … ⟧ + CRC").pack(anchor="w")
        self.image = tk.Label(right, bg="#0b1320", anchor="center")
        self.image.pack(fill="both", expand=True, pady=4)
        self.scroll = ttk.Scale(right, from_=0, to=0, orient="horizontal", command=lambda _v: self.draw())
        self.scroll.pack(fill="x")
        self.info = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.info, font=("Consolas", 10)).pack(anchor="w", pady=4)
        ttk.Label(right, text="Salida").pack(anchor="w")
        self.output = tk.Text(right, height=9, state="disabled", font=("Consolas", 11), padx=10, pady=8, **DARK)
        self.output.pack(fill="x")
        ttk.Label(root, textvariable=self.status, padding=8).pack(fill="x")
        root.protocol("WM_DELETE_WINDOW", self.close)
        if names:
            self.example.set("fizzbuzz" if "fizzbuzz" in names else names[0])
            self.load_example()

    # ------------------------------------------------------------ edición
    def source(self):
        return self.editor.get("1.0", "end-1c")

    def set_source(self, text):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)

    def show_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def on_modified(self, _event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            if self.pending:
                self.root.after_cancel(self.pending)
            self.pending = self.root.after(350, self.refresh)

    def refresh(self):
        self.pending = None
        try:
            self.listing = vela.compile_listing(self.source())
            body = [c for entry in self.listing for c in entry.candles]
            self.candles = vela.frame(body)
            vm.match_blocks(vela.decode(body))
            self.status.set(f"{len(body)} velas de programa · {len(self.candles)} con trama y CRC")
        except CandleError as exc:
            self.status.set(f"✗ {exc}")
            return
        last = max(0, len(self.candles) - WINDOW)
        self.scroll.configure(to=last)
        self.scroll.set(min(float(self.scroll.get()), last))
        self.draw()

    def locate(self):
        """Muestra las velas de la palabra donde está el cursor."""
        line = int(self.editor.index("insert").split(".")[0])
        position, found = 1, None
        for entry in self.listing:
            if entry.line == line and found is None:
                found = (position, entry)
            position += len(entry.candles)
        if found:
            start, entry = found
            self.scroll.set(max(0, min(start - WINDOW // 3, len(self.candles) - WINDOW)))
            sigs = " ".join(str(c) for c in entry.candles[:6]) + (" …" if len(entry.candles) > 6 else "")
            family = vela.INFO.get(entry.word.split()[0], ("dato", ""))
            self.info.set(f"«{entry.word}» → {len(entry.candles)} vela(s): {sigs}   [{' · '.join(filter(None, family))}]")
            self.draw(highlight=start)

    def draw(self, highlight=None):
        start = int(float(self.scroll.get()))
        segment = self.candles[start:start + WINDOW]
        image = chart.render(segment, self.labels.get(),
                             None if highlight is None else highlight - start)
        image.thumbnail((820, 520))
        self.photo = ImageTk.PhotoImage(image)
        self.image.configure(image=self.photo)

    # ------------------------------------------------------------ acciones
    def execute(self):
        try:
            body = vela.compile_source(self.source())
        except CandleError as exc:
            self.show_output(f"✗ {exc}")
            return
        lines = self.inputs.get("1.0", "end-1c").splitlines()
        self.status.set("Ejecutando…")

        def work():
            try:
                result = vm.run(body, inputs=lines)
                text = result.output + (f"\n[pila final: {', '.join(map(vm.show, result.stack))}]"
                                        if result.stack else "")
                note = f"✓ {result.steps} pasos ejecutados."
            except CandleError as exc:
                text, note = f"✗ {exc}", "Error de ejecución."
            done.append((text, note))

        def poll():
            if done:
                self.show_output(done[0][0])
                self.status.set(done[0][1])
            else:
                self.root.after(50, poll)

        done: list = []
        threading.Thread(target=work, daemon=True).start()
        poll()

    def export(self, suffix):
        if not self.candles:
            return
        kinds = {".svg": "Imagen SVG", ".png": "Imagen PNG", ".csv": "Datos OHLC", ".pine": "Pine Script"}
        path = filedialog.asksaveasfilename(defaultextension=suffix, filetypes=[(kinds[suffix], "*" + suffix)],
                                            initialfile="programa" + suffix)
        if not path:
            return
        if suffix == ".svg":
            chart.save_svg(self.candles, path, self.labels.get())
        elif suffix == ".png":
            chart.save_png(self.candles, path, self.labels.get())
        elif suffix == ".csv":
            chart.save_csv(self.candles, path)
        else:
            Path(path).write_text(chart.pine(self.candles), encoding="utf-8")
        self.status.set(f"Guardado {Path(path).name} · {len(self.candles)} velas.")

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[("Gráficos VELA", "*.svg *.png *.csv")])
        if not path:
            return
        try:
            body = vela.unframe(chart.read_any(path))
            code = vela.disassemble(vela.decode(body))
        except (CandleError, OSError) as exc:
            messagebox.showerror("Gráfico ilegible", str(exc))
            return
        self.set_source(f"# Leído de {Path(path).name}: {len(body)} velas, CRC correcto\n" + code)
        self.status.set("Imagen interpretada. Pulse ▶ Ejecutar para correr el programa.")

    def open_source(self):
        path = filedialog.askopenfilename(filetypes=[("Programa VELA", "*.vela"), ("Texto", "*.txt")])
        if path:
            self.set_source(Path(path).read_text(encoding="utf-8"))

    def save_source(self):
        path = filedialog.asksaveasfilename(defaultextension=".vela", filetypes=[("Programa VELA", "*.vela")])
        if path:
            Path(path).write_text(self.source(), encoding="utf-8")

    def load_example(self):
        path = EXAMPLES / f"{self.example.get()}.vela"
        if path.exists():
            self.set_source(path.read_text(encoding="utf-8"))
            self.show_output("")

    def live(self):
        if self.server is None or self.server.poll() is not None:
            self.server = subprocess.Popen([sys.executable, "-m", "candlelab", "vela", "vivo", "--sin-navegador"],
                                           cwd=Path(__file__).resolve().parent.parent)
            self.root.after(1200, lambda: webbrowser.open("http://localhost:8765/"))
        else:
            webbrowser.open("http://localhost:8765/")
        self.status.set("Gráfico en vivo en http://localhost:8765/ — compártelo en tu red con tu IP.")

    def close(self):
        if self.server and self.server.poll() is None:
            self.server.terminate()
        self.root.destroy()


def launch():
    root = tk.Tk()
    VelaApp(root)
    root.mainloop()
