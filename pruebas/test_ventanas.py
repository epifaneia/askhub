import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import datetime as dt, sys, types

guardado = {}
fs = types.ModuleType("store")
fs.get_state = lambda k: ""
fs.set_state = lambda k, v: guardado.__setitem__(k, v)
sys.modules["store"] = fs
from connectors import discord as d

AHORA = dt.datetime.now(dt.timezone.utc)
ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

def m(mid, texto, min_atras, autor="dani"):
    return {"id": str(mid), "content": texto,
            "author": {"username": autor},
            "timestamp": (AHORA - dt.timedelta(minutes=min_atras)).isoformat()}

def correr(mensajes):
    CAN = [{"id": "c1", "type": 4, "name": "Empresa A"},
           {"id": "10", "type": 0, "name": "general", "parent_id": "c1"}]
    def fake_get(cli, path, **params):
        if path == "/users/@me/guilds": return [{"id": "g1"}]
        if path == "/guilds/g1/channels": return CAN
        if path == "/guilds/g1/threads/active": return {"threads": []}
        if path.endswith("/messages"):
            return list(reversed(mensajes)) if not params.get("before") else []
        return []
    class C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    d._get, d._client = fake_get, lambda: C()
    guardado.clear()
    return d.fetch()

# --- 1. conversacion seguida = UN fragmento ------------------------------
filas = correr([m(101, "hola", 200), m(102, "que tal", 199), m(103, "bien", 198)])
chk("3 mensajes seguidos = 1 fragmento", len(filas) == 1, f"{len(filas)}")
chk("el id es el del primer mensaje", filas[0]["id"] == "discord:101", filas[0]["id"])
chk("la cabecera aparece UNA vez",
    filas[0]["content"].count("[canal") == 1, filas[0]["content"].count("[canal"))
chk("estan los tres, en orden",
    filas[0]["content"].index("hola") < filas[0]["content"].index("que tal") < filas[0]["content"].index("bien"))

# --- 2. silencio largo = dos conversaciones -----------------------------
filas = correr([m(101, "anteayer", 4000), m(102, "sigo", 3999),
                m(201, "hoy", 100)])
chk("un silencio de dias parte en 2", len(filas) == 2, f"{len(filas)}")
chk("cada una con su id", {f["id"] for f in filas} == {"discord:101", "discord:201"})

# --- 3. conversacion muy larga se parte por tamano ----------------------
largos = [m(300 + i, "palabra " * 60, 4000 - i) for i in range(10)]
filas = correr(largos)
chk("una charla larga se trocea", len(filas) > 1, f"{len(filas)} fragmentos")
chk("ningun fragmento se desmadra",
    max(len(f["content"]) for f in filas) < 3000,
    f"max {max(len(f['content']) for f in filas)}")

# --- 4. mensajes vacios no rompen ni cuentan ----------------------------
filas = correr([m(101, "algo", 200), m(102, "   ", 199), m(103, "mas", 198)])
chk("los vacios se ignoran sin partir nada",
    len(filas) == 1 and filas[0]["content"].count("dani (") == 2,
    f"{len(filas)} frag, {filas[0]['content'].count('dani (')} lineas")

# --- 5. cursor: conversacion viva -> se retrocede -----------------------
filas = correr([m(500, "hace un rato", 300), m(600, "ahora mismo", 2)])
chk("a 5h de distancia siguen siendo la misma charla", len(filas) == 1, f"{len(filas)}")
chk("con charla viva, el cursor retrocede a su inicio",
    guardado.get("discord_cursor_10") == "499", guardado.get("discord_cursor_10"))

# --- 6. cursor: todo antiguo -> avanza del todo -------------------------
filas = correr([m(500, "viejo", 4000), m(600, "tambien viejo", 3999)])
chk("sin charla viva, el cursor avanza al ultimo",
    guardado.get("discord_cursor_10") == "600", guardado.get("discord_cursor_10"))

# --- 7. releer sin cambios no reembebe (mismo hash) ---------------------
a = correr([m(101, "hola", 200), m(102, "que tal", 199)])
b = correr([m(101, "hola", 200), m(102, "que tal", 199)])
chk("mismo contenido -> mismo hash (no se reembebe)", a[0]["hash"] == b[0]["hash"])
c = correr([m(101, "hola", 200), m(102, "que tal", 199), m(103, "y uno mas", 198)])
chk("si la ventana crece, el hash cambia (se reembebe una vez)",
    c[0]["hash"] != a[0]["hash"] and c[0]["id"] == a[0]["id"])

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
