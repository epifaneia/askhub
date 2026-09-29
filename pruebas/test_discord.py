import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys, types

falso_store = types.ModuleType("store")
falso_store.get_state = lambda k: ""
falso_store.set_state = lambda k, v: None
sys.modules["store"] = falso_store

from connectors import discord as d

CANALES = [
    {"id": "c1", "type": 4, "name": "Frente Ventas"},
    {"id": "c2", "type": 4, "name": "Frente Producto"},
    {"id": "10", "type": 0, "name": "rediseno", "parent_id": "c1",
     "topic": "Rediseño del portal cliente"},
    {"id": "11", "type": 0, "name": "pricing", "parent_id": "c2"},
    {"id": "12", "type": 0, "name": "general"},
]
HILOS = [{"id": "20", "type": 11, "name": "tarifas 2027", "parent_id": "11",
          "thread_metadata": {"archived": False}}]
MSG = {"id": "1001", "content": "hola", "author": {"username": "dani"},
       "timestamp": "2026-08-23T10:00:00.000Z"}

pedidos = []
def fake_get(client, path, **params):
    pedidos.append(path)
    if path == "/users/@me/guilds": return [{"id": "g1"}]
    if path == "/guilds/g1/channels": return CANALES
    if path == "/guilds/g1/threads/active": return {"threads": HILOS}
    if path.endswith("/messages"):
        return [MSG] if not params.get("before") else []
    return []

class FakeCli:
    def __enter__(self): return self
    def __exit__(self, *a): return False
d._get = fake_get
d._client = lambda: FakeCli()

filas = d.fetch()
por_id = {f["url"].split("/")[-2]: f for f in filas}

ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

chk("no pide mensajes a las categorias",
    not any(p.startswith("/channels/c") for p in pedidos),
    [p for p in pedidos if p.startswith("/channels/c")] or "ninguna")

t10 = por_id["10"]["title"]
chk("canal con categoria y tema",
    t10 == "Frente Ventas › #rediseno (Rediseño del portal cliente)", t10)

t11 = por_id["11"]["title"]
chk("canal con categoria, sin tema", t11 == "Frente Producto › #pricing", t11)

t12 = por_id["12"]["title"]
chk("canal suelto sin categoria", t12 == "#general", t12)

t20 = por_id["20"]["title"]
chk("hilo: categoria > canal > hilo",
    t20 == "Frente Producto › pricing › #tarifas 2027", t20)

chk("la cabecera va DENTRO del texto que se indexa",
    "Frente Ventas" in por_id["10"]["content"], por_id["10"]["content"][:60])

chk("4 canales con mensajes, ni uno mas", len(filas) == 4, f"{len(filas)}")

# un ciclo de parent_id no debe colgar el proceso
ciclo = {"id": "a", "name": "a", "parent_id": "b"}
mapa = {"a": ciclo, "b": {"id": "b", "name": "b", "parent_id": "a"}}
chk("parent_id circular no cuelga", d._ruta(ciclo, mapa) == ["b", "a"], d._ruta(ciclo, mapa))

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
