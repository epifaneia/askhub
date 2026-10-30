# askhub

Pregunta en lenguaje natural a **todo** tu espacio de trabajo, desde tu máquina.
Sin servidor, sin Docker, sin cuota mensual. Coste: **0 €**.

```
python askhub.py sync                            # trae todo por API y lo indexa
python askhub.py ask "¿cómo va el rediseño?"     # pregunta
python askhub.py chat                            # conversación con memoria
python askhub.py proyectos                       # proyectos abiertos y subtareas pendientes
python askhub.py estado                          # qué hay indexado y qué falta
```

El equipo usa herramientas normales (Discord/Slack + Trello). **Solo tú** montas
esto: nadie más instala nada. Pero avisa al equipo de qué se indexa (canales, tableros,
actas) y adónde va: a Gemini por defecto, o a ningún sitio con Ollama.

---

## Las dos primeras patas: qué he elegido y por qué

No existe una herramienta gratuita que haga bien chat **y** tableros. Comprobado:

| Opción | Veredicto |
|---|---|
| **Discord** (chat) | ✅ Historial **ilimitado**, canales de foro = topics de verdad, bot y API gratis |
| **Slack** (chat) | ⚠️ Gratis pero **esconde lo anterior a 90 días** y solo deja 10 integraciones |
| **Trello** (proyectos) | ✅ Tarjetas ilimitadas, API gratis, 10 tableros y 10 colaboradores |
| ClickUp Free | ❌ Junta ambas cosas pero se queda en 100 MB de almacenamiento |
| Notion Free | ❌ Los invitados son **solo lectura**: tus compañeros no podrían tocar nada |

**Recomendación: Discord + Trello.** Si el equipo prefiere Slack, el conector ya
está escrito — con la ventaja de que askhub guarda copia local, así que **tu
índice conserva los mensajes que Slack te oculta a los 90 días**.

Trello no tiene % nativo, y askhub tampoco lo calcula, a propósito: un número
mezcla cuántas tareas con cuánto trabajo, y no sabe decir «está en producción y
se sigue mejorando». Se indexa lo que está escrito: columna, subtareas hechas y
pendientes, descripción; y el modelo lo cuenta con palabras.

## Instalación

Ninguna. `numpy`, `httpx` y `rich` ya los tienes; el resto es librería estándar.
La base de datos es un fichero `askhub.db` que se crea solo.

