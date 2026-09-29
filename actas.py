"""Actas de reunión: audio → transcripción local → acta → índice (y Discord).

El audio no sale de tu máquina: Whisper corre en local. Solo el texto ya
transcrito viaja al modelo para redactar el acta — y ni eso si usas Ollama.

    python askhub.py acta grabacion.flac
    python askhub.py acta grabacion.flac --titulo "Semanal" --publicar
"""

import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
import textwrap

import httpx

BASE = pathlib.Path(__file__).resolve().parent
DIR_ACTAS = BASE / "docs" / "actas"
# Si el acta se publica en Discord, su copia NO va en docs/: el conector de
# Discord ya la indexa desde el canal, y tenerla en los dos sitios duplica
# el mismo texto en el indice y gasta embeddings de mas.
DIR_ACTAS_PUBLICADAS = BASE / "actas"
# La transcripcion completa se guarda SIEMPRE, pero por defecto NO se indexa.
# El resumen en prosa ya recoge las ideas fuerza, y una hora de reunion con su
# paja son unos ocho fragmentos de relleno compitiendo con lo bueno cada vez
# que el buscador elige que 14 pasarle al modelo. Con
# INDEXAR_TRANSCRIPCIONES=1 vuelve a entrar.
INDEXAR_TRANSCRIPCIONES = os.environ.get("INDEXAR_TRANSCRIPCIONES", "0") in ("1", "si", "yes", "true")
DIR_TRANSCRIPCIONES = (BASE / "docs" / "transcripciones") if INDEXAR_TRANSCRIPCIONES else (
    BASE / "transcripciones"
)
DIR_GRABACIONES = pathlib.Path(
    os.environ.get("GRABACIONES_DIR") or (BASE / "grabaciones")
)
# Quien habla en cada pista, por orden. En OBS: pista 1 = audio del
# escritorio (la otra persona), pista 2 = tu microfono.
HABLANTES = [h.strip() for h in os.environ.get("ACTA_HABLANTES", "").split(",") if h.strip()]

GRABABLES = {".mkv", ".mp4", ".m4a", ".flac", ".wav", ".mp3", ".ogg", ".opus", ".webm"}

MODELO = os.environ.get("WHISPER_MODEL", "small")
# "es" fuerza español; "auto" deja que Whisper lo detecte. Como el audio se
# trocea en tramos y cada uno se detecta por separado, "auto" aguanta bien una
# reunion en español con un rato largo revisando material en ingles.
IDIOMA = os.environ.get("WHISPER_IDIOMA", "es").strip().lower()
IDIOMA = None if IDIOMA in ("auto", "") else IDIOMA
COMPUTO = os.environ.get("WHISPER_COMPUTE", "int8")
# Nombres propios extra, separados por comas. Los del tablero se sacan solos.
VOCABULARIO = os.environ.get("WHISPER_VOCABULARIO", "")

# Motor de transcripcion: "local" (faster-whisper en tu CPU) o "groq".
# Groq sirve whisper-large-v3-turbo gratis a ~220x tiempo real: una reunion
# de una hora en unos segundos, frente a los 15-20 minutos que tarda un
# portatil. A cambio, el audio sale de tu maquina.
STT = os.environ.get("STT_BACKEND", "local").strip().lower()
GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODELO = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
GROQ_API = "https://api.groq.com/openai/v1/audio/transcriptions"

# Groq rechaza ficheros de mas de 25 MB en el plan gratuito. Troceamos a
# WAV de 16 kHz mono: ~1,9 MB por minuto, asi que 10 min entran de sobra.
MINUTOS_TROZO = float(os.environ.get("STT_MINUTOS_TROZO", "10"))

# Whisper alucina sobre el silencio del final: se inventa frases de subtitulo
# de YouTube ("Gracias por ver el video") o repite la pista de vocabulario.
# Esos segmentos salen con una verosimilitud mucho peor que el resto, asi que
# el corte es relativo a la propia grabacion y no un umbral fijo, que en un
# audio malo se llevaria por delante habla de verdad.
MARGEN_ALUCINACION = float(os.environ.get("STT_MARGEN_ALUCINACION", "0.35"))

