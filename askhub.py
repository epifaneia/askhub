"""askhub — pregunta en lenguaje natural a todo tu espacio de trabajo, en local.

    python askhub.py sync                 # trae y indexa todo (incremental)
    python askhub.py acta reunion.flac    # audio -> acta -> al indice
    python askhub.py ask "¿cómo va X?"    # pregunta
    python askhub.py chat                 # modo conversación
    python askhub.py bot                  # responde en #preguntar de Discord
    python askhub.py proyectos            # % de avance de cada tablero
    python askhub.py estado               # qué hay indexado y qué falta

No necesita servidor, ni Docker, ni que nadie más instale nada. La base es un
único fichero askhub.db junto a este script.
"""

import argparse
import datetime
import os
import pathlib
import re
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent


def leer_env(ruta: pathlib.Path) -> dict[str, str]:
    """KEY=VALUE de un .env, sin depender de python-dotenv. Los vacíos no entran."""
    valores = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valor = valor.strip()
        entre_comillas = re.match(r"""(["'])(.*?)\1""", valor)
        if entre_comillas:
            valor = entre_comillas.group(2)
        else:
            # un comentario al final de la línea ("5  # segundos") no es parte del valor
            # (con la clave vacía, "KEY=   # nota", el valor empieza ya por #)
            valor = re.split(r"(?:^|\s+)#", valor, maxsplit=1)[0].strip()
        if valor:
            valores[clave.strip()] = valor
    return valores


def cargar_env() -> None:
    """Lee el .env de al lado; lo que ya esté en el entorno manda."""
    ruta = BASE / ".env"
    if not ruta.exists():
        return
    for clave, valor in leer_env(ruta).items():
        os.environ.setdefault(clave, valor)


cargar_env()

# El libro de custodia (custodia/ledger.py) vive junto a askhub.db, no donde se
# lance el comando: una ruta relativa en CUSTODIA_LEDGER se resuelve desde aquí.
_ledger = os.environ.get("CUSTODIA_LEDGER", "logs/custody.jsonl")
if _ledger != "-" and not os.path.isabs(_ledger):
    os.environ["CUSTODIA_LEDGER"] = str(BASE / _ledger)

import connectors  # noqa: E402
import llm  # noqa: E402
import store  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.table import Table  # noqa: E402

con = Console()

PROMPT = """Eres el asistente del espacio de trabajo. Respondes en español, directo y sin paja.

Abajo van fragmentos REALES sacados por API del chat del equipo, de los tableros
de proyecto y de los documentos locales.

Reglas:
- Responde solo con lo que digan los fragmentos. Si no está, di "no lo encuentro
  en lo que tengo indexado" y sugiere qué sincronizar. No te inventes nada.
- Sobre el avance de algo: describe el estado con palabras y cita las subtareas
  pendientes tal como están escritas. NO des porcentajes ni los calques contando
  subtareas: un número mezcla cantidad de items con cantidad de trabajo, y no sabe
  decir lo más habitual — que algo está en producción, funcionando, y aún
  mejorándose. Si la tarjeta lo dice, dilo con sus palabras.
- Termina con "Fuentes:" y la lista de las que hayas usado de verdad.
{historial}
### Fragmentos
{contexto}

### Pregunta
{pregunta}
"""


