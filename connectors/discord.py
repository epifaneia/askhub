"""Discord (gratis, historial ilimitado): canales de texto, foros e hilos."""

import datetime
import os
import time

import httpx

API = "https://discord.com/api/v10"
FALTA = "DISCORD_BOT_TOKEN (https://discord.com/developers → Bot → activar MESSAGE CONTENT INTENT)"

# Mensajes a rescatar hacia atrás la PRIMERA vez, por canal.
BACKFILL = int(os.environ.get("DISCORD_BACKFILL", "1000"))

# Un mensaje suelto de chat ('si, dale') no significa nada como fragmento.
# Se agrupan los mensajes seguidos en conversaciones: mismo canal, sin un
# silencio mayor que VENTANA_MINUTOS, y hasta VENTANA_CHARS de texto.
#
# 24 horas, no media: en un chat de trabajo de dos personas se contesta a
# las horas o al dia siguiente. Con una ventana corta no se agruparia nada
# y volveriamos a tener mensajes sueltos. Quien acaba marcando el corte de
# verdad es el tamano.
VENTANA_MINUTOS = float(os.environ.get("DISCORD_VENTANA_MINUTOS", "1440"))
VENTANA_CHARS = int(os.environ.get("DISCORD_VENTANA_CHARS", "1500"))

TIPOS_TEXTO = {0, 5, 15}  # texto, anuncios, foro
TIPO_CATEGORIA = 4


def disponible() -> bool:
    return bool(os.environ.get("DISCORD_BOT_TOKEN"))


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN'].strip()}"},
        timeout=60.0,
    )


def _get(client: httpx.Client, path: str, **params):
    r = client.get(f"{API}{path}", params=params)
    if r.status_code == 429:  # rate limit: esperar lo que diga Discord
        time.sleep(float(r.headers.get("retry-after", "1")) + 0.5)
        r = client.get(f"{API}{path}", params=params)
    r.raise_for_status()
    return r.json()


def _mensajes(client: httpx.Client, canal_id: str, cursor: str) -> tuple[list[dict], str]:
    """Devuelve (mensajes, nuevo_cursor). Sin cursor hace backfill hacia atrás."""
    recogidos: list[dict] = []
    if cursor:
        while len(recogidos) < 5000:
            lote = _get(client, f"/channels/{canal_id}/messages", limit=100, after=cursor)
            if not lote:
                break
            recogidos.extend(lote)
            cursor = max(m["id"] for m in lote)  # los ids son crecientes en el tiempo
            if len(lote) < 100:
                break
    else:
        before = None
        while len(recogidos) < BACKFILL:
            params = {"limit": 100}
            if before:
                params["before"] = before
            lote = _get(client, f"/channels/{canal_id}/messages", **params)
            if not lote:
                break
            recogidos.extend(lote)
            before = min(m["id"] for m in lote)
            if len(lote) < 100:
                break
        cursor = max((m["id"] for m in recogidos), default="")
    return recogidos, cursor


def _ruta(canal: dict, mapa: dict) -> list[str]:
    """De un canal o hilo, su camino legible: categoria > canal > hilo.

    Discord encadena el parentesco con parent_id: un hilo cuelga de un canal y
    un canal cuelga de su categoria. Sin esto, con veinte canales el modelo ve
    "#rediseno" suelto y no sabe a que frente pertenece.
    """
    partes, actual, vistos = [], canal, set()
    while actual is not None and actual["id"] not in vistos:
        vistos.add(actual["id"])
        partes.append(actual.get("name") or "?")
        padre = actual.get("parent_id")
        actual = mapa.get(padre) if padre else None
    return list(reversed(partes))


def _encabezado(ruta: list[str], tema: str) -> str:
    """La cabecera que acompana a CADA mensaje: cada uno se indexa por separado."""
    if len(ruta) > 1:
        etiqueta = " › ".join(ruta[:-1]) + f" › #{ruta[-1]}"
    else:
        etiqueta = f"#{ruta[0]}" if ruta else "#?"
    if tema:
        etiqueta += f" ({tema[:120].strip()})"
    return etiqueta


def _orden(m: dict) -> int:
    """Los ids de Discord son crecientes en el tiempo. Un id raro no debe
    tumbar la sincronizacion entera del conector."""
    try:
        return int(m["id"])
    except (KeyError, ValueError, TypeError):
        return 0


