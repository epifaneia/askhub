import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pathlib, tempfile

import askhub

ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

# --- 1. el .env.example tal cual: lo primero que hace quien clona el repo ----
ej = askhub.leer_env(askhub.BASE / ".env.example")
chk("LLM_BACKEND sin el comentario", ej.get("LLM_BACKEND") == "gemini", ej.get("LLM_BACKEND"))
chk("WHISPER_IDIOMA sin el comentario", ej.get("WHISPER_IDIOMA") == "es", ej.get("WHISPER_IDIOMA"))
chk("numeros convertibles", float(ej["DISCORD_VENTANA_MINUTOS"]) == 1440 and float(ej["BOT_INTERVALO"]) == 5)
chk("GROQ_API_KEY vacia no entra (no se cuela el comentario)", "GROQ_API_KEY" not in ej, ej.get("GROQ_API_KEY"))
chk("GEMINI_API_KEY vacia no entra", "GEMINI_API_KEY" not in ej)

# --- 2. lo que no es comentario se respeta ------------------------------------
with tempfile.TemporaryDirectory() as d:
    f = pathlib.Path(d) / ".env"
    f.write_text('A=http://x/#ancla\nB="con # dentro"\nC=valor   # nota\n# D=no\n', encoding="utf-8")
    v = askhub.leer_env(f)
chk("# pegado al valor no es comentario", v.get("A") == "http://x/#ancla", v.get("A"))
chk("entre comillas, el # es parte del valor", v.get("B") == "con # dentro", v.get("B"))
chk("comentario tras espacio fuera", v.get("C") == "valor", v.get("C"))
chk("linea comentada fuera", "D" not in v)

print("todo bien" if all(ok) else f"{ok.count(False)} fallos")
