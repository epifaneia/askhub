import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pathlib, tempfile
import connectors.docs as docs

ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

# --- una transcripcion es un chorro de lineas, sin parrafos --------------
lineas = "\n".join(f"[0:{i//60:02d}:{i%60:02d}] frase numero {i} con relleno " + "x"*40
                   for i in range(400))
tr = docs._trocear(lineas, tam=1500)
chk("una transcripcion larga se trocea", len(tr) > 20, f"{len(tr)} fragmentos")
chk("ninguno pasa del limite", max(len(t) for t in tr) <= 1500, f"max {max(len(t) for t in tr)}")
chk("ninguno supera el corte de 8000 del embedding", max(len(t) for t in tr) < 8000)
juntos = "".join(t.replace("\n", "") for t in tr)
chk("no se pierde texto por el camino",
    juntos == lineas.replace("\n", ""), f"{len(juntos)} vs {len(lineas.replace(chr(10),''))}")
chk("se conserva el final de la reunion", "frase numero 399" in tr[-1], tr[-1][-40:])

# --- una sola linea gigantesca ------------------------------------------
g = docs._trocear("y" * 7000, tam=1500)
chk("una linea gigante se parte a lo bruto", len(g) == 5 and max(len(x) for x in g) <= 1500,
    f"{len(g)} trozos")
chk("y tampoco pierde nada", sum(len(x) for x in g) == 7000)

# --- lo de siempre sigue funcionando ------------------------------------
doc = "Primer parrafo corto.\n\nSegundo parrafo.\n\nTercero."
chk("un documento normal no se fragmenta de mas", len(docs._trocear(doc, tam=1500)) == 1)
chk("y conserva la separacion de parrafos", "\n\n" in docs._trocear(doc, tam=1500)[0])
chk("texto vacio no revienta", docs._trocear("", tam=1500) == [""])

# --- la transcripcion cae dentro de docs/ y el conector la ve ------------
import actas
chk("por defecto la transcripcion NO se indexa (el resumen ya recoge las ideas)",
    not actas.INDEXAR_TRANSCRIPCIONES)
chk("y vive fuera de docs/, pero se guarda igual",
    "docs" not in actas.DIR_TRANSCRIPCIONES.parts, str(actas.DIR_TRANSCRIPCIONES))

tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "acta.txt").write_text(lineas, encoding="utf-8")
docs.CARPETA = tmp
filas = docs.fetch()
chk("el conector la parte en varios fragmentos", len(filas) > 20, f"{len(filas)} fragmentos")
chk("cada fragmento sabe de que fichero viene",
    all("[documento acta.txt]" in f["content"] for f in filas))
chk("los ids no se repiten", len({f["id"] for f in filas}) == len(filas))

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