def _contexto(hits: list[dict]) -> str:
    bloques = []
    for i, h in enumerate(hits, 1):
        cab = f"--- fragmento {i} · origen: {h['source']}"
        if h.get("title"):
            cab += f" · {h['title']}"
        if h.get("url"):
            cab += f" · {h['url']}"
        bloques.append(f"{cab}\n{h['content']}")
    return "\n\n".join(bloques)


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def sincronizar(solo=None) -> int:
    """Descarga e indexa. La usan el CLI y el bot, para no duplicar logica."""
    store.init()
    activos = connectors.activos()
    if not activos:
        con.print("[red]No hay ningún conector configurado.[/] Mira `python askhub.py estado`.")
        return 1

    total_nuevos = 0
    for nombre, modulo, purgar in activos:
        if solo and nombre not in solo:
            continue
        t0 = time.time()
        try:
            with con.status(f"[cyan]{nombre}[/]: descargando…"):
                filas = modulo.fetch()
        except Exception as exc:  # noqa: BLE001
            con.print(f"[red]✗ {nombre}[/]: {type(exc).__name__}: {exc}")
            continue

        conocidos = store.existing_hashes(nombre)
        nuevos = [f for f in filas if conocidos.get(f["id"]) != f["hash"]]

        try:
            for i in range(0, len(nuevos), 50):
                lote = nuevos[i : i + 50]
                with con.status(
                    f"[cyan]{nombre}[/]: embeddings {i + len(lote)}/{len(nuevos)}…"
                ):
                    store.upsert(lote, llm.embed([f["content"] for f in lote]))
        except Exception as exc:  # noqa: BLE001
            con.print(f"[red]✗ {nombre}[/] al calcular embeddings: {type(exc).__name__}: {exc}")
            continue

        borrados = store.prune(nombre, {f["id"] for f in filas}) if purgar else 0
        total_nuevos += len(nuevos)
        con.print(
            f"[green]✓ {nombre}[/]: {len(filas)} vistos · "
            f"[bold]{len(nuevos)} nuevos o cambiados[/] · {borrados} borrados "
            f"· {time.time() - t0:.1f}s"
        )

    con.print(f"\nÍndice: {store.counts()}  (nuevos esta vez: {total_nuevos})")
    return 0


def cmd_sync(args) -> int:
    return sincronizar(args.solo)


def responder(pregunta: str, historial: str = "", k: int = 14) -> str:
    """Responde contra el indice. La usan el CLI, el modo chat y el bot."""
    store.init()
    hits = store.search(llm.embed([pregunta], consulta=True)[0], k=k)
    if not hits:
        return "El índice está vacío. Lanza primero `python askhub.py sync`."
    return llm.generar(
        PROMPT.format(contexto=_contexto(hits), pregunta=pregunta, historial=historial)
    )


def _responder(pregunta: str, historial: str = "") -> str:
    k = int(args_globales.k) if args_globales else 14
    return responder(pregunta, historial, k=k)


def cmd_ask(args) -> int:
    store.init()
    with con.status("[cyan]buscando y razonando…[/]"):
        respuesta = _responder(" ".join(args.pregunta))
    con.print(Markdown(respuesta))
    return 0


