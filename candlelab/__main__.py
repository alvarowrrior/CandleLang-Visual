"""python -m candlelab hex|script [encode|decode]  ·  python -m candlelab vela <orden>"""

import argparse
import sys
from pathlib import Path

from . import hexadecimal, script
from .vector import CandleError


def legacy(argv):
    parser = argparse.ArgumentParser(prog="candlelab", description="CandleHex, CandleScript y VELA")
    parser.add_argument("mode", choices=("hex", "script"))
    parser.add_argument("action", nargs="?", choices=("encode", "decode"))
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    args = parser.parse_args(argv)
    codec = hexadecimal if args.mode == "hex" else script
    if not args.action:
        from .gui import launch
        launch(args.mode)
        return
    if not args.source or not args.destination:
        parser.error("Indique archivo de entrada y salida.")
    try:
        if args.action == "encode":
            if args.destination.suffix.lower() != ".svg":
                raise CandleError("El destino debe ser .svg.")
            codec.save(args.source.read_bytes().decode("utf-8"), args.destination)
        else:
            args.destination.write_bytes(codec.open_image(args.source).encode("utf-8"))
        print(f"Guardado: {args.destination}")
    except (CandleError, OSError, UnicodeError) as exc:
        parser.exit(2, f"Error: {exc}\n")


def load_candles(path: Path):
    """Velas de un .vela (se compila) o de una imagen/CSV (se lee la geometría)."""
    from . import chart, vela
    if path.suffix.lower() == ".vela":
        return vela.compile_source(path.read_text(encoding="utf-8"))
    return vela.unframe(chart.read_any(path))


def vela_main(argv):
    from . import chart, live, vela, vm
    parser = argparse.ArgumentParser(prog="candlelab vela", description="VELA: programar con velas japonesas")
    sub = parser.add_subparsers(dest="orden")
    p = sub.add_parser("ejecuta", help="ejecuta un .vela, .svg, .png o .csv")
    p.add_argument("archivo", type=Path)
    p.add_argument("--entrada", action="append", default=[], help="línea para la instrucción 'entrada'")
    p = sub.add_parser("compila", help="convierte un .vela en .svg, .png, .csv o .pine")
    p.add_argument("archivo", type=Path)
    p.add_argument("destino", type=Path)
    p.add_argument("--etiquetas", action="store_true", help="escribe el nombre de cada vela debajo")
    p = sub.add_parser("lee", help="lee una imagen o CSV y muestra el programa reconstruido")
    p.add_argument("archivo", type=Path)
    p.add_argument("destino", type=Path, nargs="?")
    p = sub.add_parser("mensaje", help="convierte un texto en un gráfico de velas que lo muestra")
    p.add_argument("texto")
    p.add_argument("destino", type=Path)
    p = sub.add_parser("vivo", help="abre el gráfico en vivo para emitir y recibir mensajes")
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--intervalo", type=float, default=1.0, help="segundos por vela")
    p.add_argument("--sin-ruido", action="store_true", help="no dibujar velas de mercado entre mensajes")
    p.add_argument("--sin-navegador", action="store_true")
    p = sub.add_parser("envia", help="envía un mensaje o programa al gráfico en vivo")
    p.add_argument("texto", help="texto del mensaje o ruta de un .vela")
    p.add_argument("--url", default="http://localhost:8765")
    p = sub.add_parser("escucha", help="recibe y ejecuta los mensajes del gráfico en vivo")
    p.add_argument("--url", default="http://localhost:8765")
    p.add_argument("--historial", action="store_true", help="lee también las velas ya emitidas")
    sub.add_parser("tabla", help="muestra todas las velas-instrucción")
    args = parser.parse_args(argv)

    try:
        if args.orden is None:
            from .gui_vela import launch
            launch()
        elif args.orden == "ejecuta":
            result = vm.run(load_candles(args.archivo), inputs=args.entrada)
            print(result.output, end="")
            if result.stack:
                print(f"[pila final: {', '.join(vm.show(v) for v in result.stack)}]")
        elif args.orden in ("compila", "mensaje"):
            source = (vela.message_program(args.texto) if args.orden == "mensaje"
                      else args.archivo.read_text(encoding="utf-8"))
            candles = vela.compile_frame(source)
            suffix = args.destino.suffix.lower()
            labels = getattr(args, "etiquetas", False)
            if suffix == ".svg":
                chart.save_svg(candles, args.destino, labels)
            elif suffix == ".png":
                chart.save_png(candles, args.destino, labels)
            elif suffix == ".csv":
                chart.save_csv(candles, args.destino)
            elif suffix == ".pine":
                args.destino.write_text(chart.pine(candles), encoding="utf-8")
            else:
                raise CandleError("Destino .svg, .png, .csv o .pine.")
            print(f"Guardado: {args.destino} · {len(candles)} velas")
        elif args.orden == "lee":
            code = vela.disassemble(vela.decode(load_candles(args.archivo)))
            if args.destino:
                args.destino.write_text(code, encoding="utf-8")
                print(f"Guardado: {args.destino}")
            else:
                print(code, end="")
        elif args.orden == "vivo":
            live.serve(args.puerto, args.intervalo, not args.sin_ruido, not args.sin_navegador)
        elif args.orden == "envia":
            path = Path(args.texto)
            is_program = path.suffix.lower() == ".vela" and path.exists()
            text = path.read_text(encoding="utf-8") if is_program else args.texto
            answer = live.send(text, args.url, is_program)
            print(f"En cola: {answer['velas']} velas · llegarán en ~{answer['segundos']} s")
        elif args.orden == "escucha":
            print(f"Escuchando {args.url} … (Ctrl+C para salir)")
            live.listen(args.url, history=args.historial)
        elif args.orden == "tabla":
            print(f"{'instrucción':<13}{'vela':<11}{'familia':<16}patrón")
            for name, sig in vela.OPCODES.items():
                family, pattern = vela.INFO[name]
                print(f"{name:<13}{str(sig):<11}{family:<16}{pattern}")
    except KeyboardInterrupt:
        pass
    except (CandleError, OSError, UnicodeError) as exc:
        parser.exit(2, f"Error: {exc}\n")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    argv = sys.argv[1:]
    if argv and argv[0] == "vela":
        vela_main(argv[1:])
    else:
        legacy(argv)


if __name__ == "__main__":
    main()
