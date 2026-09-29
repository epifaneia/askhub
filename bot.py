"""El bot de #preguntar: escucha un canal de Discord y responde desde el índice.

Sondea por REST en vez de abrir una conexión de gateway. Para dos personas
preguntando de vez en cuando, sondear cada pocos segundos sobra — y así no
entra ninguna dependencia nueva: el mismo httpx que ya usan los conectores.

Con esto tu compañero no instala nada: pregunta en Discord y ya está.

    python askhub.py bot
"""

import os
import time

import httpx

API = "https://discord.com/api/v10"
LIMITE_MENSAJE = 1900  # Discord corta en 2000

CANAL = os.environ.get("DISCORD_PREGUNTAR_CANAL", "").strip()
INTERVALO = float(os.environ.get("BOT_INTERVALO", "5"))
SYNC_CADA = float(os.environ.get("BOT_SYNC_MINUTOS", "15"))


class SinConfigurar(RuntimeError):
    pass


def _client() -> httpx.Client:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SinConfigurar("Falta DISCORD_BOT_TOKEN en el .env.")
    return httpx.Client(headers={"Authorization": f"Bot {token}"}, timeout=60.0)


def _pedir(cli: httpx.Client, metodo: str, ruta: str, **kw):
    """Una llamada a Discord, respetando el rate limit que él mismo indica."""
    for _ in range(4):
        r = cli.request(metodo, f"{API}{ruta}", **kw)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("retry-after", "1")) + 0.5)
            continue
        if r.status_code == 403:
            raise SinConfigurar(
                "Discord responde 403. El bot está en el servidor pero le falta "
                "permiso de 'Ver canal' o 'Enviar mensajes' en ese canal."
            )
        r.raise_for_status()
        return r.json() if r.content else None
    raise RuntimeError("Discord sigue limitando la petición tras varios intentos.")


def _trocear(texto: str) -> list[str]:
    """Corta por líneas para no partir una frase a la mitad."""
    if len(texto) <= LIMITE_MENSAJE:
        return [texto]
    trozos, buf = [], ""
    for linea in texto.split("\n"):
        while len(linea) > LIMITE_MENSAJE:  # una línea sola más larga que el límite
            trozos.append(linea[:LIMITE_MENSAJE])
            linea = linea[LIMITE_MENSAJE:]
        if len(buf) + len(linea) + 1 > LIMITE_MENSAJE and buf:
            trozos.append(buf)
            buf = linea
        else:
            buf = f"{buf}\n{linea}" if buf else linea
    if buf:
        trozos.append(buf)
    return trozos


def responder_en(cli: httpx.Client, canal: str, texto: str, responde_a: str = "") -> None:
    for i, trozo in enumerate(_trocear(texto)):
        cuerpo = {"content": trozo}
        if i == 0 and responde_a:
            # Se engancha al mensaje original: en un canal con dos personas
            # preguntando a la vez, si no, no se sabe qué responde a qué.
            cuerpo["message_reference"] = {"message_id": responde_a}
            cuerpo["allowed_mentions"] = {"parse": []}
        _pedir(cli, "POST", f"/channels/{canal}/messages", json=cuerpo)


def escuchar(canal: str = "", intervalo: float = 0, sync_cada: float = -1, con=None) -> int:
    """Bucle principal. Se corta con Ctrl+C."""
    canal = (canal or CANAL).strip()
    if not canal:
        raise SinConfigurar(
            "Falta DISCORD_PREGUNTAR_CANAL en el .env: el id del canal #preguntar.\n"
            "En Discord: Ajustes de usuario > Avanzado > Modo desarrollador, "
            "y luego clic derecho en el canal > Copiar ID."
        )
    intervalo = intervalo or INTERVALO
    sync_cada = SYNC_CADA if sync_cada < 0 else sync_cada

    import askhub

    def aviso(txt):
        if con:
            con.print(txt)

    with _client() as cli:
        yo = _pedir(cli, "GET", "/users/@me")["id"]
        # Arrancamos desde el último mensaje: no se contesta a lo que ya estaba.
        ultimos = _pedir(cli, "GET", f"/channels/{canal}/messages", params={"limit": 1})
        cursor = ultimos[0]["id"] if ultimos else "0"
        aviso(f"[green]✓[/] escuchando en el canal {canal} · sondeo cada {intervalo:.0f}s")
        if sync_cada:
            aviso(f"[dim]  sync automático cada {sync_cada:.0f} min[/]")

        proximo_sync = time.time() + sync_cada * 60 if sync_cada else float("inf")

        while True:
            if time.time() >= proximo_sync:
                aviso("[dim]sincronizando…[/]")
                try:
                    askhub.sincronizar()
                except Exception as exc:  # noqa: BLE001
                    aviso(f"[yellow]sync falló: {type(exc).__name__}: {exc}[/]")
                proximo_sync = time.time() + sync_cada * 60

            try:
                nuevos = _pedir(
                    cli, "GET", f"/channels/{canal}/messages",
                    params={"after": cursor, "limit": 50},
                )
            except httpx.HTTPError as exc:
                aviso(f"[yellow]Discord no responde ({exc}); reintento[/]")
                time.sleep(intervalo * 2)
                continue

            for m in sorted(nuevos or [], key=lambda x: int(x["id"])):
                cursor = m["id"]
                autor = m.get("author") or {}
                if autor.get("id") == yo or autor.get("bot"):
                    continue  # nunca contestarse a sí mismo: sería un bucle infinito
                pregunta = (m.get("content") or "").strip()
                if not pregunta:
                    continue

                aviso(f"[cyan]?[/] {autor.get('username', '?')}: {pregunta[:80]}")
                try:
                    _pedir(cli, "POST", f"/channels/{canal}/typing")
                except Exception:  # noqa: BLE001
                    pass  # el indicador de "escribiendo" es cosmético
                try:
                    respuesta = askhub.responder(pregunta)
                except Exception as exc:  # noqa: BLE001
                    respuesta = f"Se me ha atragantado: `{type(exc).__name__}: {exc}`"
                    aviso(f"[red]✗[/] {exc}")
                responder_en(cli, canal, respuesta, responde_a=m["id"])

            time.sleep(intervalo)