def cmd_chat(args) -> int:
    store.init()
    con.print("[dim]Modo conversación. Ctrl+C o 'salir' para terminar.[/]")
    turnos: list[str] = []
    while True:
        try:
            pregunta = con.input("\n[bold cyan]tú >[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            return 0
        if pregunta.lower() in {"salir", "exit", "quit", ""}:
            return 0
        historial = ""
        if turnos:
            historial = "\n### Conversación previa\n" + "\n".join(turnos[-6:]) + "\n"
        with con.status("[cyan]pensando…[/]"):
            respuesta = _responder(pregunta, historial)
        con.print(Markdown(respuesta))
        turnos += [f"Usuario: {pregunta}", f"Tú: {respuesta[:500]}"]


def cmd_bot(args) -> int:
    import bot

    store.init()
    con.print(f"[bold]Motor:[/] {llm.describir()}")
    try:
        return bot.escuchar(
            canal=args.canal or "",
            intervalo=args.intervalo or 0,
            sync_cada=-1 if args.sync_cada is None else args.sync_cada,
            con=con,
        ) or 0
    except bot.SinConfigurar as exc:
        con.print(f"[yellow]{exc}[/]")
        return 1
    except KeyboardInterrupt:
        con.print()
        con.print("[dim]Bot parado.[/]")
        return 0


def cmd_proyectos(args) -> int:
    from connectors import trello

    if not trello.disponible():
        con.print("[yellow]Trello no esta configurado.[/] Faltan TRELLO_KEY y TRELLO_TOKEN.")
        return 1
    with con.status("[cyan]consultando Trello…[/]"):
        tableros = trello.inventario()

    # Sin porcentajes a proposito: un numero no sabe decir "en produccion y
    # mejorandose". Lo que se lee es lo que hay escrito en las subtareas.
    for b in tableros:
        por_empresa = {}
        for pr in b["proyectos"]:
            por_empresa.setdefault(pr["columna"], []).append(pr)
        if not por_empresa:
            continue
        con.print(f"\n[bold]{b['titulo']}[/]")
        for empresa, proyectos in sorted(por_empresa.items()):
            con.print(f"\n  [bold cyan]{empresa}[/]")
            for pr in sorted(proyectos, key=lambda x: x["nombre"]):
                marcas = pr["etiquetas"] + pr["campos"]
                etiq = ("  [magenta]" + " · ".join(marcas) + "[/]") if marcas else ""
                con.print(f"    [bold]{pr['nombre']}[/]{etiq}")
                if pr["pendientes"]:
                    for t in pr["pendientes"]:
                        con.print(f"      [yellow]○[/] {t}")
                elif pr["hechos"]:
                    con.print("      [green]todas las subtareas hechas[/]")
    con.print()
    return 0


def cmd_estado(args) -> int:
    store.init()
    con.print(f"[bold]Motor:[/] {llm.describir()}")
    con.print(f"[bold]Base:[/]  {store.DB_PATH}")

    tabla = Table(header_style="bold")
    tabla.add_column("Conector")
    tabla.add_column("Estado")
    tabla.add_column("Fragmentos", justify="right")
    inventario = store.counts()
    for nombre, _, _ in connectors.activos():
        tabla.add_row(nombre, "[green]listo[/]", str(inventario.get(nombre, 0)))
    for nombre, falta in connectors.inactivos():
        tabla.add_row(nombre, f"[yellow]sin configurar[/] · {falta}", str(inventario.get(nombre, 0)))
    con.print(tabla)
    return 0


def cmd_acta(args) -> int:
    import actas

    if args.audio:
        rutas = [pathlib.Path(r) for r in args.audio]
        faltan = [str(r) for r in rutas if not r.exists()]
        if faltan:
            con.print("[red]No encuentro:[/] " + ", ".join(faltan))
            return 1
    else:
        # Sin argumentos: lo que haya en la carpeta de grabaciones sin procesar.
        rutas = actas.pendientes()
        if not rutas:
            con.print(f"[yellow]No hay grabaciones nuevas en[/] {actas.DIR_GRABACIONES}")
            con.print("[dim]Configura esa carpeta como ruta de grabación en OBS.[/]")
            return 0
        if len(rutas) > 1:
            con.print(f"[cyan]{len(rutas)} grabaciones pendientes.[/] Proceso la más reciente:")
            for r in rutas[:-1]:
                con.print(f"[dim]  queda para luego: {r.name}[/]")
        rutas = [rutas[-1]]
        con.print(f"[cyan]Grabación:[/] {rutas[0].name}")

    # La fecha sale de la grabacion, no de cuando la proceses.
    fecha = args.fecha or actas.fecha_grabacion(rutas[0])
    titulo = args.titulo or f"Reunión {fecha}"

    try:
        with con.status("[cyan]transcribiendo en local (tarda; el audio no sale de aquí)…[/]"):
            transcripcion = actas.transcribir_varias(
                rutas,
                hablantes=[h.strip() for h in (args.hablantes or "").split(",") if h.strip()]
                or actas.HABLANTES,
            )
    except RuntimeError as exc:
        con.print(f"[yellow]{exc}[/]")
        return 1

    con.print(f"[green]✓[/] transcrito: {len(transcripcion.split())} palabras")

    with con.status("[cyan]redactando el acta…[/]"):
        acta = actas.redactar(transcripcion, varias_pistas=len(rutas) > 1)
    with con.status("[cyan]redactando el resumen…[/]"):
        resumen = actas.redactar_resumen(transcripcion)

    con.print(Markdown(acta))
    con.print()
    con.print("[dim]— resumen —[/]")
    con.print(Markdown(resumen))
    con.print()

    # Se publica ANTES de guardar: si el envio falla, el acta debe acabar en
    # docs/ para que al menos entre al indice por la via local.
    publicada = False
    if args.publicar:
        try:
            actas.publicar_discord(acta, titulo, fecha, args.canal or "")
            publicada = True
            con.print("[green]✓[/] acta publicada en #actas")
        except Exception as exc:  # noqa: BLE001
            con.print(f"[red]✗ no se pudo publicar el acta:[/] {exc}")
            con.print("[dim]  la guardo en docs/ para que no se pierda[/]")
        try:
            if actas.CANAL_RESUMENES:
                actas.publicar_discord(
                    resumen, f"{titulo} — resumen", fecha, actas.CANAL_RESUMENES
                )
                con.print("[green]✓[/] resumen publicado en #resumenes")
            else:
                con.print("[yellow]![/] falta DISCORD_RESUMENES_CANAL: el resumen no se publica")
        except Exception as exc:  # noqa: BLE001
            con.print(f"[red]✗ no se pudo publicar el resumen:[/] {exc}")

    ruta_acta, ruta_tr = actas.guardar(
        acta, transcripcion, titulo, fecha, indexar=not publicada
    )
    con.print(f"[green]✓[/] acta: {ruta_acta}")
    dentro = "indexada" if actas.INDEXAR_TRANSCRIPCIONES else "fuera del índice"
    con.print(f"[dim]  transcripción completa: {ruta_tr} — {dentro}[/]")
    if publicada:
        con.print("[dim]  fuera de docs/ a proposito: la indexa el canal de Discord[/]")

    if not args.audio:
        actas.marcar_hecha(rutas[0])
    con.print("[dim]Lanza `python askhub.py sync` para que entre en el índice.[/]")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    global args_globales
    p = argparse.ArgumentParser(description="Pregunta a todo tu espacio de trabajo, en local.")
    p.add_argument("-k", default="14", help="fragmentos de contexto a recuperar (por defecto 14)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="descarga e indexa (incremental)")
    s.add_argument("--solo", nargs="*", help="limita a ciertos conectores, ej: --solo trello")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("ask", help="una pregunta")
    s.add_argument("pregunta", nargs="+")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("acta", help="audio de una reunión -> acta indexable")
    s.add_argument("audio", nargs="*",
                   help="ficheros; sin nada, coge la grabación pendiente más reciente")
    s.add_argument("--titulo", help="título del acta")
    s.add_argument("--hablantes", help="nombres por orden de pista, ej: Ana,Daniel")
    s.add_argument("--fecha", help="YYYY-MM-DD (por defecto hoy)")
    s.add_argument("--publicar", action="store_true", help="publicarla en el canal de Discord")
    s.add_argument("--canal", help="id del canal; si no, DISCORD_ACTAS_CANAL")
    s.set_defaults(func=cmd_acta)

    sub.add_parser("chat", help="modo conversación").set_defaults(func=cmd_chat)
    s = sub.add_parser("bot", help="escucha el canal #preguntar de Discord y responde")
    s.add_argument("--canal", help="id del canal; si no, DISCORD_PREGUNTAR_CANAL")
    s.add_argument("--intervalo", type=float, help="segundos entre sondeos (5)")
    s.add_argument("--sync-cada", type=float, dest="sync_cada",
                   help="minutos entre syncs automaticos; 0 los desactiva")
    s.set_defaults(func=cmd_bot)

    sub.add_parser("proyectos", help="%% de avance por tablero").set_defaults(func=cmd_proyectos)
    sub.add_parser("estado", help="qué hay indexado y qué falta").set_defaults(func=cmd_estado)

    args = p.parse_args()
    args_globales = args

    # --- cable 1: identidad. askhub no corre de forma anónima. ---
    from custodia.identity import require_actor, MissingActor
    try:
        actor = require_actor()
    except MissingActor as e:
        print(f"askhub: {e}")
        return 2
    print(f"askhub: actor {actor}")
    llm.PASO = args.cmd  # cada evento del libro de custodia dice desde qué comando salió
    return args.func(args)


args_globales = None

if __name__ == "__main__":
    sys.exit(main())
