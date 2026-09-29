"""Trello (plan gratuito): tableros y tarjetas, en texto.

Aqui NO se calculan porcentajes a proposito. Un "78%" mezcla numero de items
con cantidad de trabajo, y sobre todo no sabe decir lo mas habitual: que algo
esta en produccion, funcionando, y todavia mejorandose. Eso no es un numero.

Lo que se indexa es lo que esta escrito -- columna, subtareas hechas y
pendientes, descripcion -- y quien interpreta es el modelo. El codigo solo se
encarga de que el material llegue entero.
"""

import json
import os

import httpx

API = "https://api.trello.com/1"
FALTA = "TRELLO_KEY + TRELLO_TOKEN (https://trello.com/power-ups/admin → API key)"

# Proyectos por fragmento de resumen. Suficientes para que una empresa entre
# de una pieza, sin pasarse del tamano que admite un embedding.
POR_RESUMEN = 25



# --- campos del Power-Up "Any Fields" ---------------------------------------
# No es el de Trello, asi que no sale en /customFields: guarda lo suyo en
# pluginData. El formato es simple -- el tablero define [{f: id, n: nombre}] y
# cada tarjeta lleva [{f: id, v: valor}] -- pero es formato ajeno y no
# documentado. Si algun dia cambia, AVISAMOS en vez de devolver nada en
# silencio: perder las urgencias sin enterarse seria peor que un error.
CLAVE_DEFS = "PU_ANY_FIELDS-badge-fields"
CLAVE_VALORES = "PU_ANY_FIELDS-badges"


def _plugin(objeto: dict) -> dict:
    """Junta el pluginData de un objeto en un solo diccionario."""
    fundido = {}
    for d in objeto.get("pluginData") or []:
        valor = d.get("value")
        try:
            if isinstance(valor, str):
                valor = json.loads(valor)
            if isinstance(valor, dict):
                fundido.update(valor)
        except (ValueError, TypeError):
            continue
    return fundido


def _defs_campos(board_plugin: list) -> dict:
    fundido = _plugin({"pluginData": board_plugin})
    defs = {}
    for campo in fundido.get(CLAVE_DEFS) or []:
        if isinstance(campo, dict) and campo.get("f") is not None:
            defs[campo["f"]] = str(campo.get("n") or "campo")
    return defs


def _campos_tarjeta(card: dict, defs: dict) -> list[str]:
    valores = _plugin(card).get(CLAVE_VALORES) or []
    salida = []
    for item in valores:
        if not isinstance(item, dict):
            continue
        texto = str(item.get("v") or "").strip()
        if not texto:
            continue
        nombre = defs.get(item.get("f"))
        if nombre is None:
            # El valor esta pero no sabemos de que campo: se dice, no se tira.
            salida.append(f"campo desconocido: {texto}")
        else:
            salida.append(f"{nombre}: {texto}")
    return salida


def disponible() -> bool:
    return bool(os.environ.get("TRELLO_KEY") and os.environ.get("TRELLO_TOKEN"))


def _auth() -> dict:
    return {"key": os.environ["TRELLO_KEY"], "token": os.environ["TRELLO_TOKEN"]}


def _get(client: httpx.Client, path: str, **params):
    r = client.get(f"{API}{path}", params={**_auth(), **params}, timeout=60.0)
    r.raise_for_status()
    return r.json()


def _etiquetas(card: dict) -> list[str]:
    """Las etiquetas son atributos DEL PROYECTO: estado, prioridad, lo que sea.

    Antes se leian como si fueran la empresa. Pero el ambito es la columna
    -- Cliente A, Cliente B, Investigaciones laterales -- y a una columna nadie le
    pone una urgencia. Confundirlos convertia una etiqueta 'Urgencia: Alta'
    en una empresa inventada.
    """
    return [
        (l.get("name") or "").strip()
        for l in (card.get("labels") or [])
        if (l.get("name") or "").strip()
    ]


def _subtareas(card: dict) -> tuple[list[str], list[str]]:
    hechos, faltan = [], []
    for cl in card.get("checklists") or []:
        for i in cl.get("checkItems") or []:
            (hechos if i.get("state") == "complete" else faltan).append(i.get("name", ""))
    return hechos, faltan


