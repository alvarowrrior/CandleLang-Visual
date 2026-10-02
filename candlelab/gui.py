"""Dos aplicaciones de escritorio independientes con una presentación común."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from . import hexadecimal, runtime, script
from .vector import CandleError, preview


class App:
    def __init__(self, root: tk.Tk, mode: str):
        self.root = root
        self.mode = mode
        self.codec = hexadecimal if mode == "hex" else script
        self.window = 32 if mode == "hex" else 48
        self.candles = []
        self.pending = None
        self.revision = 0
        self.photo = None
        self.status = tk.StringVar(value="Escriba para transformar el mensaje en velas.")
        root.title("CandleHex · HEX1" if mode == "hex" else "CandleScript · SCR1")
        root.geometry("1250x770")

        bar = ttk.Frame(root, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Guardar SVG", command=self.save).pack(side="left", padx=4)
        ttk.Button(bar, text="Abrir SVG", command=self.open).pack(side="left", padx=4)
        ttk.Button(bar, text="Cargar ejemplo", command=self.example).pack(side="left", padx=4)
        self.run_button = None
        if mode == "script":
            self.run_button = ttk.Button(bar, text="Ejecutar programa", command=self.execute)
            self.run_button.pack(side="left", padx=4)
        ttk.Label(bar, text="HEX1 · 0–F · ↑/↓" if mode == "hex" else "SCR1 · bits + palabras reservadas").pack(side="right")

        panels = ttk.PanedWindow(root, orient="horizontal")
        panels.pack(fill="both", expand=True, padx=12)
        left, right = ttk.Frame(panels), ttk.Frame(panels)
        panels.add(left, weight=1)
        panels.add(right, weight=1)
        ttk.Label(left, text="Mensaje" if mode == "hex" else "Programa").pack(anchor="w")
        self.editor = tk.Text(left, wrap="word", undo=True, font=("Consolas", 11),
                              bg="#101d2f", fg="#e6eef8", insertbackground="#e6eef8", padx=12, pady=12)
        self.editor.pack(fill="both", expand=True, pady=5)
        self.editor.bind("<<Modified>>", self.on_modified)
        ttk.Label(left, text=("Admite cualquier texto UTF-8, incluidas tildes y emoji."
                              if mode == "hex" else "Ej.: variable(a) = verdadero · mientras a sea verdadero entonces")).pack(anchor="w")

        ttk.Label(right, text=("Vista esquemática: alturas 2ⁿ comprimidas SOLO aquí"
                               if mode == "hex" else "Vista del gráfico continuo · las palabras tienen velas propias")).pack(anchor="w")
        self.image = ttk.Label(right, anchor="center", background="#0b1320")
        self.image.pack(fill="both", expand=True, pady=5)
        self.scroll = ttk.Scale(right, from_=0, to=0, orient="horizontal", command=self.scroll_preview)
        self.scroll.pack(fill="x")
        ttk.Label(right, text="Bytes del mensaje (hexadecimal)" if mode == "hex" else "Salida del programa").pack(anchor="w", pady=(10, 3))
        self.output = tk.Text(right, height=8, state="disabled", wrap="word", font=("Consolas", 10),
                              bg="#101d2f", fg="#e6eef8", padx=10, pady=8)
        self.output.pack(fill="x")
        ttk.Label(root, textvariable=self.status, padding=10).pack(fill="x")
        root.after(50, self.refresh)

    def source(self):
        return self.editor.get("1.0", "end-1c")

    def show_output(self, value: str):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", value)
        self.output.configure(state="disabled")

    def on_modified(self, _event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            self.revision += 1
            if self.mode == "script":
                self.show_output("")
            if self.pending:
                self.root.after_cancel(self.pending)
            self.pending = self.root.after(400, self.refresh)

    def refresh(self):
        self.pending = None
        text = self.source()
        try:
            self.candles = self.codec.encode(text)
            last = max(0, len(self.candles) - self.window)
            self.scroll.configure(to=last)
            self.scroll.set(last)
            self.draw_visible(last)
            self.status.set(f"{len(text.encode('utf-8'))} bytes · {len(self.candles)} velas · gráfico horizontal completo al exportar.")
            if self.mode == "hex":
                data = text.encode("utf-8")
                self.show_output(data[:300].hex(" ") + (" …" if len(data) > 300 else ""))
        except CandleError as exc:
            self.status.set(str(exc))

    def scroll_preview(self, value):
        self.draw_visible(int(float(value)))

    def draw_visible(self, start):
        segment = self.candles[start:start + self.window]
        self.photo = ImageTk.PhotoImage(preview(segment, schematic=self.mode == "hex"))
        self.image.configure(image=self.photo)

    def save(self):
        try:
            candles = self.codec.encode(self.source())
        except CandleError as exc:
            messagebox.showerror("No se puede guardar", str(exc))
            return
        path = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("Imagen SVG", "*.svg")],
                                            initialfile="candlehex.svg" if self.mode == "hex" else "candlescript.svg")
        if path:
            self.codec.save(self.source(), path)
            self.status.set(f"Imagen guardada: {Path(path).name} · {len(candles)} velas.")

    def open(self):
        path = filedialog.askopenfilename(filetypes=[("Imagen SVG", "*.svg")])
        if not path:
            return
        try:
            content = self.codec.open_image(path)
        except (CandleError, OSError) as exc:
            messagebox.showerror("Imagen ilegible", str(exc))
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", content)
        self.status.set(f"Imagen decodificada: {Path(path).name}")

    def example(self):
        text = ("Hola, mundo. ¡Este mensaje viaja en hexadecimal! 📈"
                if self.mode == "hex" else
                'variable(a) = verdadero\nvariable(contador) = 0\nmientras a sea verdadero entonces\n'
                '    mostrar(contador)\n    variable(contador) = contador + 1\n'
                '    si contador sea 5 entonces\n        variable(a) = falso\n    fin\nfin\n')
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)

    def execute(self):
        content = self.source()
        if content.startswith("#Bash") and not messagebox.askyesno(
            "Ejecutar en este equipo", "El código Python/Bash se ejecutará con los permisos de su usuario. ¿Continuar?",
            icon="warning"):
            return
        revision = self.revision
        self.run_button.configure(state="disabled")
        self.status.set("Ejecutando…")

        def work():
            try:
                result = runtime.execute(content)
            except (CandleError, OSError) as exc:
                result = str(exc)
            self.root.after(0, lambda: self.finish(result, revision))

        threading.Thread(target=work, daemon=True).start()

    def finish(self, text, revision):
        if revision == self.revision:
            self.show_output(text)
            self.status.set("Ejecución terminada.")
        self.run_button.configure(state="normal")


def launch(mode: str):
    root = tk.Tk()
    App(root, mode)
    root.mainloop()
