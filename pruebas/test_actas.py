import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pathlib, sys, types
import actas

ok = []
def chk(nombre, cond, detalle=""):
    ok.append(bool(cond))
    print(f"[{'PASA' if cond else 'FALLA'}] {nombre}" + (f"  -> {detalle}" if detalle else ""))

# --- 1. troceado ---------------------------------------------------------
corto = "linea\n" * 10
chk("texto corto = 1 trozo", len(actas._trocear(corto)) == 1)
largo = "\n".join(f"[0:00:{i:02d}] frase numero {i} " + "x"*100 for i in range(600))
trozos = actas._trocear(largo, tam=5000)
chk("texto largo se trocea", len(trozos) > 5, f"{len(trozos)} trozos")
chk("ningun trozo pasa del limite", all(len(t) <= 5000 for t in trozos), f"max={max(len(t) for t in trozos)}")
chk("no se pierde texto", sum(len(t) for t in trozos) + len(trozos) - 1 == len(largo))

# --- 2. slug -------------------------------------------------------------
chk("slug con acentos y signos", actas._slug("Reunión semanal: ¿qué tal?") == "reunión-semanal-qué-tal",
    actas._slug("Reunión semanal: ¿qué tal?"))
chk("slug vacio no rompe", actas._slug("¿¡!?") == "reunion", actas._slug("¿¡!?"))

# --- 3. redactar con un LLM falso (map-reduce) ---------------------------
llamadas = []
falso = types.ModuleType("llm")
falso.generar = lambda prompt, max_tokens=1500: (llamadas.append(prompt), "## Resumen\nAlgo.")[1]
sys.modules["llm"] = falso

llamadas.clear()
actas.redactar("corta")
chk("transcripcion corta = 1 llamada", len(llamadas) == 1, f"{len(llamadas)}")

llamadas.clear()
actas.redactar(largo)
chk("transcripcion larga = parciales + unificacion", len(llamadas) >= 3, f"{len(llamadas)} llamadas")
chk("la ultima llamada unifica", "actas parciales" in llamadas[-1])

# --- 4. guardar ----------------------------------------------------------
ra, rt = actas.guardar("## Resumen\nProbando.", "[0:00:00] hola", "Prueba de acta", "2026-08-23")
chk("acta cae dentro de docs/ (se indexa)", "docs" in ra.parts and ra.exists(), str(ra))
chk("la transcripcion se guarda pero fuera del indice",
    "docs" not in rt.parts and rt.exists(), str(rt))
chk("y va en carpeta aparte del acta", rt.parent != ra.parent, f"{rt.parent.name} vs {ra.parent.name}")
chk("el acta lleva titulo y fecha", "# Prueba de acta" in ra.read_text(encoding="utf-8"))

# --- 5. el conector de docs la ve ---------------------------------------
import connectors.docs as docs
filas = docs.fetch()
chk("el conector docs indexa el acta", any("actas/2026-08-23" in f["id"] for f in filas),
    f"{len(filas)} fragmentos")

# --- 6. publicar en Discord: troceado a 2000 y errores -------------------
enviados = []
class FakeResp:
    def __init__(self, code): self.status_code = code
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")
class FakeCli:
    codigo = 200
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def post(self, url, json=None):
        enviados.append(json["content"]); return FakeResp(FakeCli.codigo)
actas.httpx = types.SimpleNamespace(Client=FakeCli)

import os
os.environ["DISCORD_BOT_TOKEN"] = "x"
acta_larga = "parrafo bla bla bla. " * 500
actas.publicar_discord(acta_larga, "Semanal", "2026-08-23", canal="123")
chk("trocea por debajo del limite de Discord", all(len(m) <= 2000 for m in enviados),
    f"{len(enviados)} mensajes, max {max(len(m) for m in enviados)}")
chk("no pierde contenido al trocear", "".join(enviados).count("bla") == acta_larga.count("bla"))

try:
    actas.publicar_discord("x", "t", "f", canal="")
    chk("sin canal -> error claro", False)
except RuntimeError as e:
    chk("sin canal -> error claro", "DISCORD_ACTAS_CANAL" in str(e))

enviados.clear(); FakeCli.codigo = 403
try:
    actas.publicar_discord("x", "t", "f", canal="123")
    chk("403 -> mensaje util", False)
except RuntimeError as e:
    chk("403 -> mensaje util", "Enviar mensajes" in str(e), str(e)[:60])

# --- 7. sin faster-whisper: aviso util, no traceback ---------------------
_guardado = sys.modules.get("faster_whisper")
sys.modules["faster_whisper"] = None  # fuerza el ImportError aunque este instalado
try:
    actas.transcribir(pathlib.Path("noexiste.flac"))
    chk("sin whisper -> instrucciones", False)
except RuntimeError as e:
    chk("sin whisper -> instrucciones", "pip install faster-whisper" in str(e))
finally:
    if _guardado is None:
        sys.modules.pop("faster_whisper", None)
    else:
        sys.modules["faster_whisper"] = _guardado

# limpieza
ra.unlink(); rt.unlink()

# --- 8. vocabulario para Whisper ----------------------------------------
import sqlite3, tempfile
tmp = pathlib.Path(tempfile.mkdtemp()) / "v.db"
cx = sqlite3.connect(tmp)
cx.execute("create table chunks (source text, title text)")
cx.executemany("insert into chunks values (?,?)", [
    ("trello", "AI Working Group  ·  Reqif"),
    ("trello", "sin empresa  ·  resumen"),
    ("trello", "AI Working Group  ·  CTSM"),
    ("discord", "no deberia salir de aqui"),
])
cx.commit(); cx.close()
sys.modules["store"] = types.SimpleNamespace(DB_PATH=str(tmp))
actas.VOCABULARIO = "Ana, Polarion"
v = actas._vocabulario()
chk("mete los proyectos del tablero", "Reqif" in v and "CTSM" in v, v)
chk("mete lo del .env", "Ana" in v and "Polarion" in v)
chk("no cuela 'resumen' ni 'sin empresa'",
    "resumen" not in v and "sin empresa" not in v, v)
chk("no coge titulos que no son de trello", "no deberia salir" not in v)

sys.modules["store"] = types.SimpleNamespace(DB_PATH="/no/existe.db")
chk("sin indice no revienta, tira del .env", "Ana" in actas._vocabulario())

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
