# askhub · Pregunta a todo tu espacio de trabajo, desde tu máquina

*Read this in [English](README.md).*

Un equipo pequeño trabaja con herramientas normales, Discord y Trello, y una persona monta esto en su portátil: un índice local de todo el chat, todas las tarjetas y las actas de reunión, y un bot que responde en un canal `#preguntar` al momento cómo va cada proyecto y qué falta. La otra persona no instala nada. Sin servidor, sin Docker, sin cuota mensual. Cero euros\*.

askhub es una pieza concreta de un ecosistema de trabajo completo: Discord para el chat, Trello para los proyectos, y esto en medio. Discord y Trello no son una elección técnica sino económica: sus planes gratuitos son generosos y el sistema queda limpio y completo. El resto son llamadas a herramientas que ya existen, y por eso es intercambiable: hay conector de Slack, y el mismo diseño se monta igual con piezas autoalojadas como Mattermost y Vikunja.

> La IA tiene riesgos. El código los acota. La norma responde de lo que queda.

[Filosofía de diseño](#filosofía-de-diseño) · [Dónde aporta valor la IA](#dónde-aporta-valor-la-ia) · [Los cinco pasos](#los-cinco-pasos-en-este-proyecto) · [Medido](#medido) · [Demo](#demo-en-cinco-comandos) · [Limitaciones](#limitaciones) · [Seguridad y regulación](#seguridad-y-regulación) · [Guía](docs/GUIA.md)

---

## Filosofía de diseño

Cualquier aplicación con IA tiene cinco pasos. Solo el paso 4 invoca un modelo; los otros cuatro son código: reproducibles, testeables, sin red. El paso 5 nunca corrige: marca y degrada. Texto completo en [epifaneia.dev](https://epifaneia.dev).

```
 1 LIMPIEZA      2 CONTEXTO      3 GUARDARRAÍL IN    4 PROCESO        5 GUARDARRAÍL OUT
 ■ código        ■ código        ■ código            ▲ modelo         ■ código
```

## Dónde aporta valor la IA

"¿En qué quedamos sobre el informe de agosto?" tiene la respuesta repartida entre un hilo de Discord de hace tres semanas, dos tarjetas de Trello y un acta que nadie volvió a abrir. Ninguna herramienta gratuita hace bien chat y tableros a la vez, y ningún copiloto integrado ve las dos cosas. El modelo hace lo único que solo un modelo puede hacer: leer los fragmentos recuperados y redactar la respuesta, o convertir una hora de reunión transcrita en un acta con decisiones y tareas. El código hace todo lo demás: qué entra al índice y cómo se agrupa, qué porcentaje lleva cada tablero, qué se le enseña al modelo, y que el acta y el resumen lleguen enteros, sin que la máquina decida qué era relevante.

---

## Los cinco pasos en este proyecto

★ marca dónde está la mejora en este proyecto: la **limpieza** y el **guardarraíl de salida**.

| Paso | Qué hace aquí | |
|---|---|---|
| 1 · Limpieza | Conectores de Discord (canales, foros e hilos, historial ilimitado), Trello (tarjetas y checklists), Slack como alternativa, y documentos sueltos de `docs/`. Los mensajes no se indexan sueltos: un "sí, dale" no significa nada; se agrupan en conversaciones por canal, con un corte por silencio de 24 horas o por tamaño, y cada grupo entra como una pieza con la cabecera del canal una vez. Las reuniones entran por audio: dos pistas de OBS, una por persona, transcritas en local con Whisper y con los nombres propios del tablero como vocabulario. | ★ |
| 2 · Contexto | Un solo fichero `askhub.db` (SQLite con vectores en numpy) para chat, tarjetas, actas y documentos. Sincronización incremental: solo se recalcula el embedding de lo que cambió, por hash; si la última conversación sigue viva, el cursor retrocede a su principio para completarla en la siguiente pasada. La transcripción completa se guarda pero no se indexa: una hora de reunión son ocho fragmentos de relleno compitiendo con lo bueno. | |
| 3 · Guardarraíl de entrada | El modelo recibe los fragmentos recuperados con su origen, y nada más. Los tokens de Discord y Trello los tiene el proceso de sincronización; el bot responde citando el mensaje original. | |
| 4 · Proceso | Una llamada por pregunta. Gemini en la capa gratuita por defecto, o Ollama en local con el mismo contrato; reintentos ante 429. Sin agentes. | |
| 5 · Guardarraíl de salida | El porcentaje de cada tablero lo calcula el código: tarjeta en columna de hecho o con vencimiento cumplido, 100; si no, el porcentaje de su checklist; el del tablero es la media. De cada reunión salen dos textos a dos canales: el acta con Resumen, Decisiones, Tareas y Temas abiertos, y un resumen en prosa con todo lo que esas cuatro cajas tirarían, cuyo prompt tiene prohibido filtrar por relevancia. Quien lee decide. La fecha del acta sale de cuándo se grabó, no de cuándo se procesó. | ★ |

## Medido

| Qué | Valor |
|---|---|
| Coste de funcionamiento | 0 € para dos o tres personas: planes gratuitos de Discord y Trello, capa gratuita de Gemini\*, embeddings solo de lo que cambia |
| Pruebas | `python pruebas/todas.py`: sin una sola llamada de red; Gemini, Discord y Trello van falseados |
| Transcripción | En local con faster-whisper (el audio no sale de la máquina), o Groq con whisper-large-v3-turbo a unas 220 veces tiempo real cuando el audio no es confidencial |
| Ruido evitado | Una hora de reunión transcrita son unos ocho fragmentos que ya no compiten con lo bueno al recuperar |
| Bot | Sondeo por REST cada 5 segundos, sincronización sola cada 15 minutos, sin conexión de gateway ni dependencia nueva |

\* Plan gratuito de Gemini comprobado el 29 de septiembre de 2026: existe, sin tarjeta, con límites por minuto y por día que Google cambia sin aviso, y desde abril de 2026 solo para los modelos Flash y Flash-Lite. Sujeto a disponibilidad. Con `LLM_BACKEND=ollama` no hay plan que dependa de nadie.

Lo que no está medido: la calidad de las respuestas contra un ground truth. Las pruebas cubren los conectores, el agrupado, las actas y el bot, no el acierto del modelo.

## Demo en cinco comandos

```bash
cp .env.example .env               # tokens de Discord y Trello, GEMINI_API_KEY o Ollama, CUSTODIA_ACTOR
python askhub.py sync              # trae todo por API y lo indexa (incremental)
python askhub.py ask "¿cómo va el rediseño?"
python askhub.py proyectos         # porcentaje de avance por tablero
python askhub.py bot               # responde en #preguntar de Discord mientras el proceso corre
```

`numpy`, `httpx` y `rich` bastan; `faster-whisper` solo para las actas. La guía completa de conexión de Discord, Trello, OBS y el bot está en [docs/GUIA.md](docs/GUIA.md). Este repositorio no lleva datos: `askhub.db`, actas, grabaciones y transcripciones están fuera de git.

## Limitaciones

- El bot responde mientras el proceso esté corriendo en la máquina de quien lo monta. Si se apaga el portátil, deja de responder hasta que se vuelva a lanzar. Es el precio de no pagar servidor.
- Gemini por defecto: la pregunta y los fragmentos recuperados salen de la máquina en cada consulta. Con `LLM_BACKEND=ollama` nada sale, más lento.
- Sin evaluación de la calidad de las respuestas ni de las actas contra ground truth.
- Trello no tiene porcentaje nativo: el cálculo es propio y depende de cómo se usen las columnas y las checklists.
- Dos personas y dos pistas es diarización perfecta; con más gente en una sola pista, Whisper no separa voces.
- La guía de instalación está solo en español.
- Identidad, eventos y firma van como contrato con un valor local por defecto (variable de entorno, fichero JSONL, clave HMAC). Los adaptadores al Entra ID, SIEM o PKI de una empresa no están aquí ni se pueden probar aquí: ver [docs/INTEGRATION.es.md](docs/INTEGRATION.es.md).

---

## Seguridad y regulación

Los mismos cuatro epígrafes en todos los repositorios. Las filas **hoy** son lo que hace el código. Las filas **cable** son los tres cables de integración que el repositorio trae como contrato (identidad, eventos, firma) y la empresa conecta a sus sistemas: ver [docs/INTEGRATION.es.md](docs/INTEGRATION.es.md). Pruebas locales: `python pruebas/todas.py`.

| | | |
|---|---|---|
| **Confidencialidad** | Índice, actas, grabaciones y transcripciones se quedan en la máquina y fuera de git. Whisper corre en local. Lo que sale a Gemini es la pregunta y los fragmentos recuperados para ella; con Ollama no sale nada. El bot solo lee los canales donde tiene permiso. | **hoy** |
| **Trazabilidad** | Cada fragmento lleva fuente, título, url y hash; el bot responde citando el mensaje original; cada acta guarda su transcripción completa aparte. `estado` dice qué hay indexado y qué falta. | **hoy** |
| | **Cable 2 · eventos.** Toda llamada a un modelo (chat, embeddings, transcripción en nube) pasa por `custodia/ledger`: una línea JSON con actor, paso, motor, endpoint, si el dato salió, tamaño y hash. Nunca el texto. `logs/custody.jsonl` o stdout. | **cable** |
| **Prevención de fugas** | El modelo no tiene credenciales; los tokens de Discord, Trello y Slack los tiene el proceso de sincronización, que solo lee. El bot no abre conexión de gateway. | **hoy** |
| | **Cable 1 · identidad.** `askhub.py` se niega a arrancar sin un actor con nombre (`custodia/identity`, por defecto `CUSTODIA_ACTOR`); el actor se estampa en cada evento y cada firma. La empresa sustituye el proveedor por Entra ID, LDAP, Kerberos o su SSO en una llamada. | **cable** |
| **Humano en el bucle** | El bot responde y cita; no crea ni cierra tarjetas. El acta se guarda antes de publicarse y el resumen en prosa no filtra por relevancia: quien lee decide qué importa. | **hoy** |
| | **Cable 3 · firma.** `tools/signoff.py sign docs/actas/<acta>.md` escribe el manifiesto (hash, actor, fecha, firma) y `verify` pasa; un acta cambiada o una clave distinta fallan. La empresa sustituye la clave HMAC local por su PKI registrando dos funciones. | **cable** |

Marco: EU AI Act (2024/1689) · RGPD · ISO/IEC 42001 · ISO/IEC 27001.

---

## Estructura

```
askhub.py        CLI: sync · ask · chat · bot · proyectos · estado · acta
bot.py           el bot de #preguntar (sondeo REST)
actas.py         audio → transcripción local → acta + resumen en prosa → índice y Discord
llm.py           Gemini o Ollama, mismo contrato; reintentos ante 429
store.py         askhub.db: SQLite + vectores en numpy
connectors/      discord · trello · slack · docs
pruebas/         todas.py y una prueba por pieza, sin red
docs/            GUIA.md · INTEGRATION.es.md · actas generadas (fuera de git)
custodia/        identity · ledger · signoff · cli  — los tres cables de integración
tools/signoff.py
```

Daniel Martín · [epifaneia.dev](https://epifaneia.dev) · Apache-2.0
