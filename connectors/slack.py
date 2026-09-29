"""Slack (plan gratuito): canales donde esté invitado el bot.

Ojo con el plan gratuito: Slack esconde lo anterior a 90 días. Tu copia local
NO lo pierde, así que cuanto antes empieces a sincronizar, más memoria tendrás.
"""

import os
import time

import httpx

API = "https://slack.com/api"
FALTA = "SLACK_BOT_TOKEN (xoxb-…, scopes: channels:history, channels:read, users:read)"


def disponible() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN"))


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN'].strip()}"},
        timeout=60.0,
    )


def _get(client: httpx.Client, metodo: str, **params) -> dict:
    for _ in range(3):
        r = client.get(f"{API}/{metodo}", params=params)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")))
            continue
        r.raise_for_status()
        datos = r.json()
        if not datos.get("ok"):
            raise RuntimeError(f"slack {metodo}: {datos.get('error')}")
        return datos
    raise RuntimeError(f"slack {metodo}: demasiados reintentos")


def _paginar(client: httpx.Client, metodo: str, campo: str, **params) -> list:
    salida, cursor = [], ""
    while True:
        datos = _get(client, metodo, cursor=cursor, limit=200, **params)
        salida.extend(datos.get(campo) or [])
        cursor = (datos.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            return salida


def fetch() -> list[dict]:
    import store

    from . import hash_texto

    filas = []
    with _client() as client:
        usuarios = {
            u["id"]: (u.get("profile", {}).get("display_name") or u.get("name") or "?")
            for u in _paginar(client, "users.list", "members")
        }
        canales = _paginar(
            client, "conversations.list", "channels", types="public_channel,private_channel"
        )

        for canal in canales:
            if not canal.get("is_member"):
                continue  # el bot tiene que estar invitado al canal
            cid, nombre = canal["id"], canal.get("name", "?")
            clave = f"slack_cursor_{cid}"
            desde = store.get_state(clave, "0")
            try:
                datos = _get(client, "conversations.history", channel=cid, oldest=desde, limit=200)
            except (httpx.HTTPError, RuntimeError):
                continue

            ultimo = desde
            for m in datos.get("messages") or []:
                texto = (m.get("text") or "").strip()
                ts = m.get("ts", "0")
                ultimo = max(ultimo, ts, key=float)
                if not texto or m.get("subtype"):
                    continue
                autor = usuarios.get(m.get("user"), m.get("username", "?"))
                sello = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
                contenido = f"[canal #{nombre}] {autor} ({sello}):\n{texto}"
                filas.append(
                    {
                        "id": f"slack:{cid}:{ts}",
                        "source": "slack",
                        "title": f"#{nombre}",
                        "url": "",
                        "content": contenido,
                        "hash": hash_texto(contenido),
                    }
                )
            store.set_state(clave, ultimo)
    return filas
