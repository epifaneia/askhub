import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["LLM_REINTENTOS"] = "4"
import llm

ESTADO = {"n": 0, "modo": ""}

class H(BaseHTTPRequestHandler):
    # HTTP/1.1 con Content-Length correcto: sin esto el servidor cierra la
    # conexion tras cada respuesta, httpx reutiliza una ya muerta, _post lo
    # ve como error de red y reintenta -- y el caso del 401 contaba dos
    # peticiones una de cada seis veces. Era el andamio, no la logica.
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        ESTADO["n"] += 1
        n, modo = ESTADO["n"], ESTADO["modo"]
        if modo == "429_luego_ok" and n < 3:
            cuerpo = {"error": {"details": [{"retryDelay": "1s"}]}}
            self.send_response(429); self._json(cuerpo); return
        if modo == "429_siempre":
            self.send_response(429); self._json({"error": {"details": [{"retryDelay": "1s"}]}}); return
        if modo == "500_luego_ok" and n < 2:
            self.send_response(500); self._json({"error": "boom"}); return
        if modo == "401":
            self.send_response(401); self._json({"error": "clave mala"}); return
        self.send_response(200); self._json({"ok": True, "intentos": n})
    def _json(self, c):
        b = json.dumps(c).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

srv = ThreadingHTTPServer(("127.0.0.1", 8731), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:8731/x"

def caso(nombre, modo, esperado):
    ESTADO["n"] = 0; ESTADO["modo"] = modo
    t0 = time.time()
    try:
        r = llm._post(URL, aviso="test", json={}, timeout=10.0)
        res = f"OK tras {ESTADO['n']} intento(s)"
    except llm.CuotaAgotada as e:
        res = f"CuotaAgotada tras {ESTADO['n']} intentos"
    except Exception as e:
        res = f"{type(e).__name__} tras {ESTADO['n']} intento(s)"
    ok = "PASA" if esperado in res else "FALLA"
    print(f"[{ok}] {nombre:34} -> {res}  ({time.time()-t0:.1f}s)")
    return ok == "PASA"

todo = [
    caso("429 dos veces, luego 200", "429_luego_ok", "OK tras 3"),
    caso("429 siempre -> CuotaAgotada", "429_siempre", "CuotaAgotada tras 4"),
    caso("500 una vez, luego 200", "500_luego_ok", "OK tras 2"),
    caso("401 -> falla ya, sin reintentar", "401", "HTTPStatusError tras 1"),
]
print("\nRESULTADO:", "todo bien" if all(todo) else "HAY FALLOS")