CANAL_DISCORD = os.environ.get("DISCORD_ACTAS_CANAL", "").strip()
CANAL_RESUMENES = os.environ.get("DISCORD_RESUMENES_CANAL", "").strip()
LIMITE_MENSAJE = 1900  # Discord corta en 2000; dejamos aire para el encabezado

# Por encima de esto la transcripción se resume por partes y luego se unifica,
# para no depender de que quepa entera en la ventana de contexto.
TROZO = 18000

FALTA_WHISPER = (
    "faster-whisper no está instalado. Es la única dependencia nueva:\n\n"
    "    pip install faster-whisper\n\n"
    "Trae su propio ffmpeg, no hace falta instalarlo aparte."
)


# ---------------------------------------------------------------------------
# 1. Transcripción (local)
# ---------------------------------------------------------------------------

def _vocabulario() -> str:
    """Nombres propios del propio espacio de trabajo.

    Whisper no sabe que "Reqif" existe y transcribe "RECIF"; tampoco conoce el
    nombre de tu compañero, y escribe lo que le suena. Pero esos nombres ya estan
    en el indice, asi que se los damos por adelantado en vez de corregirlos despues.
    """
    terminos = {t.strip() for t in VOCABULARIO.split(",") if t.strip()}
    try:
        import sqlite3

        import store

        con = sqlite3.connect(store.DB_PATH)
        for (titulo,) in con.execute(
            "select distinct title from chunks where source = 'trello'"
        ):
            for parte in (titulo or "").split(" · "):
                parte = parte.strip()
                if parte and parte.lower() not in ("resumen", "sin empresa"):
                    terminos.add(parte)
        con.close()
    except Exception:  # noqa: BLE001
        pass  # sin indice todavia: se tira con lo que haya en el .env
    return ", ".join(sorted(terminos))


