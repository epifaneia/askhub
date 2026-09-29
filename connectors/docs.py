"""Carpeta local ./docs — todo lo que no vive ni en el chat ni en el tablero."""

import os
import pathlib

CARPETA = pathlib.Path(os.environ.get("DOCS_DIR", "")) if os.environ.get("DOCS_DIR") else (
    pathlib.Path(__file__).resolve().parent.parent / "docs"
)
EXTENSIONES = {".md", ".txt", ".markdown", ".csv", ".json"}
# Documentacion del propio repositorio: vive en docs/ pero no es conocimiento del equipo.
EXCLUIR = {"GUIA.md", "INTEGRATION.md", "INTEGRATION.es.md"}
FALTA = f"nada: suelta ficheros en {CARPETA}"


def disponible() -> bool:
    # Basta con que exista la carpeta: si la vacías, el conector debe seguir
    # activo para poder PURGAR del índice lo que ya no está.
    return CARPETA.exists()


def _partir_largo(bloque: str, tam: int) -> list[str]:
    """Un bloque mas grande que el limite se parte por lineas, y si aun no cabe,
    a lo bruto.

    Sin esto, una transcripcion -- que es un chorro de lineas sin parrafos --
    entraba como UN solo fragmento gigante, y el embedding lo cortaba a 8000
    caracteres sin avisar: el final de cada reunion se perdia en silencio.
    """
    if len(bloque) <= tam:
        return [bloque]
    salida, buf = [], ""
    for linea in bloque.split("\n"):
        while len(linea) > tam:
            salida.append(linea[:tam])
            linea = linea[tam:]
        if len(buf) + len(linea) + 1 > tam and buf:
            salida.append(buf)
            buf = linea
        else:
            buf = f"{buf}\n{linea}" if buf else linea
    if buf:
        salida.append(buf)
    return salida


def _trocear(texto: str, tam: int = 1500) -> list[str]:
    parrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    trozos, buf = [], ""
    for p in parrafos:
        for pieza in _partir_largo(p, tam):
            if len(buf) + len(pieza) + 2 > tam and buf:
                trozos.append(buf)
                buf = pieza
            else:
                buf = f"{buf}\n\n{pieza}" if buf else pieza
    if buf:
        trozos.append(buf)
    return trozos or [texto[:tam]]


def fetch() -> list[dict]:
    from . import hash_texto

    filas = []
    for ruta in sorted(CARPETA.rglob("*")):
        if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES or ruta.name in EXCLUIR:
            continue
        try:
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = ruta.relative_to(CARPETA).as_posix()
        for i, trozo in enumerate(_trocear(texto)):
            contenido = f"[documento {rel}]\n{trozo}"
            filas.append(
                {
                    "id": f"docs:{rel}#{i}",
                    "source": "docs",
                    "title": rel,
                    "url": str(ruta),
                    "content": contenido,
                    "hash": hash_texto(contenido),
                }
            )
    return filas