def _fecha(m: dict) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(m["timestamp"])
    except (KeyError, ValueError, TypeError):
        return datetime.datetime.now(datetime.timezone.utc)


def _agrupar(mensajes: list[dict]) -> list[list[dict]]:
    """Parte una lista de mensajes en conversaciones.

    Se corta cuando hay un silencio largo o cuando la ventana ya es lo bastante
    grande como para valer de fragmento por si sola.
    """
    hueco = datetime.timedelta(minutes=VENTANA_MINUTOS)
    ventanas: list[list[dict]] = []
    actual: list[dict] = []
    largo = 0
    anterior = None

    for m in mensajes:
        cuando = _fecha(m)
        if actual and (
            (anterior is not None and cuando - anterior > hueco) or largo >= VENTANA_CHARS
        ):
            ventanas.append(actual)
            actual, largo = [], 0
        actual.append(m)
        largo += len((m.get("content") or "").strip()) + 1
        anterior = cuando

    if actual:
        ventanas.append(actual)
    return ventanas


def _texto_ventana(ventana: list[dict], nombre: str) -> str:
    """La cabecera va UNA vez, y debajo la conversacion seguida."""
    inicio = _fecha(ventana[0]).strftime("%Y-%m-%d %H:%M")
    lineas = [f"[canal {nombre}] conversacion del {inicio}"]
    for m in ventana:
        autor = (m.get("author") or {}).get("username", "?")
        hora = _fecha(m).strftime("%H:%M")
        lineas.append(f"{autor} ({hora}): {(m.get('content') or '').strip()}")
    return "\n".join(lineas)


def fetch() -> list[dict]:
    import store

    from . import hash_texto

    filas = []
    with _client() as client:
        for guild in _get(client, "/users/@me/guilds"):
            gid = guild["id"]
            try:
                canales = _get(client, f"/guilds/{gid}/channels")
            except httpx.HTTPError:
                continue

            # Los hilos activos son canales de pleno derecho para Discord.
            try:
                canales += (_get(client, f"/guilds/{gid}/threads/active") or {}).get("threads", [])
            except httpx.HTTPError:
                pass

            mapa = {c["id"]: c for c in canales}

            for canal in canales:
                if canal.get("type") == TIPO_CATEGORIA:
                    continue  # las categorias no tienen mensajes: solo dan contexto
                if canal.get("type") not in TIPOS_TEXTO and "thread_metadata" not in canal:
                    continue
                cid = canal["id"]
                clave = f"discord_cursor_{cid}"
                try:
                    mensajes, nuevo = _mensajes(client, cid, store.get_state(clave))
                except httpx.HTTPError:
                    continue  # sin permiso de lectura en ese canal: se salta

                ruta = _ruta(canal, mapa)
                nombre = _encabezado(ruta, canal.get("topic") or "")

                # Discord los devuelve del mas nuevo al mas viejo; para agrupar
                # una conversacion hacen falta en orden cronologico.
                utiles = sorted(
                    (m for m in mensajes if (m.get("content") or "").strip()),
                    key=_orden,
                )
                ventanas = _agrupar(utiles)

                for ventana in ventanas:
                    primero = ventana[0]
                    contenido = _texto_ventana(ventana, nombre)
                    filas.append(
                        {
                            "id": f"discord:{primero['id']}",
                            "source": "discord",
                            "title": nombre,
                            "url": f"https://discord.com/channels/{gid}/{cid}/{primero['id']}",
                            "content": contenido,
                            "hash": hash_texto(contenido),
                        }
                    )

                # Si la ultima conversacion sigue viva, se retrocede el cursor a
                # su principio: en el siguiente sync se relee y la ventana se
                # completa, en vez de partirse en dos fragmentos. Releer sale
                # gratis: si no ha cambiado, el hash coincide y no se reembebe.
                if ventanas:
                    fin = _fecha(ventanas[-1][-1])
                    ahora = datetime.datetime.now(datetime.timezone.utc)
                    if ahora - fin <= datetime.timedelta(minutes=VENTANA_MINUTOS):
                        arranque = _orden(ventanas[-1][0])
                        if arranque:
                            nuevo = str(arranque - 1)

                if nuevo:
                    store.set_state(clave, nuevo)
    return filas