Pon tu `GEMINI_API_KEY` en `.env` (gratis en https://aistudio.google.com/apikey).

## Conectar Trello (2 min)

1. Entra en https://trello.com/power-ups/admin, crea un Power-Up cualquiera y copia la **API key**.
2. En esa misma página, enlace **Token** → autoriza → copia el token.
3. Pégalos en `.env`:

```
TRELLO_KEY=...
TRELLO_TOKEN=...
```

Si tus columnas de "terminado" se llaman distinto, añádelas a `TRELLO_DONE_LISTS`.

Whisper no sabe que "Reqif" existe y transcribe "RECIF"; tampoco conoce el nombre
de tu compañero. Asi que antes de transcribir se le pasan los nombres propios del propio
tablero, sacados del indice, mas lo que pongas en `WHISPER_VOCABULARIO` (personas,
clientes, siglas: eso no esta en Trello).

Si los nombres siguen saliendo mal con audio real, el otro boton es el modelo:
`WHISPER_MODEL=medium` o `large-v3`. Mas lento y ocupa mas, pero acierta mas.

### De donde sale el audio

Sin Teams Premium no hay transcripcion nativa, y meter un bot de terceros en una
reunion de cliente es otra conversacion. Para dos personas hay una via limpia:
**grabar dos pistas en local** -- tu microfono en una, el audio del sistema (la
otra persona) en otra. Con dos participantes eso es diarizacion perfecta y gratis.
OBS Studio lo hace con dos pistas en el mismo fichero: en *Ajustes -> Salida ->
modo Avanzado -> Grabacion* activas dos pistas, y en *Propiedades avanzadas de
audio* mandas el audio del escritorio a una y el microfono a la otra.

`acta` detecta los ficheros multipista y abre cada pista como una voz:

```
python askhub.py acta reunion.mkv --hablantes Ana,Daniel
```

O mejor: apunta la ruta de grabacion de OBS a `grabaciones/`, pon
`ACTA_HABLANTES=Ana, Daniel` en el `.env`, y despues de cada reunion basta con

```
python askhub.py acta --publicar
```

Coge la grabacion pendiente mas reciente, y lleva la cuenta de las ya
procesadas para no rehacer ni gastar transcripcion de mas.

Los nombres van por orden de pista. Sin `--hablantes` quedan como "pista1" y
"pista2", que sigue sirviendo: lo que importa es que el modelo sepa que son
personas distintas.

### O ninguno: si ya tienes la transcripcion

```
python askhub.py acta reunion.vtt --titulo "Semanal"
```

Traga `.txt`, `.vtt`, `.srt` y `.docx` (el .docx se lee sin dependencias). Da
igual si viene de Teams, de tl;dv o de Fathom: **lo que cambia es de donde sale
el texto, el acta la escribimos siempre nosotros** -- y por eso conoce tus
proyectos y tu marco de fases, cosa que un notetaker generico no puede saber.

Los planes gratuitos de tl;dv y Fathom dan transcripcion ilimitada y capan los
resumenes con IA. Regalan justo lo que necesitas y cobran lo unico que no.

## El bot de #preguntar

Un CLI en tu maquina solo te sirve a ti. Con el bot, la otra persona **no instala
nada**: pregunta en Discord y el bot responde desde el mismo indice.

```
python askhub.py bot
```

Escucha el canal de `DISCORD_PREGUNTAR_CANAL`, responde citando el mensaje
original, y cada 15 minutos hace un `sync` solo (`--sync-cada 0` lo desactiva).
No abre conexion de gateway: sondea por REST, asi que no hay dependencias nuevas.

Necesita que el bot tenga **Enviar mensajes** en ese canal, ademas de Ver canal
y Leer historial.

El precio de no pagar servidor: responde **mientras el proceso este corriendo**.
Si apagas el PC, deja de responder hasta que lo vuelvas a lanzar.

## Actas de reunion (la tercera pata)

Craig graba el canal de voz de Discord (`/join` y `/stop`, gratis, **una pista por
persona**, pero guarda el fichero solo 7 días: descárgalo). A partir de ahí:

```
pip install faster-whisper          # unica dependencia nueva, trae su ffmpeg
python askhub.py acta 1-dani.flac 2-companero.flac --titulo "Semanal" --publicar
```

Qué hace: transcribe **en local** (el audio no sale de tu máquina), redacta el
acta con Resumen / Decisiones / Tareas / Temas abiertos, la guarda en
`docs/actas/` — donde el conector de documentos la indexa sola — y con
`--publicar` la manda al canal `#actas`, troceada para el límite de Discord.

De cada reunión salen **dos textos, a dos canales**:

- **El acta**, a `#actas-de-reunion`: Resumen, Decisiones, Tareas, Temas abiertos.
  Tensa y operativa.
- **El resumen**, a `#resumenes-de-reunion`: prosa seguida con lo que esas cuatro
  cajas tirarían — ideas fuerza que no llevan a ninguna tarea, menciones de
  pasada a otros clientes, formas nuevas de enfocar algo. Su prompt tiene
  prohibido filtrar por relevancia: quien lee decide.

La fecha sale de **cuándo se grabó**, no de cuándo lo proceses: metadato del
contenedor, fecha en el nombre del fichero, o fecha del fichero, en ese orden.

La transcripción completa se guarda en `transcripciones/`, pero **no se indexa**.
El resumen en prosa ya recoge las ideas fuerza, y una hora de reunión con su paja
son unos ocho fragmentos de relleno compitiendo con lo bueno cada vez que el
buscador elige qué pasarle al modelo. El fichero queda por si hace falta; con
`INDEXAR_TRANSCRIPCIONES=1` vuelve a entrar al índice.

Reuniones largas: si la transcripción no cabe de una, se resume por tramos y
luego se unifican. No hay que hacer nada.

## Conectar Discord (5 min)

1. https://discord.com/developers/applications → **New Application**.
2. Pestaña **Bot** → **Reset Token** → copia el token a `DISCORD_BOT_TOKEN`.
3. En esa misma pestaña activa **MESSAGE CONTENT INTENT**. Sin esto el bot ve los
   mensajes vacíos: es el fallo clásico.
4. **OAuth2 → URL Generator** → marca `bot` y los permisos *View Channels* y
   *Read Message History* → abre la URL y mete el bot en tu servidor.

La primera sincronizacion se trae 1000 mensajes hacia atras por canal
(`DISCORD_BACKFILL`); a partir de ahi solo lo nuevo.

Los mensajes **no se indexan sueltos**: un "si, dale" no significa nada por su
cuenta y el hilo de la conversacion queda partido entre ocho fragmentos. Se
agrupan por conversacion -- mensajes seguidos del mismo canal, hasta que hay un
silencio de 30 minutos o se llega a 1500 caracteres -- y cada grupo se indexa
como una sola pieza, con la cabecera del canal una vez arriba.

Si la ultima conversacion sigue viva cuando toca sincronizar, el cursor
retrocede a su principio para que la siguiente vez se complete en lugar de
partirse. Releerla sale gratis: si no ha cambiado, el hash coincide y no se
recalcula el embedding.

## Pruebas

```
python pruebas/todas.py
```

No hacen ni una llamada de red: los servidores de Gemini, Discord y Trello van
falseados, asi que se pueden lanzar sin credenciales y sin gastar cuota.

## Conectar Slack (alternativa)

1. https://api.slack.com/apps → **Create New App** → From scratch.
2. **OAuth & Permissions** → Bot Token Scopes: `channels:history`, `channels:read`,
   `groups:history`, `groups:read`, `users:read`.
3. Instala en el workspace y copia el **Bot User OAuth Token** (`xoxb-…`) a `SLACK_BOT_TOKEN`.
4. Invita el bot a cada canal: `/invite @tu-bot`. Solo lee donde esté invitado.

## Documentos sueltos

Todo `.md`, `.txt`, `.csv` o `.json` que dejes en `askhub/docs/` entra en la
búsqueda. Es la vía rápida para actas, notas o especificaciones que no viven en
ninguna app.

## Sincronizar solo, cada hora

```powershell
schtasks /create /tn "askhub sync" /sc hourly ^
  /tr "cmd /c cd /d C:\ruta\a\askhub && python askhub.py sync"
```

O simplemente lánzalo a mano antes de preguntar: es incremental y tarda segundos.

## Qué cuesta esto

| Pieza | Coste |
|---|---|
| Discord / Slack / Trello | 0 € (planes gratuitos) |
| askhub en tu máquina | 0 € |
| Gemini capa gratuita | 0 €\* — límites por minuto y por día que Google cambia; desde abril de 2026 solo modelos Flash |
| Embeddings | 0 € en la capa gratuita, y solo se recalculan los fragmentos que cambian |

\* Comprobado el 29 de septiembre de 2026; sujeto a disponibilidad. Con Ollama no dependes de ningún plan.

Para 2-3 personas no te vas a acercar al límite. Si algún día lo rozas, subir a
pago son céntimos, no una cuota fija.

## Privacidad

El contenido que se indexa viaja a Google para calcular embeddings y respuestas.
Acordamos que aquí no va nada sensible. Si algún día lo hubiera, cambia una línea
del `.env` y deja de salir un solo byte de tu máquina:

```
LLM_BACKEND=ollama
```

(Necesita Ollama arrancado con un modelo de chat y `nomic-embed-text` para embeddings.)

## Cómo funciona

1. Cada conector saca datos por la API oficial y los normaliza a fragmentos.
2. Se calcula un hash de cada fragmento: **solo se re-embede lo que ha cambiado**.
3. Los vectores se guardan en SQLite; la búsqueda es coseno exacto con numpy
   (fuerza bruta, instantánea por debajo de ~100 000 fragmentos).
4. Los 14 fragmentos más cercanos se meten en el contexto del LLM con instrucción
   explícita de no inventar y de citar fuentes.

Cada tablero genera además un **fragmento de resumen** por cliente, con todos sus
proyectos abiertos y sus subtareas pendientes; por eso
"¿cómo va X?" funciona en lenguaje natural en vez de devolverte una lista de tarjetas.
