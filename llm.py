"""Embeddings y respuestas. Por defecto Gemini (capa gratuita); Ollama si lo prefieres."""

import json
import math
import os
import pathlib
import random
import sys
import time

import httpx

BACKEND = os.environ.get("LLM_BACKEND", "gemini").strip().lower()

# --- Gemini ------------------------------------------------------------------
# Google ya no publica una tabla fija de límites de la capa gratuita: dependen
# del proyecto y se consultan en https://aistudio.google.com/rate-limit
# Por eso aquí no asumimos ninguna cifra y reintentamos ante un 429.
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")).strip()
GEMINI_CHAT = os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.7-flash").strip()
GEMINI_EMBED = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001").strip()
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))

# --- Ollama (100% local, sin red) -------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT = os.environ.get("OLLAMA_CHAT_MODEL", "qwen3:8b").strip()
OLLAMA_EMBED = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text").strip()

# --- Reintentos --------------------------------------------------------------
REINTENTOS = int(os.environ.get("LLM_REINTENTOS", "6"))
ESPERA_MAX = float(os.environ.get("LLM_ESPERA_MAX", "90"))


# --- Custodia ----------------------------------------------------------------
# Subcomando en curso ("sync", "bot", "acta"...); lo fija askhub.main(). Con él,
# cada evento del libro de custodia dice desde qué paso se llamó al modelo.
PASO = ""


def paso() -> str:
    script = pathlib.Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "unknown"
    return f"{script} {PASO}".strip()


def _motor(url: str) -> str:
    if url.startswith(OLLAMA_URL):
        return "ollama"
    if url.startswith(GEMINI_API):
        return "gemini"
    return url.split("/")[2] if "//" in url else url


class CuotaAgotada(RuntimeError):
    """El proveedor sigue devolviendo 429 después de agotar los reintentos."""


def _segundos_sugeridos(r: httpx.Response) -> float | None:
    """Cuánto pide esperar el servidor. Google lo manda en el cuerpo, no en la cabecera."""
    cab = r.headers.get("retry-after")
    if cab:
        try:
            return float(cab)
        except ValueError:
            pass
    try:
        detalles = (r.json().get("error") or {}).get("details") or []
    except Exception:
        return None
    for d in detalles:
        retraso = d.get("retryDelay")
        if isinstance(retraso, str) and retraso.endswith("s"):
            try:
                return float(retraso[:-1])
            except ValueError:
                pass
    return None


def _post_raw(url: str, *, aviso: str = "", **kw) -> httpx.Response:
    """POST con reintentos ante 429 y errores 5xx/red.

    Un 429 a mitad de una sincronización larga es lo normal en la capa gratuita,
    no una excepción: si no se reintenta, el sync se cae y hay que empezar de cero.
    """
    ultimo: Exception | None = None
    for intento in range(REINTENTOS):
        try:
            r = httpx.post(url, **kw)
        # Ojo: se reintenta también cuando la petición pudo llegar y fallar al
        # leer la respuesta. Aquí da igual —embeddings y generación no tienen
        # efectos secundarios— pero no valdría para un POST que escriba.
        except httpx.RequestError as e:  # timeout, DNS, conexión caída
            ultimo = e
        else:
            if r.status_code < 400:
                return r
            if r.status_code != 429 and r.status_code < 500:
                r.raise_for_status()  # 400, 401, 403: reintentar no arregla nada
            espera = _segundos_sugeridos(r)
            ultimo = httpx.HTTPStatusError(
                f"{r.status_code} en {aviso or url}: {r.text[:300]}", request=r.request, response=r
            )
            if intento == REINTENTOS - 1:
                break
            if espera is None:
                espera = 2**intento
            time.sleep(min(espera + random.uniform(0, 1), ESPERA_MAX))
            continue

        if intento == REINTENTOS - 1:
            break
        time.sleep(min(2**intento + random.uniform(0, 1), ESPERA_MAX))

    if isinstance(ultimo, httpx.HTTPStatusError) and ultimo.response.status_code == 429:
        raise CuotaAgotada(
            f"Cuota agotada tras {REINTENTOS} intentos ({aviso or url}). "
            "Mira tus límites en https://aistudio.google.com/rate-limit, "
            "o pasa a Ollama con LLM_BACKEND=ollama en el .env."
        ) from ultimo
    raise ultimo  # type: ignore[misc]


# --- cable 2: libro de custodia. Toda llamada al modelo pasa por aquí. ---
def _post(url: str, *, aviso: str = "", **kw) -> httpx.Response:
    from custodia.ledger import record_call, is_local
    payload = json.dumps(kw.get("json"), ensure_ascii=False)
    with record_call(step=paso(), engine=_motor(url), endpoint=url.split("/")[2] if "//" in url else url,
                     leaves_machine=not is_local(url), payload=payload) as rec:
        r = _post_raw(url, aviso=aviso, **kw)
        rec["output_chars"] = len(r.text)
        return r


def _normalizar(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def _embed_gemini(textos: list[str], task: str) -> list[list[float]]:
    salida = []
    for i in range(0, len(textos), 50):
        lote = textos[i : i + 50]
        body = {
            "requests": [
                {
                    "model": f"models/{GEMINI_EMBED}",
                    "content": {"parts": [{"text": t[:8000] or " "}]},
                    "taskType": task,
                    "outputDimensionality": EMBED_DIM,
                }
                for t in lote
            ]
        }
        r = _post(
            f"{GEMINI_API}/models/{GEMINI_EMBED}:batchEmbedContents",
            aviso=f"embeddings ({len(lote)} fragmentos)",
            json=body,
            headers={"x-goog-api-key": GEMINI_KEY},
            timeout=120.0,
        )
        salida.extend(_normalizar(e["values"]) for e in r.json()["embeddings"])
    return salida


def _embed_ollama(textos: list[str]) -> list[list[float]]:
    salida = []
    for t in textos:
        r = _post(
            f"{OLLAMA_URL}/api/embeddings",
            aviso="embeddings (ollama)",
            json={"model": OLLAMA_EMBED, "prompt": t[:8000]},
            timeout=120.0,
        )
        salida.append(_normalizar(r.json()["embedding"]))
    return salida


def embed(textos: list[str], consulta: bool = False) -> list[list[float]]:
    if not textos:
        return []
    if BACKEND == "ollama":
        return _embed_ollama(textos)
    return _embed_gemini(textos, "RETRIEVAL_QUERY" if consulta else "RETRIEVAL_DOCUMENT")


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------

def _texto_gemini(payload: dict) -> str:
    cand = payload.get("candidates") or []
    if not cand:
        return ""
    partes = (cand[0].get("content") or {}).get("parts") or []
    return "\n".join(p["text"] for p in partes if p.get("text") and not p.get("thought")).strip()


def generar(prompt: str, max_tokens: int = 1500) -> str:
    if BACKEND == "ollama":
        r = _post(
            f"{OLLAMA_URL}/api/generate",
            aviso="generación (ollama)",
            json={"model": OLLAMA_CHAT, "prompt": prompt, "stream": False},
            timeout=300.0,
        )
        return (r.json().get("response") or "").strip()

    r = _post(
        f"{GEMINI_API}/models/{GEMINI_CHAT}:generateContent",
        aviso="generación",
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        },
        headers={"x-goog-api-key": GEMINI_KEY},
        timeout=180.0,
    )
    return _texto_gemini(r.json())


def describir() -> str:
    if BACKEND == "ollama":
        return f"ollama · {OLLAMA_CHAT} + {OLLAMA_EMBED}"
    return f"gemini · {GEMINI_CHAT} + {GEMINI_EMBED}@{EMBED_DIM}d"