def _trocear_audio(
    ruta: pathlib.Path, minutos: float = 0, pista: int = 0
) -> list[tuple[pathlib.Path, float]]:
    """Decodifica a 16 kHz mono y parte en WAV que quepan en el limite de subida.

    Devuelve [(fichero, segundos_de_desfase)] para poder recomponer las marcas
    de tiempo despues.
    """
    import tempfile
    import wave

    import av

    minutos = minutos or MINUTOS_TROZO
    por_trozo = int(16000 * 60 * minutos)
    destino = pathlib.Path(tempfile.mkdtemp(prefix="askhub_stt_"))

    contenedor = av.open(str(ruta))
    remuestreo = av.AudioResampler(format="s16", layout="mono", rate=16000)

    trozos: list[tuple[pathlib.Path, float]] = []
    escritor = None
    muestras = 0
    total = 0

    def abrir(indice: int):
        w = wave.open(str(destino / f"parte{indice:03d}.wav"), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        return w

    for cuadro in contenedor.decode(audio=pista):
        for salida in remuestreo.resample(cuadro):
            # to_ndarray() y no planes[0]: el plano viene con relleno del bufer,
            # y ese relleno se colaba como audio, alargando la grabacion.
            crudo = salida.to_ndarray().tobytes()
            if escritor is None:
                trozos.append((destino / f"parte{len(trozos):03d}.wav", total / 16000))
                escritor = abrir(len(trozos) - 1)
                muestras = 0
            escritor.writeframes(crudo)
            n = len(crudo) // 2
            muestras += n
            total += n
            if muestras >= por_trozo:
                escritor.close()
                escritor = None

    if escritor is not None:
        escritor.close()
    contenedor.close()
    return trozos


def _sin_alucinaciones(segmentos: list[dict]) -> tuple[list[dict], int]:
    """Quita el ruido que Whisper se inventa al final, sin tocar el habla real."""
    utiles = [s for s in segmentos if (s.get("text") or "").strip()]
    if len(utiles) < 2:
        return utiles, 0

    probs = sorted(s.get("avg_logprob", 0.0) for s in utiles)
    mediana = probs[len(probs) // 2]
    corte = mediana - MARGEN_ALUCINACION

    # Solo por la cola: un bajon en mitad de la reunion es alguien hablando
    # flojo, no una alucinacion.
    fin = len(utiles)
    while fin > 1:
        ultimo = utiles[fin - 1]
        malo = ultimo.get("avg_logprob", 0.0) < corte
        callado = ultimo.get("no_speech_prob", 0.0) > 0.6
        if not (malo or callado):
            break
        fin -= 1
    return utiles[:fin], len(utiles) - fin


def _paso() -> str:
    """Paso que hace la llamada, para el libro de custodia ('askhub acta')."""
    try:
        import llm

        return llm.paso()
    except Exception:  # noqa: BLE001  (un llm falseado en las pruebas)
        return pathlib.Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "unknown"


def _transcribir_groq(ruta: pathlib.Path, pistas: str) -> str:
    from custodia.ledger import record_call, is_local

    if not GROQ_KEY:
        raise RuntimeError(
            "Falta GROQ_API_KEY en el .env. Es gratis y sin tarjeta: "
            "https://console.groq.com/keys"
        )
    lineas = []
    descartados = 0
    for fichero, desfase in _trocear_audio(ruta):
        crudo = fichero.read_bytes()
        datos = {
            "model": (None, GROQ_MODELO),
            "response_format": (None, "verbose_json"),
            "file": (fichero.name, crudo, "audio/wav"),
        }
        if IDIOMA:  # sin este campo, Groq detecta el idioma del tramo
            datos["language"] = (None, IDIOMA)
        if pistas:
            # Sin frase envolvente: Whisper trata el prompt como texto que
            # ya venia y lo continua, asi que una instruccion acaba dentro
            # de la transcripcion. Una lista pelada de nombres, no.
            datos["prompt"] = (None, pistas[:800])
        # --- cable 2: libro de custodia. El audio SALE de la máquina. Como no
        # es texto, el tamaño y el hash se toman de los bytes del trozo (van por
        # **extra y pisan los del payload vacío); el contenido, nunca. ---
        with record_call(
            step=_paso(), engine="groq", endpoint=GROQ_API.split("/")[2],
            leaves_machine=not is_local(GROQ_API), payload="",
            input_chars=len(crudo), input_sha256_16=hashlib.sha256(crudo).hexdigest()[:16],
            input_kind="audio/wav",
        ) as rec:
            r = httpx.post(
                GROQ_API,
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files=datos,
                timeout=300.0,
            )
            if r.status_code == 401:
                raise RuntimeError("Groq rechaza la clave (401). Revisa GROQ_API_KEY.")
            if r.status_code == 413:
                raise RuntimeError(
                    "Groq rechaza el fichero por tamano. Baja STT_MINUTOS_TROZO en el .env."
                )
            r.raise_for_status()
            respuesta = r.json()
            rec["output_chars"] = len(json.dumps(respuesta))
        buenos, tirados = _sin_alucinaciones(respuesta.get("segments") or [])
        descartados += tirados
        for seg in buenos:
            marca = str(datetime.timedelta(seconds=int(seg.get("start", 0) + desfase)))
            lineas.append(f"[{marca}] {(seg.get('text') or '').strip()}")
    if descartados:
        print(f"  ({descartados} segmento(s) descartados por parecer alucinacion de silencio)")
    return "\n".join(lineas)


def transcribir(ruta: pathlib.Path, progreso=None) -> str:
    pistas = _vocabulario()
    if STT == "groq":
        return _transcribir_groq(ruta, pistas)
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(FALTA_WHISPER) from e

    modelo = WhisperModel(MODELO, device="cpu", compute_type=COMPUTO)
    segmentos, info = modelo.transcribe(
        str(ruta),
        language=IDIOMA,
        vad_filter=True,
        hotwords=pistas or None,
    )

    lineas = []
    for s in segmentos:
        marca = str(datetime.timedelta(seconds=int(s.start)))
        lineas.append(f"[{marca}] {s.text.strip()}")
        if progreso:
            progreso(s.start, info.duration)
    return "\n".join(lineas)


TEXTO_PLANO = {".txt", ".md", ".markdown"}
SUBTITULOS = {".vtt", ".srt"}
DOCUMENTO = {".docx"}
YA_TRANSCRITO = TEXTO_PLANO | SUBTITULOS | DOCUMENTO


def _leer_vtt(texto: str) -> str:
    """De un .vtt o .srt saca '[hh:mm:ss] frase', tirando cabeceras y numeracion."""
    lineas, marca = [], ""
    for cruda in texto.splitlines():
        linea = cruda.strip()
        if not linea or linea.upper().startswith("WEBVTT") or linea.isdigit():
            continue
        if "-->" in linea:
            marca = linea.split("-->")[0].strip().split(".")[0].split(",")[0]
            continue
        linea = re.sub(r"<[^>]+>", "", linea)  # etiquetas de estilo o de hablante
        if linea:
            lineas.append(f"[{marca}] {linea}" if marca else linea)
            marca = ""
    return "\n".join(lineas)


def _leer_docx(ruta: pathlib.Path) -> str:
    """Un .docx es un zip con XML. Se saca el texto sin dependencias."""
    import zipfile

    with zipfile.ZipFile(ruta) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", " ", xml)
    texto = re.sub(r"<[^>]+>", "", xml)
    for antes, despues in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        texto = texto.replace(antes, despues)
    return "\n".join(l.strip() for l in texto.split("\n") if l.strip())


def _leer_transcripcion(ruta: pathlib.Path) -> str:
    """Una transcripcion ya hecha: de Teams, de tl;dv, de donde sea."""
    if ruta.suffix.lower() in DOCUMENTO:
        return _leer_docx(ruta)
    texto = ruta.read_text(encoding="utf-8", errors="ignore")
    if ruta.suffix.lower() in SUBTITULOS:
        return _leer_vtt(texto)
    return texto.strip()


def _num_pistas(ruta: pathlib.Path) -> int:
    try:
        import av

        with av.open(str(ruta)) as c:
            return max(1, len(c.streams.audio))
    except Exception:  # noqa: BLE001
        return 1


def _extraer_pistas(ruta: pathlib.Path, hablantes: list[str]) -> list[pathlib.Path]:
    """OBS deja micro y escritorio en pistas separadas del MISMO fichero.

    Con dos participantes eso es diarizacion perfecta y gratis, pero hay que
    separarlas antes: cada pista pasa a ser un fichero, y cada fichero, una voz.
    """
    salidas = []
    for i in range(_num_pistas(ruta)):
        nombre = hablantes[i] if i < len(hablantes) else f"pista{i + 1}"
        # Un solo trozo por pista: partir ya lo hace despues quien transcribe.
        trozos = _trocear_audio(ruta, minutos=10**6, pista=i)
        if not trozos:
            continue
        destino = trozos[0][0].with_name(f"{i + 1}-{_slug(nombre)}.wav")
        trozos[0][0].rename(destino)
        salidas.append(destino)
    return salidas


def transcribir_varias(
    rutas: list[pathlib.Path], progreso=None, hablantes: list[str] | None = None
) -> str:
    """Una pista por persona -- de Craig, o de grabar micro y sistema aparte.

    Acepta tambien transcripciones ya hechas (.txt, .vtt, .srt, .docx): da igual
    si vienen de Teams, de tl;dv o de aqui. Lo que cambia es de donde sale el
    texto; el acta la escribimos siempre nosotros.
    """
    hablantes = hablantes or []
    # Un unico fichero con varias pistas: se abre en una por voz.
    if len(rutas) == 1 and rutas[0].suffix.lower() not in YA_TRANSCRITO:
        if _num_pistas(rutas[0]) > 1:
            rutas = _extraer_pistas(rutas[0], hablantes)

    def contenido(r: pathlib.Path) -> str:
        if r.suffix.lower() in YA_TRANSCRITO:
            return _leer_transcripcion(r)
        return transcribir(r, progreso)

    if len(rutas) == 1:
        return contenido(rutas[0])
    partes = []
    for r in rutas:
        hablante = re.sub(r"^\d+[-_]", "", r.stem)  # "1-daniel.flac" -> "daniel"
        partes.append(f"### Pista de {hablante}\n{contenido(r)}")
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# 2. Redacción del acta
# ---------------------------------------------------------------------------

PROMPT_ACTA = """Eres quien levanta el acta de una reunión de trabajo. Escribes en español,
claro y sin relleno.

Abajo va la transcripción automática de una reunión{contexto_pistas}. Puede tener
errores de reconocimiento: interpreta con sentido común, pero **no inventes nada
que no se haya dicho**. Si algo queda ambiguo, dilo en vez de rellenarlo.

Devuelve exactamente estas secciones en Markdown, y omite las que queden vacías:

## Resumen
Tres o cuatro frases. Qué se trató y a dónde se llegó.

## Decisiones
Lo que quedó decidido. Una línea por decisión. Si no se decidió nada, dilo.

## Tareas
Una línea por tarea, con responsable si se dijo y fecha si se mencionó.
Formato: `- [ ] Tarea — responsable — fecha`. Sin responsable, pon "sin asignar".

## Temas abiertos
Lo que quedó sin cerrar o pendiente de más información.

### Transcripción
{transcripcion}
"""

PROMPT_UNIFICAR = """Abajo van las actas parciales de tramos consecutivos de UNA misma reunión.
Únelas en un acta sola, en español, con las secciones Resumen, Decisiones, Tareas
y Temas abiertos. Fusiona lo repetido, respeta el orden cronológico y no añadas
nada que no esté en las partes.

{partes}
"""


def _trocear(texto: str, tam: int = TROZO) -> list[str]:
    if len(texto) <= tam:
        return [texto]
    lineas, trozos, buf = texto.split("\n"), [], ""
    for linea in lineas:
        if len(buf) + len(linea) + 1 > tam and buf:
            trozos.append(buf)
            buf = linea
        else:
            buf = f"{buf}\n{linea}" if buf else linea
    if buf:
        trozos.append(buf)
    return trozos


def redactar(transcripcion: str, varias_pistas: bool = False, progreso=None) -> str:
    import llm

    contexto = " grabada con una pista por participante" if varias_pistas else ""
    trozos = _trocear(transcripcion)

    if len(trozos) == 1:
        return llm.generar(
            PROMPT_ACTA.format(transcripcion=trozos[0], contexto_pistas=contexto),
            max_tokens=2000,
        )

    parciales = []
    for i, trozo in enumerate(trozos, 1):
        if progreso:
            progreso(i, len(trozos))
        parciales.append(
            f"## Parte {i} de {len(trozos)}\n"
            + llm.generar(
                PROMPT_ACTA.format(transcripcion=trozo, contexto_pistas=contexto),
                max_tokens=1500,
            )
        )
    return llm.generar(PROMPT_UNIFICAR.format(partes="\n\n".join(parciales)), max_tokens=2500)


PROMPT_RESUMEN = """Escribe el resumen de una reunión de trabajo, en español, en prosa.

El acta formal ya se ha hecho por otro lado y recoge decisiones y tareas. Tu
trabajo es el contrario: **quedarte con lo que esa estructura tiraría**.

Reglas:
- Cuenta de qué se habló, en orden, con las ideas tal como salieron.
- Conserva las **ideas fuerza** aunque no lleven a ninguna tarea: propuestas de
  futuro, formas nuevas de enfocar algo, dudas de fondo.
- Conserva las menciones a otras empresas, clientes o proyectos aunque fueran
  de pasada. Quien lea decide si le sirve; **tú no filtras por relevancia**.
- Quita la paja de verdad: saludos, repeticiones, "¿me oyes?", divagaciones sin
  contenido.
- No inventes nada. Si algo quedó a medias o ambiguo, dilo así.
- Prosa seguida, sin listas ni encabezados. Ni resumen ejecutivo ni telegrama.

### Transcripción
{transcripcion}
"""


def redactar_resumen(transcripcion: str, progreso=None) -> str:
    """El hermano del acta: lo que no cabe en cuatro cajas."""
    import llm

    trozos = _trocear(transcripcion)
    if len(trozos) == 1:
        return llm.generar(PROMPT_RESUMEN.format(transcripcion=trozos[0]), max_tokens=2000)
    partes = []
    for i, trozo in enumerate(trozos, 1):
        if progreso:
            progreso(i, len(trozos))
        partes.append(llm.generar(PROMPT_RESUMEN.format(transcripcion=trozo), max_tokens=1500))
    return llm.generar(PROMPT_UNIFICAR.format(partes="\n\n".join(partes)), max_tokens=2500)


# ---------------------------------------------------------------------------
# 3. Guardar y publicar
# ---------------------------------------------------------------------------

def pendientes() -> list[pathlib.Path]:
    """Grabaciones de la carpeta que aun no tienen acta.

    Se lleva la cuenta en la misma base que el resto, para que volver a lanzar
    el comando no rehaga lo ya hecho ni gaste transcripcion de mas.
    """
    if not DIR_GRABACIONES.exists():
        return []
    try:
        import store

        store.init()
        hechas = {f for f in (store.get_state("actas_hechas") or "").split("|") if f}
    except Exception:  # noqa: BLE001
        hechas = set()
    sueltas = [
        r
        for r in sorted(DIR_GRABACIONES.iterdir())
        if r.is_file()
        and (r.suffix.lower() in GRABABLES or r.suffix.lower() in YA_TRANSCRITO)
        and r.name not in hechas
    ]
    return sueltas


def marcar_hecha(ruta: pathlib.Path) -> None:
    try:
        import store

        hechas = [f for f in (store.get_state("actas_hechas") or "").split("|") if f]
        if ruta.name not in hechas:
            hechas.append(ruta.name)
        store.set_state("actas_hechas", "|".join(hechas[-500:]))
    except Exception:  # noqa: BLE001
        pass


def fecha_grabacion(ruta: pathlib.Path) -> str:
    """Cuando se GRABO, no cuando se procesa.

    Si grabas el viernes y lo pasas el lunes, fechar con hoy descoloca el acta
    y rompe preguntas como "¿que dijimos el viernes?". Se prueba, de mas fiable
    a menos: metadato del contenedor, fecha en el nombre, fecha del fichero.
    """
    try:
        import av

        with av.open(str(ruta)) as c:
            crudo = (c.metadata or {}).get("creation_time", "")
        if crudo:
            return datetime.datetime.fromisoformat(crudo.replace("Z", "+00:00")).date().isoformat()
    except Exception:  # noqa: BLE001
        pass

    # OBS nombra "2026-08-24 18-30-15.mkv"; otros usan guiones bajos o nada.
    m = re.search(r"(20\d{2})[-_.]?(0\d|1[0-2])[-_.]?(0\d|[12]\d|3[01])", ruta.stem)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass

    try:
        return datetime.date.fromtimestamp(ruta.stat().st_mtime).isoformat()
    except OSError:
        return datetime.date.today().isoformat()


def _slug(texto: str) -> str:
    limpio = re.sub(r"[^\w\s-]", "", texto, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_]+", "-", limpio)[:60] or "reunion"


def guardar(
    acta: str, transcripcion: str, titulo: str, fecha: str, indexar: bool = True
) -> tuple[pathlib.Path, pathlib.Path]:
    carpeta = DIR_ACTAS if indexar else DIR_ACTAS_PUBLICADAS
    carpeta.mkdir(parents=True, exist_ok=True)
    DIR_TRANSCRIPCIONES.mkdir(parents=True, exist_ok=True)
    nombre = f"{fecha}-{_slug(titulo)}"

    ruta_acta = carpeta / f"{nombre}.md"
    ruta_acta.write_text(
        f"# {titulo}\n\n**Fecha:** {fecha}\n\n{acta.strip()}\n", encoding="utf-8"
    )
    # La transcripción cruda vive FUERA de docs/: es enorme y indexarla entera
    # se comería los embeddings sin aportar más que el acta.
    ruta_tr = DIR_TRANSCRIPCIONES / f"{nombre}.txt"
    ruta_tr.write_text(transcripcion, encoding="utf-8")
    return ruta_acta, ruta_tr


def publicar_discord(acta: str, titulo: str, fecha: str, canal: str = "") -> None:
    canal = (canal or CANAL_DISCORD).strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not canal:
        raise RuntimeError("Falta DISCORD_ACTAS_CANAL en el .env (id del canal #actas).")
    if not token:
        raise RuntimeError("Falta DISCORD_BOT_TOKEN en el .env.")

    cuerpo = f"**{titulo}** · {fecha}\n\n{acta.strip()}"
    trozos = textwrap.wrap(
        cuerpo, LIMITE_MENSAJE, replace_whitespace=False, drop_whitespace=False
    ) or [cuerpo]

    with httpx.Client(headers={"Authorization": f"Bot {token}"}, timeout=60.0) as cli:
        for trozo in trozos:
            r = cli.post(f"https://discord.com/api/v10/channels/{canal}/messages",
                         json={"content": trozo})
            if r.status_code == 403:
                raise RuntimeError(
                    "Discord responde 403: el bot no puede escribir en ese canal. "
                    "Dale el permiso 'Enviar mensajes' o revisa el id del canal."
                )
            r.raise_for_status()