def inventario() -> list[dict]:
    """Tableros con sus tarjetas ya masticadas. Lo usan el indice y `proyectos`."""
    salida = []
    with httpx.Client() as client:
        for board in _get(client, "/members/me/boards", filter="open", fields="name,url"):
            listas = {
                l["id"]: l["name"]
                for l in _get(client, f"/boards/{board['id']}/lists", fields="name")
            }
            cards = _get(
                client,
                f"/boards/{board['id']}/cards",
                fields="name,desc,idList,due,dueComplete,url,labels",
                checklists="all",
                pluginData="true",
            )
            try:
                defs = _defs_campos(_get(client, f"/boards/{board['id']}/pluginData"))
            except httpx.HTTPError:
                defs = {}
            proyectos = []
            for c in cards:
                hechos, faltan = _subtareas(c)
                proyectos.append(
                    {
                        "id": c["id"],
                        "nombre": c.get("name", ""),
                        "url": c.get("url", ""),
                        "columna": listas.get(c.get("idList"), "?"),
                        "etiquetas": _etiquetas(c),
                        "campos": _campos_tarjeta(c, defs),
                        "hechos": hechos,
                        "pendientes": faltan,
                        "vence": (c.get("due") or "")[:10],
                        "desc": (c.get("desc") or "").strip(),
                    }
                )
            salida.append(
                {
                    "id": board["id"],
                    "titulo": board["name"],
                    "url": board.get("url", ""),
                    "proyectos": proyectos,
                }
            )
    return salida


def _texto_tarjeta(p: dict, tablero: str) -> str:
    partes = [
        f"[tablero {tablero}] proyecto: {p['nombre']}",
        f"columna: {p['columna']}",
    ]
    if p["etiquetas"]:
        partes.append("etiquetas: " + " · ".join(p["etiquetas"]))
    if p["campos"]:
        partes.append(" · ".join(p["campos"]))
    if p["vence"]:
        partes.append(f"vence: {p['vence']}")
    if p["hechos"]:
        partes.append("subtareas hechas: " + "; ".join(p["hechos"]))
    if p["pendientes"]:
        partes.append("subtareas pendientes: " + "; ".join(p["pendientes"]))
    if p["desc"]:
        partes.append(p["desc"][:2000])
    return "\n".join(partes)


def _texto_resumen(ambito: str, tablero: str, proyectos: list[dict], parte: str = "") -> str:
    """Todo lo abierto de una empresa en UNA pieza.

    Es lo que evita que "que hay abierto en Cliente A" recupere seis tarjetas de
    quince y el modelo conteste, muy convencido, una lista incompleta.
    """
    cabecera = f"[resumen de {ambito}] proyectos de {ambito} en el tablero {tablero}{parte}"
    lineas = [cabecera]
    for p in proyectos:
        linea = f"- {p['nombre']}"
        marcas = p["etiquetas"] + p["campos"]
        if marcas:
            linea += " [" + " · ".join(marcas) + "]"
        if p["pendientes"]:
            linea += " — pendiente: " + "; ".join(p["pendientes"])
        elif p["hechos"]:
            linea += " — todas las subtareas hechas"
        lineas.append(linea)
    return "\n".join(lineas)


def fetch() -> list[dict]:
    from . import hash_texto

    filas = []
    for b in inventario():
        for p in b["proyectos"]:
            contenido = _texto_tarjeta(p, b["titulo"])
            filas.append(
                {
                    "id": f"trello:card:{p['id']}",
                    "source": "trello",
                    "title": f"{b['titulo']} · {p['nombre']}",
                    "url": p["url"],
                    "content": contenido,
                    "hash": hash_texto(contenido),
                }
            )

        por_ambito: dict[str, list[dict]] = {}
        for p in b["proyectos"]:
            por_ambito.setdefault(p["columna"], []).append(p)

        for empresa, proyectos in sorted(por_ambito.items()):
            trozos = [
                proyectos[i : i + POR_RESUMEN] for i in range(0, len(proyectos), POR_RESUMEN)
            ] or [[]]
            for n, trozo in enumerate(trozos):
                parte = f" (parte {n + 1} de {len(trozos)})" if len(trozos) > 1 else ""
                contenido = _texto_resumen(empresa, b["titulo"], trozo, parte)
                filas.append(
                    {
                        "id": f"trello:empresa:{b['id']}:{empresa}:{n}",
                        "source": "trello",
                        "title": f"{empresa} · resumen",
                        "url": b["url"],
                        "content": contenido,
                        "hash": hash_texto(contenido),
                    }
                )
    return filas
