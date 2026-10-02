/* VELA1 en JavaScript: compilador, lector de velas, máquina de pila y receptor de tramas.
 * Implementación independiente de la de Python (candlelab/vela.py y vm.py); ambas
 * producen exactamente las mismas velas para el mismo programa. */
(function (global) {
  "use strict";

  const FAMILIES = [
    ["aritmética", "Estrella fugaz", "V", 1, 0, ["+", "-", "*", "/", "%", "neg", "^", "abs"]],
    ["pila", "Estrella fugaz", "R", 1, 0, ["dup", "quita", "cambia", "copia", "rota", "profundidad"]],
    ["comparación", "Martillo", "V", 0, 1, ["==", "!=", "<", ">", "<=", ">="]],
    ["lógica", "Martillo", "R", 0, 1, ["y", "o", "no", "verdadero", "falso"]],
    ["memoria", "Peonza", "V", 1, 1, ["guarda", "lee"]],
    ["funciones", "Peonza", "R", 1, 1, ["llama"]],
    ["texto", "Estrella fugaz larga", "V", 2, 0, ["longitud", "caracter", "codigo", "une", "letra", "mayusculas", "minusculas"]],
    ["conversión", "Estrella fugaz larga", "R", 2, 0, ["numero", "texto"]],
    ["entrada/salida", "Martillo largo", "V", 0, 2, ["mostrar", "escribe", "entrada", "salto"]],
    ["sistema", "Martillo largo", "R", 0, 2, ["aleatorio", "indice"]],
  ];
  const DOJIS = {
    nada: [0, 0, "Doji plano"], si: [0, 2, "Doji libélula"], sino: [2, 2, "Doji de piernas largas"],
    fin: [2, 0, "Doji lápida"], mientras: [1, 1, "Doji estrella"], hacer: [1, 2, "Doji ancla"],
    veces: [2, 1, "Doji farol"], define: [3, 0, "Doji antena"], retorna: [0, 3, "Doji raíz"],
    alto: [3, 3, "Doji cruz"],
  };
  const sig = (kind, body, upper, lower) => ({ kind, body, upper, lower });
  const key = (s) => `${s.kind}${s.body}.${s.upper}.${s.lower}`;
  const same = (a, b) => a && b && key(a) === key(b);

  const QUOTE_OPEN = sig("V", 1, 2, 2), QUOTE_CLOSE = sig("R", 1, 2, 2);
  const FRAME_START = sig("V", 2, 3, 3), FRAME_END = sig("R", 2, 3, 3);
  const OPCODES = {}, INFO = {}, MNEMONIC = {};
  for (const [family, pattern, color, up, low, names] of FAMILIES)
    names.forEach((name, i) => { OPCODES[name] = sig(color, i + 1, up, low); INFO[name] = [family, pattern]; });
  for (const [name, [up, low, pattern]] of Object.entries(DOJIS)) {
    OPCODES[name] = sig("D", 0, up, low); INFO[name] = ["control", pattern];
  }
  for (const [name, s] of Object.entries(OPCODES)) MNEMONIC[key(s)] = name;

  const ALIASES = { muestra: "mostrar", imprime: "mostrar", duplica: "dup", intercambia: "cambia",
    descarta: "quita", repite: "veces", funcion: "define", "función": "define" };
  const STATEMENT_END = new Set(["guarda", "mostrar", "escribe", "salto", "quita", "retorna", "alto", "nada"]);
  const NAME = /^[\p{L}_][\p{L}\p{N}\p{M}_]*$/u;
  const EXPLICIT = /^([vf])(\d+)$/;
  const ESCAPES = { n: "\n", t: "\t", '"': '"', "\\": "\\" };

  class VelaError extends Error {}
  const err = (msg) => { throw new VelaError(msg); };

  const enc = new TextEncoder(), dec = new TextDecoder("utf-8", { fatal: true });
  const digit = (d, first) => sig(first ? "V" : "R", d + 1, 0, 0);
  const numberCandles = (digits) => [...digits].map((d, i) => digit(+d, i === 0));
  function stringCandles(text) {
    const out = [QUOTE_OPEN];
    for (const b of enc.encode(text)) out.push(sig("V", (b >> 4) + 1, 0, 0), sig("R", (b & 15) + 1, 0, 0));
    out.push(QUOTE_CLOSE);
    return out;
  }

  function* tokens(source) {
    const re = /\s+|#[^\n]*|"(?:[^"\\\n]|\\.)*"|[^\s"#]+|"/gsu;
    let line = 1, m;
    while ((m = re.exec(source))) {
      const t = m[0];
      if (t === '"') err(`Línea ${line}: texto sin cerrar.`);
      if (!/^\s+$/.test(t) && !t.startsWith("#")) yield [t, line];
      line += (t.match(/\n/g) || []).length;
    }
  }

  function unescape(lit, line) {
    let out = "";
    for (let i = 1; i < lit.length - 1; i++) {
      if (lit[i] === "\\") {
        const n = lit[i + 1];
        if (!(n in ESCAPES)) err(`Línea ${line}: secuencia de escape desconocida \\${n}.`);
        out += ESCAPES[n]; i++;
      } else out += lit[i];
    }
    return out;
  }

  const canon = (t) => { const l = t.toLowerCase(); return ALIASES[l] || l; };

  function compileListing(source) {
    const toks = [...tokens(source)];
    const functions = new Set();
    toks.forEach(([t], i) => { if (canon(t) === "define" && toks[i + 1]) functions.add(toks[i + 1][0]); });
    const ids = { v: new Map(), f: new Map() }, reserved = { v: new Set(), f: new Set() };
    for (const [t] of toks) {
      const m = EXPLICIT.exec(t.replace(/^=+/, ""));
      if (m) reserved[m[1]].add(+m[2]);
    }
    function ident(space, name, line) {
      if (!NAME.test(name)) err(`Línea ${line}: nombre inválido '${name}'.`);
      if (name.toLowerCase() in OPCODES || name.toLowerCase() in ALIASES) err(`Línea ${line}: '${name}' es una palabra reservada.`);
      const m = EXPLICIT.exec(name);
      let n;
      if (m && m[1] === space) n = +m[2];
      else {
        const table = ids[space];
        if (!table.has(name)) {
          const used = new Set(table.values());
          n = 0;
          while (reserved[space].has(n) || used.has(n)) n++;
          table.set(name, n);
        }
        n = table.get(name);
      }
      return numberCandles(String(n));
    }
    const out = [];
    let pendingDefine = null;
    for (const [t, line] of toks) {
      if (pendingDefine !== null) {
        out.push({ word: `define ${t}`, line, candles: [...ident("f", t, line), OPCODES.define] });
        pendingDefine = null; continue;
      }
      const w = canon(t);
      if (t.startsWith('"')) out.push({ word: t, line, candles: stringCandles(unescape(t, line)) });
      else if (/^-?[0-9]+$/.test(t)) {
        const c = numberCandles(t.replace(/^-/, ""));
        if (t.startsWith("-")) c.push(OPCODES.neg);
        out.push({ word: t, line, candles: c });
      } else if (w === "define") pendingDefine = line;
      else if (w in OPCODES) out.push({ word: w, line, candles: [OPCODES[w]] });
      else if (t.startsWith("=") && t.length > 1) out.push({ word: t, line, candles: [...ident("v", t.slice(1), line), OPCODES.guarda] });
      else if (functions.has(t) || (EXPLICIT.test(t) && t[0] === "f")) out.push({ word: t, line, candles: [...ident("f", t, line), OPCODES.llama] });
      else if (NAME.test(t)) out.push({ word: t, line, candles: [...ident("v", t, line), OPCODES.lee] });
      else err(`Línea ${line}: palabra desconocida '${t}'.`);
    }
    if (pendingDefine !== null) err(`Línea ${pendingDefine}: falta el nombre tras 'define'.`);
    return out;
  }
  const compile = (src) => compileListing(src).flatMap((e) => e.candles);

  function decode(candles) {
    const out = [];
    let i = 0;
    while (i < candles.length) {
      const c = candles[i];
      if (c.upper === 0 && c.lower === 0 && c.kind !== "D") {
        if (c.body < 1 || c.body > 10) err(`Vela ${i}: Marubozu de cuerpo ${c.body} fuera de un texto (máx. 10).`);
        const last = out[out.length - 1];
        if (c.kind === "V") out.push({ op: "num", arg: String(c.body - 1), index: i });
        else if (last && last.op === "num" && last.index + last.arg.length === i) last.arg += String(c.body - 1);
        else err(`Vela ${i}: dígito rojo sin número verde que lo inicie.`);
        i++;
      } else if (same(c, QUOTE_OPEN)) {
        const start = i, bytes = [];
        i++;
        while (i < candles.length && !same(candles[i], QUOTE_CLOSE)) {
          const a = candles[i], b = candles[i + 1];
          if (!b || [a, b].some((p) => p.upper || p.lower || p.body < 1 || p.body > 16) || a.kind !== "V" || b.kind !== "R")
            err(`Vela ${i}: texto mal formado (se esperan parejas verde/roja).`);
          bytes.push(((a.body - 1) << 4) | (b.body - 1));
          i += 2;
        }
        if (i >= candles.length) err(`Vela ${start}: texto sin vela de cierre.`);
        let text;
        try { text = dec.decode(new Uint8Array(bytes)); } catch (e) { err(`Vela ${start}: texto UTF-8 inválido.`); }
        out.push({ op: "txt", arg: text, index: start });
        i++;
      } else if (MNEMONIC[key(c)]) { out.push({ op: MNEMONIC[key(c)], arg: null, index: i }); i++; }
      else err(`Vela ${i}: firma ${c.kind}${c.body}·${c.upper}/${c.lower} sin instrucción asignada.`);
    }
    return out;
  }

  const quote = (t) => '"' + t.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\t/g, "\\t") + '"';

  function disassemble(code) {
    const lines = []; let cur = [], depth = 0;
    const pad = (d) => "    ".repeat(Math.max(d, 0));
    const flush = () => { if (cur.length) { lines.push(pad(depth) + cur.join(" ")); cur = []; } };
    for (let i = 0; i < code.length;) {
      const ins = code[i], nxt = code[i + 1] ? code[i + 1].op : null;
      if (ins.op === "num" && ["guarda", "lee", "llama", "define"].includes(nxt)) {
        const n = BigInt(ins.arg).toString();
        i += 2;
        if (nxt === "define") { flush(); lines.push(pad(depth) + `define f${n}`); depth++; continue; }
        cur.push({ guarda: `=v${n}`, lee: `v${n}`, llama: `f${n}` }[nxt]);
        if (nxt === "guarda") flush();
        continue;
      }
      i++;
      if (ins.op === "num") cur.push(ins.arg);
      else if (ins.op === "txt") cur.push(quote(ins.arg));
      else if (ins.op === "mientras") { flush(); cur.push("mientras"); }
      else if (["si", "hacer", "veces"].includes(ins.op)) { cur.push(ins.op); flush(); depth++; }
      else if (ins.op === "sino") { flush(); lines.push(pad(depth - 1) + "sino"); }
      else if (ins.op === "fin") { flush(); depth = Math.max(depth - 1, 0); lines.push(pad(depth) + "fin"); }
      else { cur.push(ins.op); if (STATEMENT_END.has(ins.op)) flush(); }
    }
    flush();
    return lines.length ? lines.join("\n") + "\n" : "";
  }

  // ------------------------------------------------------------ tramas
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xffffffff;
    for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  const CODES = { V: 0, R: 1, D: 2 };
  const checksum = (cs) => crc32(cs.flatMap((c) => [CODES[c.kind], c.body, c.upper, c.lower])) & 0xffff;

  function frame(cs) {
    const crc = checksum(cs);
    const tail = [0, 1, 2, 3].map((n) => sig(n % 2 ? "R" : "V", ((crc >> (12 - 4 * n)) & 15) + 1, 0, 0));
    return [FRAME_START, ...cs, FRAME_END, ...tail];
  }
  function unframe(cs) {
    const s = cs.findIndex((c) => same(c, FRAME_START));
    if (s < 0) err("No aparece la vela de inicio de trama ⟦.");
    const e = cs.findIndex((c, i) => i > s && same(c, FRAME_END));
    if (e < 0) err("Falta la vela de fin de trama ⟧.");
    const body = cs.slice(s + 1, e), tail = cs.slice(e + 1, e + 5);
    if (tail.length !== 4 || tail.some((t) => t.upper || t.lower || t.body < 1 || t.body > 16)) err("Faltan las 4 velas de control tras ⟧.");
    const crc = tail.reduce((acc, t) => (acc << 4) | (t.body - 1), 0);
    if (crc !== checksum(body)) err("Control CRC incorrecto: el gráfico está alterado o incompleto.");
    return body;
  }
  const messageProgram = (text) => quote(text) + " mostrar\n";

  // ------------------------------------------------------------ geometría
  function ohlc(cs, start = 0) {
    let p = start;
    return cs.map((c) => {
      const close = c.kind === "V" ? p + c.body : c.kind === "R" ? p - c.body : p;
      const bar = [p, Math.max(p, close) + c.upper, Math.min(p, close) - c.lower, close];
      p = close; return bar;
    });
  }
  function signature(o, h, l, c) {
    if (h < Math.max(o, c) || l > Math.min(o, c)) err(`OHLC imposible: ${o}, ${h}, ${l}, ${c}.`);
    return sig(c > o ? "V" : c < o ? "R" : "D", Math.abs(c - o), h - Math.max(o, c), Math.min(o, c) - l);
  }

  /** Etiquetador incremental: nombre de cada vela según su contexto. */
  class Labeler {
    constructor() { this.inText = false; this.crc = 0; }
    next(c) {
      if (this.crc) { this.crc--; return { text: "crc " + (c.body - 1).toString(16).toUpperCase(), role: "crc" }; }
      if (same(c, FRAME_START)) { this.inText = false; return { text: "⟦ inicio", role: "frame" }; }
      if (same(c, FRAME_END)) { this.crc = 4; return { text: "⟧ final", role: "frame" }; }
      if (same(c, QUOTE_OPEN)) { this.inText = true; return { text: "«", role: "txt" }; }
      if (same(c, QUOTE_CLOSE)) { this.inText = false; return { text: "»", role: "txt" }; }
      if (this.inText) return { text: (c.body - 1).toString(16).toUpperCase(), role: "txt" };
      if (!c.upper && !c.lower && c.kind !== "D") return { text: String(c.body - 1), role: "num" };
      const m = MNEMONIC[key(c)];
      return m ? { text: m, role: INFO[m][0] } : { text: "·", role: "ruido" };
    }
  }

  class Receiver {
    constructor() { this.buffer = null; this.tail = 0; }
    push(c) {
      if (same(c, FRAME_START)) { this.buffer = [c]; this.tail = 0; return { state: "inicio" }; }
      if (!this.buffer) return null;
      this.buffer.push(c);
      if (this.tail) {
        if (--this.tail === 0) {
          const got = this.buffer; this.buffer = null;
          try { return { state: "trama", candles: unframe(got) }; }
          catch (e) { return { state: "error", error: e.message }; }
        }
      } else if (same(c, FRAME_END)) this.tail = 4;
      else if (this.buffer.length > 200000) this.buffer = null;
      return { state: "recibiendo", count: this.buffer ? this.buffer.length : 0 };
    }
  }

  // ------------------------------------------------------------ máquina de pila
  const isInt = (v) => typeof v === "bigint";
  const show = (v) => (v === true ? "verdadero" : v === false ? "falso" : String(v));
  const int = (v, op) => { if (!isInt(v)) err(`'${op}' necesita números, recibió '${show(v)}'.`); return v; };
  const text = (v, op) => { if (typeof v !== "string") err(`'${op}' necesita texto, recibió '${show(v)}'.`); return v; };
  const floorDiv = (a, b) => { const q = a / b; return (a % b !== 0n && (a < 0n) !== (b < 0n)) ? q - 1n : q; };
  const floorMod = (a, b) => { const r = a % b; return r !== 0n && (r < 0n) !== (b < 0n) ? r + b : r; };
  function compare(a, b, op) {
    if (op === "==" || op === "!=") return (typeof a === typeof b && a === b) === (op === "==");
    if (!(typeof a === "string" && typeof b === "string")) { int(a, op); int(b, op); }
    return { "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b }[op];
  }
  const truthy = (v) => (isInt(v) ? v !== 0n : Boolean(v));
  const BINARY = {
    "+": (a, b) => (typeof a === "string" || typeof b === "string" ? show(a) + show(b) : int(a, "+") + int(b, "+")),
    "-": (a, b) => int(a, "-") - int(b, "-"),
    "*": (a, b) => {
      if (typeof a === "string") { const n = Number(int(b, "*")); if (a.length * Math.max(n, 0) > 100000) err("Texto demasiado largo."); return a.repeat(Math.max(n, 0)); }
      return int(a, "*") * int(b, "*");
    },
    "/": (a, b) => { int(a, "/"); if (int(b, "/") === 0n) err("División entre cero."); return floorDiv(a, b); },
    "%": (a, b) => { int(a, "%"); if (int(b, "%") === 0n) err("División entre cero."); return floorMod(a, b); },
    "^": (a, b) => { int(a, "^"); if (int(b, "^") < 0n || b > 4096n) err("El exponente debe estar entre 0 y 4096."); return a ** b; },
    "==": (a, b) => compare(a, b, "=="), "!=": (a, b) => compare(a, b, "!="),
    "<": (a, b) => compare(a, b, "<"), ">": (a, b) => compare(a, b, ">"),
    "<=": (a, b) => compare(a, b, "<="), ">=": (a, b) => compare(a, b, ">="),
    y: (a, b) => truthy(a) && truthy(b), o: (a, b) => truthy(a) || truthy(b),
    une: (a, b) => show(a) + show(b),
    letra: (t, i) => {
      const cs = [...text(t, "letra")]; let n = Number(int(i, "letra"));
      if (n < -cs.length || n >= cs.length) err(`'letra' fuera de rango: ${n}.`);
      return cs[n < 0 ? n + cs.length : n];
    },
  };
  const UNARY = {
    neg: (a) => -int(a, "neg"), abs: (a) => (int(a, "abs") < 0n ? -a : a), no: (a) => !truthy(a),
    longitud: (a) => BigInt([...text(a, "longitud")].length),
    caracter: (a) => { const n = Number(int(a, "caracter")); if (n < 0 || n > 0x10ffff) err("Código de carácter fuera de rango."); return String.fromCodePoint(n); },
    codigo: (a) => { if (!text(a, "codigo")) err("'codigo' necesita al menos un carácter."); return BigInt(a.codePointAt(0)); },
    mayusculas: (a) => text(a, "mayusculas").toUpperCase(), minusculas: (a) => text(a, "minusculas").toLowerCase(),
    numero: (a) => {
      if (typeof a === "boolean") return a ? 1n : 0n;
      if (isInt(a)) return a;
      const t = text(a, "numero").trim();
      if (!/^[+-]?\d+$/.test(t)) err(`'${a}' no es un número entero.`);
      return BigInt(t);
    },
    texto: show,
  };

  function matchBlocks(code) {
    const b = { end: {}, opener: {}, otherwise: {}, doo: {}, owner: {} }, st = [];
    code.forEach((ins, i) => {
      const where = `Vela ${ins.index} (${ins.op})`;
      if (["si", "mientras", "veces", "define"].includes(ins.op)) st.push(i);
      else if (ins.op === "sino") {
        const t = st[st.length - 1];
        if (t === undefined || code[t].op !== "si" || t in b.otherwise) err(`${where}: 'sino' sin 'si' abierto.`);
        b.otherwise[t] = i; b.owner[i] = t;
      } else if (ins.op === "hacer") {
        const t = st[st.length - 1];
        if (t === undefined || code[t].op !== "mientras" || t in b.doo) err(`${where}: 'hacer' sin 'mientras' abierto.`);
        b.doo[t] = i; b.owner[i] = t;
      } else if (ins.op === "fin") {
        if (!st.length) err(`${where}: 'fin' sin bloque abierto.`);
        const s = st.pop();
        if (code[s].op === "mientras" && !(s in b.doo)) err(`Vela ${code[s].index}: 'mientras' necesita 'hacer'.`);
        b.end[s] = i; b.opener[i] = s;
      }
    });
    if (st.length) { const ins = code[st[st.length - 1]]; err(`Vela ${ins.index}: falta 'fin' para '${ins.op}'.`); }
    return b;
  }

  function run(code, { inputs = [], maxSteps = 200000 } = {}) {
    if (code.length && "kind" in code[0]) code = decode(code);
    const B = matchBlocks(code), lines = [...inputs];
    const stack = [], vars = new Map(), funcs = new Map(), calls = [], loops = [], out = [];
    let size = 0, steps = 0, pc = 0;
    const pop = () => { if (!stack.length) err("La pila está vacía."); return stack.pop(); };
    const push = (v) => {
      if (stack.length >= 10000) err("Desbordamiento de pila.");
      if (typeof v === "string" && v.length > 100000) err("Texto demasiado largo.");
      if (isInt(v) && (v < 0n ? -v : v).toString(16).length > 25000) err("Número demasiado grande.");
      stack.push(v);
    };
    const write = (t) => { size += t.length; if (size > 50000) err("La salida supera 50 000 caracteres."); out.push(t); };
    const leave = () => { const [ret, depth] = calls.pop(); loops.length = depth; return ret; };
    const result = (halted) => ({ output: out.join(""), stack: stack.map(show), steps, halted });
    while (pc < code.length) {
      const ins = code[pc], op = ins.op;
      let nxt = pc + 1;
      if (++steps > maxSteps) err(`Límite de ${maxSteps} pasos alcanzado; ¿bucle infinito?`);
      try {
        if (op === "num") push(BigInt(ins.arg));
        else if (op === "txt") push(ins.arg);
        else if (op in BINARY) { const b = pop(); push(BINARY[op](pop(), b)); }
        else if (op in UNARY) push(UNARY[op](pop()));
        else switch (op) {
          case "dup": { const v = pop(); push(v); push(v); break; }
          case "quita": pop(); break;
          case "cambia": { const b = pop(), a = pop(); push(b); push(a); break; }
          case "copia": { const b = pop(), a = pop(); push(a); push(b); push(a); break; }
          case "rota": { const c = pop(), b = pop(), a = pop(); push(b); push(c); push(a); break; }
          case "profundidad": push(BigInt(stack.length)); break;
          case "verdadero": case "falso": push(op === "verdadero"); break;
          case "guarda": { const k = int(pop(), "guarda"); vars.set(k, pop()); break; }
          case "lee": { const k = int(pop(), "lee"); if (!vars.has(k)) err(`La variable v${k} no tiene valor.`); push(vars.get(k)); break; }
          case "mostrar": write(show(pop()) + "\n"); break;
          case "escribe": write(show(pop())); break;
          case "salto": write("\n"); break;
          case "entrada": push(lines.length ? lines.shift() : ""); break;
          case "aleatorio": { const n = int(pop(), "aleatorio"); if (n < 1n) err("'aleatorio' necesita un número mayor que 0."); push(BigInt(Math.floor(Math.random() * Number(n)))); break; }
          case "indice": if (loops.length <= (calls.length ? calls[calls.length - 1][1] : 0)) err("'indice' solo funciona dentro de 'veces'."); push(BigInt(loops[loops.length - 1][0])); break;
          case "si": if (!truthy(pop())) nxt = (pc in B.otherwise ? B.otherwise[pc] : B.end[pc]) + 1; break;
          case "sino": nxt = B.end[B.owner[pc]] + 1; break;
          case "hacer": if (!truthy(pop())) nxt = B.end[B.owner[pc]] + 1; break;
          case "veces": { const n = int(pop(), "veces"); if (n > 0n) loops.push([0, Number(n), pc]); else nxt = B.end[pc] + 1; break; }
          case "define": funcs.set(int(pop(), "define"), pc + 1); nxt = B.end[pc] + 1; break;
          case "llama": {
            const k = int(pop(), "llama");
            if (!funcs.has(k)) err(`La función f${k} no está definida.`);
            if (calls.length >= 1000) err("Demasiadas llamadas anidadas.");
            calls.push([pc + 1, loops.length]); nxt = funcs.get(k); break;
          }
          case "retorna": if (!calls.length) return result(true); nxt = leave(); break;
          case "fin": {
            const s = B.opener[pc], kind = code[s].op;
            if (kind === "mientras") nxt = s + 1;
            else if (kind === "veces") { const l = loops[loops.length - 1]; if (++l[0] < l[1]) nxt = s + 1; else loops.pop(); }
            else if (kind === "define" && calls.length) nxt = leave();
            break;
          }
          case "alto": return result(true);
          default: break; // nada, mientras
        }
      } catch (e) {
        if (e instanceof VelaError) err(`Vela ${ins.index} (${op === "num" ? "número" : op === "txt" ? "texto" : op}): ${e.message}`);
        throw e;
      }
      pc = nxt;
    }
    return result(false);
  }

  const api = {
    FAMILIES, DOJIS, OPCODES, INFO, MNEMONIC, QUOTE_OPEN, QUOTE_CLOSE, FRAME_START, FRAME_END,
    VelaError, sig, key, same, compileListing, compile, decode, disassemble, frame, unframe,
    checksum, messageProgram, ohlc, signature, Labeler, Receiver, run, show,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.Vela = api;
})(typeof window !== "undefined" ? window : globalThis);
