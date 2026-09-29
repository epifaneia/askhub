import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import types
from connectors import trello as t

ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

def card(cid, nombre, columna="Doing", labels=(), hechos=(), faltan=(), desc=""):
    return {"id": cid, "name": nombre, "idList": columna, "url": f"http://t/{cid}",
            "desc": desc, "due": "",
            "labels": [{"name": l} for l in labels],
            "checklists": [{"checkItems":
                [{"name": h, "state": "complete"} for h in hechos] +
                [{"name": f, "state": "incomplete"} for f in faltan]}]}

CARDS = [
    card("1", "Compliance matrix", "L1", ["ACME"], ["lista actualizada"], ["revisar latencia"]),
    card("2", "ACME_Procedimientos cyber", "L2"),
    card("3", "Migracion ERP", "L1", ["GLOBEX"], ["fase 1"], [],
         desc="En PROD y funcionando, iterando optimizacion"),
    card("4", "Cosa suelta", "L2"),
]
DEFS = [{"value": '{"PU_ANY_FIELDS-badge-fields":[{"f":16203,"n":"Urgency"},{"f":16204,"n":"Current State"}]}'}]

def fake_get(cli, path, **params):
    if path == "/members/me/boards": return [{"id": "b1", "name": "Proyectos", "url": "http://b"}]
    if path.endswith("/pluginData"): return DEFS
    if path.endswith("/lists"): return [{"id": "L1", "name": "Doing"}, {"id": "L2", "name": "To Do"}]
    if path.endswith("/cards"): return CARDS
    return []
class C:
    def __enter__(self): return self
    def __exit__(self, *a): return False
t._get = fake_get
t.httpx = types.SimpleNamespace(Client=lambda: C())

filas = t.fetch()
texto = {f["id"]: f["content"] for f in filas}

# --- nada de porcentajes ------------------------------------------------
chk("no se cuela ningun porcentaje", not any("%" in f["content"] for f in filas),
    [f["id"] for f in filas if "%" in f["content"]] or "limpio")

# --- las subtareas van literales ---------------------------------------
c1 = texto["trello:card:1"]
chk("subtareas hechas, literales", "lista actualizada" in c1)
chk("subtareas pendientes, literales", "revisar latencia" in c1)
chk("la columna se indexa", "columna: Doing" in c1, c1.split(chr(10))[1])

# --- el matiz de la descripcion sobrevive ------------------------------
chk("'en PROD, iterando' llega al indice",
    "iterando optimizacion" in texto["trello:card:3"])

# --- etiquetas: atributos del proyecto, NO la empresa --------------------
chk("la etiqueta se indexa como etiqueta", "etiquetas: ACME" in c1, c1)
chk("no se inventa una empresa con ella", "empresa:" not in c1)

CARDS.append(card("5", "Con urgencia", "L1", ["Urgencia: Alta", "Estado: Bloqueado"]))
filas_u = t.fetch()
cu = {f["id"]: f["content"] for f in filas_u}["trello:card:5"]
chk("una etiqueta clave:valor no crea un ambito fantasma",
    not any("Urgencia" in f["title"] and "resumen" in f["title"] for f in filas_u),
    [f["title"] for f in filas_u if "resumen" in f["title"]])
chk("y viaja entera al indice",
    "Urgencia: Alta" in cu and "Estado: Bloqueado" in cu, cu.splitlines()[2])
CARDS.pop()

# --- el ambito es la columna --------------------------------------------
resumenes = {f["title"]: f["content"] for f in t.fetch() if "resumen" in f["title"]}
chk("hay un resumen por columna", set(resumenes) == {"Doing · resumen", "To Do · resumen"},
    str(sorted(resumenes)))
r = resumenes["Doing · resumen"]
chk("el resumen lista los proyectos de esa columna",
    "Compliance matrix" in r and "Migracion ERP" in r, r)
chk("y arrastra lo pendiente", "revisar latencia" in r)
chk("el resumen muestra las etiquetas de cada proyecto", "[ACME]" in r, r)

# --- troceado de empresas con muchos proyectos -------------------------
t.POR_RESUMEN = 2
filas2 = t.fetch()
partes = [f for f in filas2 if f["title"] == "Doing · resumen"]
chk("una columna con muchos proyectos se trocea sin perder ninguno",
    len(partes) == 1 or all("parte" in p["content"] for p in partes), f"{len(partes)} parte(s)")
t.POR_RESUMEN = 25

# --- el hash cambia si cambia el contenido -----------------------------
h1 = {f["id"]: f["hash"] for f in t.fetch()}
CARDS[0]["checklists"][0]["checkItems"].append({"name": "nuevo hito", "state": "incomplete"})
h2 = {f["id"]: f["hash"] for f in t.fetch()}
chk("anadir una subtarea cambia el hash", h1["trello:card:1"] != h2["trello:card:1"])
chk("y no toca las demas", h1["trello:card:3"] == h2["trello:card:3"])


# --- campos del Power-Up Any Fields --------------------------------------
def con_campos(cid, nombre, pares):
    c = card(cid, nombre, "L1")
    c["pluginData"] = [{"value": json.dumps(
        {"PU_ANY_FIELDS-badges": [{"f": f, "v": v} for f, v in pares]})}]
    return c

import json
CARDS.append(con_campos("9", "Reqif", [(16203, "Non urgent"), (16204, "In progress")]))
f9 = {x["id"]: x["content"] for x in t.fetch()}["trello:card:9"]
chk("traduce el id del campo a su nombre", "Urgency: Non urgent" in f9, f9)
chk("y el segundo campo tambien", "Current State: In progress" in f9)

resu = {x["title"]: x["content"] for x in t.fetch() if "resumen" in x["title"]}
chk("los campos salen tambien en el resumen",
    "Non urgent" in resu["Doing · resumen"], resu["Doing · resumen"])

# valor cuyo campo no esta definido: se dice, no se tira
CARDS[-1]["pluginData"] = [{"value": json.dumps(
    {"PU_ANY_FIELDS-badges": [{"f": 99999, "v": "Urgente"}]})}]
f9b = {x["id"]: x["content"] for x in t.fetch()}["trello:card:9"]
chk("un campo desconocido se avisa, no se pierde",
    "campo desconocido: Urgente" in f9b, f9b)

# si el plugin cambia de formato, no debe reventar el sync entero
CARDS[-1]["pluginData"] = [{"value": "esto ya no es json"}]
try:
    f9c = {x["id"]: x["content"] for x in t.fetch()}["trello:card:9"]
    chk("formato roto no tumba el conector", "proyecto: Reqif" in f9c)
except Exception as e:
    chk("formato roto no tumba el conector", False, f"{type(e).__name__}: {e}")

CARDS[-1]["pluginData"] = [{"value": json.dumps({"otra-cosa": [1, 2]})}]
f9d = {x["id"]: x["content"] for x in t.fetch()}["trello:card:9"]
chk("pluginData de otro power-up se ignora sin ruido",
    "Urgency" not in f9d and "campo desconocido" not in f9d, f9d)
CARDS.pop()

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
