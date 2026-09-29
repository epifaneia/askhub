import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, types
os.environ["DISCORD_BOT_TOKEN"] = "x"

fake_askhub = types.ModuleType("askhub")
preguntas = []
fake_askhub.responder = lambda p, historial="", k=14: (preguntas.append(p), f"Respuesta a: {p}")[1]
fake_askhub.sincronizar = lambda solo=None: 0
sys.modules["askhub"] = fake_askhub

import bot

ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

YO = "botid"
enviados = []

def montar(tandas):
    """tandas: listas de mensajes que devuelve cada sondeo consecutivo."""
    estado = {"i": 0}
    def fake_pedir(cli, metodo, ruta, **kw):
        if ruta == "/users/@me": return {"id": YO}
        if ruta.endswith("/typing"): return None
        if metodo == "POST" and ruta.endswith("/messages"):
            enviados.append(kw["json"]); return {"id": "enviado"}
        if metodo == "GET" and ruta.endswith("/messages"):
            if "after" not in (kw.get("params") or {}):
                return [{"id": "100"}]           # el ultimo que ya habia
            i = estado["i"]; estado["i"] += 1
            if i >= len(tandas): raise KeyboardInterrupt
            return tandas[i]
        return None
    return fake_pedir

def msg(mid, texto, autor="dani", aid="u1", es_bot=False):
    return {"id": mid, "content": texto,
            "author": {"id": aid, "username": autor, "bot": es_bot}}

bot.time.sleep = lambda s: None

# --- 1. no contesta al historial previo, si a lo nuevo -------------------
enviados.clear(); preguntas.clear()
bot._pedir = montar([[msg("101", "¿como va el rediseno?")]])
try: bot.escuchar(canal="123", intervalo=0, sync_cada=0)
except KeyboardInterrupt: pass
chk("arranca sin contestar lo anterior", len(preguntas) == 1, f"{len(preguntas)} preguntas")
chk("responde a la nueva", enviados and "rediseno" in enviados[0]["content"])
chk("se engancha al mensaje original",
    enviados[0].get("message_reference", {}).get("message_id") == "101")

# --- 2. ignora sus propios mensajes y otros bots ------------------------
enviados.clear(); preguntas.clear()
bot._pedir = montar([[msg("101", "yo mismo", aid=YO),
                      msg("102", "otro bot", aid="u9", es_bot=True),
                      msg("103", "", aid="u1"),
                      msg("104", "pregunta buena")]])
try: bot.escuchar(canal="123", intervalo=0, sync_cada=0)
except KeyboardInterrupt: pass
chk("ignora lo suyo, otros bots y vacios", preguntas == ["pregunta buena"], str(preguntas))

# --- 3. respuesta larga: troceada bajo el limite ------------------------
enviados.clear()
fake_askhub.responder = lambda p, historial="", k=14: "linea larga de texto " * 400
bot._pedir = montar([[msg("101", "dame algo largo")]])
try: bot.escuchar(canal="123", intervalo=0, sync_cada=0)
except KeyboardInterrupt: pass
chk("trocea por debajo de 2000", all(len(e["content"]) <= 2000 for e in enviados),
    f"{len(enviados)} mensajes, max {max(len(e['content']) for e in enviados)}")
chk("solo el primer trozo cita el original",
    sum(1 for e in enviados if "message_reference" in e) == 1)

# --- 4. una linea sola mas larga que el limite no se pierde -------------
trozos = bot._trocear("x" * 5000)
chk("linea gigante se parte igual", all(len(t) <= 1900 for t in trozos) and
    sum(len(t) for t in trozos) == 5000, f"{len(trozos)} trozos")

# --- 5. si responder() peta, avisa en el canal en vez de morir ----------
enviados.clear()
def explota(p, historial="", k=14): raise RuntimeError("indice corrupto")
fake_askhub.responder = explota
bot._pedir = montar([[msg("101", "algo")]])
try: bot.escuchar(canal="123", intervalo=0, sync_cada=0)
except KeyboardInterrupt: pass
chk("un error no tumba el bot, lo dice en el canal",
    enviados and "indice corrupto" in enviados[0]["content"], enviados[0]["content"][:60] if enviados else "nada")

# --- 6. configuracion ausente: mensajes utiles -------------------------
try:
    bot.escuchar(canal="", intervalo=0, sync_cada=0); chk("sin canal -> aviso", False)
except bot.SinConfigurar as e:
    chk("sin canal -> aviso", "DISCORD_PREGUNTAR_CANAL" in str(e))

del os.environ["DISCORD_BOT_TOKEN"]
try:
    bot._client(); chk("sin token -> aviso", False)
except bot.SinConfigurar as e:
    chk("sin token -> aviso", "DISCORD_BOT_TOKEN" in str(e))

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
