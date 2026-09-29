import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pathlib, tempfile, types, wave, zipfile
import actas

ok = []
def chk(n, c, det=""):
    ok.append(bool(c)); print(f"[{'PASA' if c else 'FALLA'}] {n}" + (f"  -> {det}" if det else ""))

tmp = pathlib.Path(tempfile.mkdtemp())

# --- troceo de audio -----------------------------------------------------
wav = tmp / "largo.wav"
w = wave.open(str(wav), "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
w.writeframes(b"\x00\x01" * 2 * 44100 * 130)   # 130 s en estereo a 44,1 kHz
w.close()

trozos = actas._trocear_audio(wav, minutos=1)
chk("un audio largo se parte", len(trozos) == 3, f"{len(trozos)} trozos de 1 min sobre 130 s")
chk("los desfases son correlativos",
    [round(d) for _, d in trozos] == [0, 60, 120], [round(d) for _, d in trozos])
c = wave.open(str(trozos[0][0])); par = (c.getnchannels(), c.getframerate(), c.getsampwidth())
dur0 = c.getnframes() / c.getframerate(); c.close()
chk("se convierte a 16 kHz mono 16 bits", par == (1, 16000, 2), str(par))
chk("cada trozo dura lo pedido", abs(dur0 - 60) < 1.5, f"{dur0:.1f}s")
ult = wave.open(str(trozos[-1][0])); durn = ult.getnframes() / 16000; ult.close()
chk("no se pierde audio al final", abs(durn - 10) < 1.5, f"ultimo trozo {durn:.1f}s")
mb = trozos[0][0].stat().st_size / 1e6
chk("un trozo entra en el limite de 25 MB de Groq", mb < 25, f"{mb:.1f} MB/min")

# --- Groq: sin clave, aviso util ----------------------------------------
actas.GROQ_KEY = ""
try:
    actas._transcribir_groq(wav, "")
    chk("sin clave -> aviso", False)
except RuntimeError as e:
    chk("sin clave -> aviso con enlace", "console.groq.com" in str(e))

# --- Groq: recompone las marcas de tiempo entre trozos -------------------
actas.GROQ_KEY = "x"
actas.MINUTOS_TROZO = 1  # para que el fichero de prueba genere varios trozos
enviados = []
class R:
    status_code = 200
    def raise_for_status(self): pass
    def json(self): return {"segments": [{"start": 5.0, "text": "hola"}]}
def fake_post(url, headers=None, files=None, timeout=None):
    enviados.append(files); return R()
actas.httpx = types.SimpleNamespace(post=fake_post)
t = actas._transcribir_groq(wav, "Reqif, Ana")
chk("una llamada por trozo", len(enviados) == 3, f"{len(enviados)} llamadas")
chk("el vocabulario viaja como prompt",
    any("Reqif" in (f.get("prompt") or (None, ""))[1] for f in enviados))
chk("las marcas se desplazan por trozo",
    "[0:00:05]" in t and "[0:01:05]" in t, t.splitlines()[:2])

# --- transcripciones ya hechas ------------------------------------------
vtt = tmp / "teams.vtt"
vtt.write_text("WEBVTT\n\n1\n00:00:03.500 --> 00:00:07.000\n<v Ana>Esto viene de Teams\n",
               encoding="utf-8")
chk("lee un .vtt de Teams", actas._leer_transcripcion(vtt) == "[00:00:03] Esto viene de Teams",
    actas._leer_transcripcion(vtt))

txt = tmp / "tldv.txt"
txt.write_text("Daniel: hola\nAna: que tal", encoding="utf-8")
chk("lee un .txt tal cual", "Daniel: hola" in actas._leer_transcripcion(txt))

docx = tmp / "t.docx"
with zipfile.ZipFile(docx, "w") as z:
    z.writestr("word/document.xml",
        "<w:document><w:body><w:p><w:r><w:t>Acta de Teams</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Segunda l&amp;nea</w:t></w:r></w:p></w:body></w:document>")
d = actas._leer_transcripcion(docx)
chk("lee un .docx sin dependencias", "Acta de Teams" in d and "Segunda l&nea" in d, repr(d))

# --- mezcla de pistas: audio y texto conviven ---------------------------
llamadas = []
actas.transcribir = lambda r, progreso=None: llamadas.append(r) or "AUDIO TRANSCRITO"
mezcla = actas.transcribir_varias([txt, wav])
chk("no transcribe lo que ya es texto", len(llamadas) == 1, f"{len(llamadas)} llamadas a STT")
chk("etiqueta cada pista con su hablante",
    "### Pista de tldv" in mezcla and "### Pista de largo" in mezcla)
chk("mete el texto ya hecho sin tocarlo", "Daniel: hola" in mezcla)


# --- ficheros multipista (OBS: micro y escritorio en el mismo mkv) -------
import numpy as np, av
mkv = tmp / "obs.mkv"
sal = av.open(str(mkv), mode="w")
fl = [sal.add_stream("pcm_s16le", rate=16000, layout="mono") for _ in range(2)]
for i, f in enumerate(fl):
    tono = (np.sin(2*np.pi*(220*(i+1))*np.arange(16000*5)/16000) * 8000).astype(np.int16)
    cu = av.AudioFrame.from_ndarray(tono.reshape(1, -1), format="s16", layout="mono")
    cu.rate = 16000
    for pq in f.encode(cu): sal.mux(pq)
for f in fl:
    for pq in f.encode(None): sal.mux(pq)
sal.close()

chk("detecta las dos pistas", actas._num_pistas(mkv) == 2, actas._num_pistas(mkv))
chk("un wav normal cuenta como una", actas._num_pistas(wav) == 1)
chk("un fichero de texto no revienta la deteccion", actas._num_pistas(txt) == 1)

sueltas = actas._extraer_pistas(mkv, ["Ana", "Daniel"])
chk("saca un fichero por pista", len(sueltas) == 2, [f.name for f in sueltas])
chk("los nombra con el hablante en orden",
    [f.name for f in sueltas] == ["1-ana.wav", "2-daniel.wav"], [f.name for f in sueltas])
import wave as _w
d = [_w.open(str(f)).getnframes()/16000 for f in sueltas]
chk("cada pista conserva su duracion", all(abs(x - 5) < 0.3 for x in d), [round(x,2) for x in d])

def _dif(f):
    c = _w.open(str(f)); import numpy as _np
    a = _np.frombuffer(c.readframes(c.getnframes()), dtype=_np.int16); c.close()
    return int(_np.abs(_np.diff(a.astype(int))).mean())
chk("las pistas son distintas (no se ha duplicado una)", _dif(sueltas[0]) != _dif(sueltas[1]),
    [_dif(f) for f in sueltas])

sin_nombres = actas._extraer_pistas(mkv, [])
chk("sin --hablantes usa nombres genericos",
    [f.name for f in sin_nombres] == ["1-pista1.wav", "2-pista2.wav"], [f.name for f in sin_nombres])

llamadas2 = []
actas.transcribir = lambda r, progreso=None: llamadas2.append(r.stem) or f"texto de {r.stem}"
mezcla2 = actas.transcribir_varias([mkv], hablantes=["Ana", "Daniel"])
chk("un mkv de dos pistas se abre en dos voces", len(llamadas2) == 2, llamadas2)
chk("y cada una queda etiquetada",
    "### Pista de ana" in mezcla2 and "### Pista de daniel" in mezcla2, mezcla2[:120])


# --- alucinaciones de Whisper sobre el silencio final --------------------
def seg(t, lp, ns=0.0):
    return {"text": t, "avg_logprob": lp, "no_speech_prob": ns, "start": 0}

real = [seg("hola que tal", -0.08), seg("pues bien", -0.10), seg("vale", -0.09)]

buenos, fuera = actas._sin_alucinaciones(real + [seg("Gracias por ver el video", -0.59)])
chk("tira la alucinacion del final", fuera == 1 and len(buenos) == 3, f"fuera={fuera}")

buenos, fuera = actas._sin_alucinaciones(
    real + [seg("subtitulos por la comunidad", -0.62), seg("Gracias por ver", -0.71)])
chk("tira varias seguidas si las hay", fuera == 2, f"fuera={fuera}")

medio = [seg("hola", -0.08), seg("(alguien habla flojo)", -0.75), seg("cerramos", -0.09)]
buenos, fuera = actas._sin_alucinaciones(medio)
chk("NO tira un bajon en mitad de la reunion", fuera == 0 and len(buenos) == 3, f"fuera={fuera}")

buenos, fuera = actas._sin_alucinaciones(real + [seg("mmm", -0.09, ns=0.9)])
chk("tira lo marcado como silencio aunque puntue bien", fuera == 1, f"fuera={fuera}")

buenos, fuera = actas._sin_alucinaciones([seg("unica frase", -0.9)])
chk("con un solo segmento no se toca nada", fuera == 0 and len(buenos) == 1)

buenos, fuera = actas._sin_alucinaciones(real)
chk("una grabacion limpia no pierde nada", fuera == 0 and len(buenos) == 3)

malo = [seg("audio ruidoso", -0.70), seg("se oye regular", -0.74), seg("pero es real", -0.72)]
buenos, fuera = actas._sin_alucinaciones(malo)
chk("en audio malo entero no se carga el final (umbral relativo, no fijo)",
    fuera == 0, f"fuera={fuera}")

buenos, fuera = actas._sin_alucinaciones([seg("   ", -0.1)] + real)
chk("los vacios no cuentan", len(buenos) == 3 and fuera == 0)


# --- fecha: de la grabacion, no de cuando se procesa ---------------------
import datetime, os, types as _t

def toca(nombre, dias_atras=None):
    f = tmp / nombre
    f.write_bytes(b"x")
    if dias_atras is not None:
        t = (datetime.datetime.now() - datetime.timedelta(days=dias_atras)).timestamp()
        os.utime(f, (t, t))
    return f

hoy = datetime.date.today().isoformat()

f = toca("2026-03-15 18-30-15.mkv", dias_atras=1)
chk("fecha desde el nombre estilo OBS", actas.fecha_grabacion(f) == "2026-03-15",
    actas.fecha_grabacion(f))

f = toca("reunion_2026_04_02.mkv", dias_atras=1)
chk("y con guiones bajos", actas.fecha_grabacion(f) == "2026-04-02", actas.fecha_grabacion(f))

f = toca("semanal.mkv", dias_atras=5)
esperada = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
chk("sin fecha en el nombre, la del fichero", actas.fecha_grabacion(f) == esperada,
    actas.fecha_grabacion(f))
chk("y NO la de hoy", actas.fecha_grabacion(f) != hoy)

f = toca("v2 del 2026-13-45 raro.mkv", dias_atras=3)
chk("una fecha imposible en el nombre no cuela",
    actas.fecha_grabacion(f) == (datetime.date.today()-datetime.timedelta(days=3)).isoformat(),
    actas.fecha_grabacion(f))

chk("un fichero que no existe no revienta",
    actas.fecha_grabacion(pathlib.Path("no_existe_12345.mkv")) == hoy)

# --- el resumen: hermano del acta, sin las cuatro cajas ------------------
vistos = []
falso = _t.ModuleType("llm")
falso.generar = lambda prompt, max_tokens=1500: (vistos.append(prompt), "resumen en prosa")[1]
_sys.modules["llm"] = falso

vistos.clear()
r = actas.redactar_resumen("una reunion corta")
chk("resumen corto = una llamada", len(vistos) == 1 and r == "resumen en prosa")
chk("el prompt prohibe filtrar por relevancia", "no filtras por relevancia" in vistos[0])
chk("y pide conservar las ideas fuerza", "ideas fuerza" in vistos[0])

vistos.clear()
largo = "\n".join(f"[0:00:{i:02d}] frase {i} " + "z"*200 for i in range(300))
actas.redactar_resumen(largo)
chk("resumen largo se hace por tramos y se unifica", len(vistos) >= 3, f"{len(vistos)} llamadas")
chk("la ultima llamada unifica", "actas parciales" in vistos[-1])

print("\nRESULTADO:", "todo bien" if all(ok) else f"{ok.count(False)} FALLOS")
