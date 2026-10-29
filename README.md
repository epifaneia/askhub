# askhub · Ask your whole workspace, from your own machine

*Léelo en [español](README.es.md).*

A small team works with ordinary tools, Discord and Trello, and one person sets this up on their laptop: a local index of all the chat, all the cards and the meeting minutes, and a bot that answers in a `#preguntar` channel, on the spot, how each project is going and what is missing. The other person installs nothing. No server, no Docker, no monthly fee. Zero euros\*.

askhub is one concrete piece of a complete work ecosystem: Discord for chat, Trello for projects, and this in between. Discord and Trello are not a technical choice but an economic one: their free plans are generous and the system ends up clean and complete. The rest are calls to tools that already exist, which is why it is interchangeable: there is a Slack connector, and the same design works unchanged with self-hosted parts such as Mattermost and Vikunja.

> AI carries risk. Code bounds it. The standard answers for what remains.

[Design philosophy](#design-philosophy) · [Where AI adds value](#where-ai-adds-value) · [The five steps](#the-five-steps-in-this-project) · [Measured](#measured) · [Demo](#demo-in-five-commands) · [Limitations](#limitations) · [Security and regulation](#security-and-regulation) · [Guide (Spanish)](docs/GUIA.md)

---

## Design philosophy

Every AI application has five steps. Only step 4 invokes a model; the other four are code: reproducible, testable, offline. Step 5 never patches: it flags and degrades. Full text at [epifaneia.dev](https://epifaneia.dev).

```
 1 CLEANING      2 CONTEXT       3 INPUT GUARDRAIL   4 PROCESS        5 OUTPUT GUARDRAIL
 ■ code          ■ code          ■ code              ▲ model          ■ code
```

## Where AI adds value

"What did we agree about the August report?" has its answer spread across a Discord thread from three weeks ago, two Trello cards and minutes nobody opened again. No free tool does chat and boards well at the same time, and no integrated copilot sees both. The model does the only thing only a model can do: read the retrieved fragments and write the answer, or turn an hour of transcribed meeting into minutes with decisions and tasks. The code does everything else: what enters the index and how it is grouped, what percentage each board has, what the model is shown, and that the minutes and the summary arrive whole, without the machine deciding what was relevant.

---

## The five steps in this project

★ marks where the improvement lives in this project: **cleaning** and the **output guardrail**.

| Step | What it does here | |
|---|---|---|
| 1 · Cleaning | Connectors for Discord (channels, forums and threads, unlimited history), Trello (cards and checklists), Slack as an alternative, and loose documents from `docs/`. Messages are not indexed one by one: a "yes, go ahead" means nothing on its own; they are grouped into conversations per channel, cut by a 24-hour silence or by size, and each group enters as one piece with the channel header once. Meetings enter as audio: two OBS tracks, one per person, transcribed locally with Whisper using the board's proper names as vocabulary. | ★ |
| 2 · Context | One file, `askhub.db` (SQLite with numpy vectors), for chat, cards, minutes and documents. Incremental sync: only the embedding of what changed is recomputed, by hash; if the last conversation is still alive, the cursor moves back to its start so the next pass completes it. The full transcript is saved but not indexed: an hour of meeting is eight filler fragments competing with the good ones. | |
| 3 · Input guardrail | The model receives the retrieved fragments with their origin, and nothing else. The Discord and Trello tokens belong to the sync process; the bot answers quoting the original message. | |
| 4 · Process | One call per question. Gemini on the free tier by default, or Ollama locally under the same contract; retries on 429. No agents. | |
| 5 · Output guardrail | Each board's percentage is computed by code: a card in a done column or past its due date counts 100; otherwise its checklist percentage; the board's is the average. Every meeting yields two texts to two channels: the minutes with Summary, Decisions, Tasks and Open topics, and a prose summary with everything those four boxes would drop, whose prompt is forbidden from filtering by relevance. The reader decides. The minutes are dated by when the recording was made, not when it was processed. | ★ |

## Measured

| What | Value |
|---|---|
| Running cost | 0 € for two or three people: free Discord and Trello plans, Gemini free tier\*, embeddings only for what changes |
| Tests | `python pruebas/todas.py`: not a single network call; Gemini, Discord and Trello are faked |
| Transcription | Locally with faster-whisper (audio never leaves the machine), or Groq with whisper-large-v3-turbo at about 220× real time when the audio is not confidential |
| Noise avoided | An hour of transcribed meeting is about eight fragments that no longer compete with the good ones at retrieval |
| Bot | REST polling every 5 seconds, self-sync every 15 minutes, no gateway connection and no new dependency |

\* Gemini free tier checked on 29 September 2026: it exists, no card required, with per-minute and per-day limits that Google changes without notice, and since April 2026 only for the Flash and Flash-Lite models. Subject to availability. With `LLM_BACKEND=ollama` there is no plan that depends on anyone.

What is not measured: answer quality against a ground truth. The tests cover the connectors, the grouping, the minutes and the bot, not the model's accuracy.

## Demo in five commands

```bash
cp .env.example .env               # Discord and Trello tokens, GEMINI_API_KEY or Ollama, CUSTODIA_ACTOR
python askhub.py sync              # fetches everything over the APIs and indexes it (incremental)
python askhub.py ask "how is the redesign going?"
python askhub.py proyectos         # completion percentage per board
python askhub.py bot               # answers in Discord's #preguntar while the process runs
```

`numpy`, `httpx` and `rich` are enough; `faster-whisper` only for the minutes. The full guide for connecting Discord, Trello, OBS and the bot is in [docs/GUIA.md](docs/GUIA.md) (Spanish). This repository ships no data: `askhub.db`, minutes, recordings and transcripts are outside git.

## Limitations

- The bot answers while the process is running on the machine of whoever set it up. If the laptop is off, it stops answering until it is launched again. That is the price of not paying for a server.
- Gemini by default: the question and the retrieved fragments leave the machine on every query. With `LLM_BACKEND=ollama` nothing leaves, more slowly.
- No evaluation of answer or minutes quality against ground truth.
- Trello has no native percentage: the computation is ours and depends on how columns and checklists are used.
- Two people on two tracks is perfect diarisation; with more people on one track, Whisper does not separate voices.
- Whoever asks sees everything indexed. The bot answers anyone who writes in the questions channel with the whole index: channels that person cannot read, every Trello board the personal token opens, `docs/` and the minutes. It does not filter by the asker's permissions. It is meant for a small team (two or three people) who already share the same access; for anything wider, results would have to be filtered by the asker's Discord roles first.
- The setup guide is in Spanish only.
- Identity, events and sign-off ship as a contract with a local default (environment variable, JSONL file, HMAC key). The adapters to a company's Entra ID, SIEM or PKI are not here and cannot be tested here: see [docs/INTEGRATION.md](docs/INTEGRATION.md).

---

## Security and regulation

The same four headings in every repository. **today** rows are what the code does. **wire** rows are the three integration wires the repository ships as a contract (identity, events, sign-off) that the company connects to its own systems: see [docs/INTEGRATION.md](docs/INTEGRATION.md). Local tests: `python pruebas/todas.py`.

| | | |
|---|---|---|
| **Confidentiality** | Index, minutes, recordings and transcripts stay on the machine and outside git. Whisper runs locally. What goes to Gemini is the question and the fragments retrieved for it; with Ollama nothing leaves. The bot only reads the channels it has permission for, but answers from all of them to anyone in the questions channel: see Limitations. | **today** |
| **Traceability** | Every fragment carries source, title, url and hash; the bot answers quoting the original message; every set of minutes keeps its full transcript aside. `estado` reports what is indexed and what is missing. | **today** |
| | **Wire 2 · events.** Every model call (chat, embeddings, cloud transcription) goes through `custodia/ledger`: one JSON line with actor, step, engine, endpoint, whether data left, size and hash. Never the text. `logs/custody.jsonl` or stdout. | **wire** |
| **Leak prevention** | The model has no credentials; the Discord, Trello and Slack tokens belong to the sync process, which only reads. The bot opens no gateway connection. | **today** |
| | **Wire 1 · identity.** `askhub.py` refuses to start without a named actor (`custodia/identity`, by default `CUSTODIA_ACTOR`); the actor is stamped on every event and every signature. The company replaces the provider with Entra ID, LDAP, Kerberos or its SSO in one call. | **wire** |
| **Human in the loop** | The bot answers and quotes; it creates and closes no cards. The minutes are saved before being published and the prose summary does not filter by relevance: the reader decides what matters. | **today** |
| | **Wire 3 · sign-off.** `tools/signoff.py sign docs/actas/<minutes>.md` writes the manifest (hash, actor, date, signature) and `verify` passes; changed minutes or a different key fail. The company replaces the local HMAC key with its PKI by registering two functions. | **wire** |

Framework: EU AI Act (2024/1689) · GDPR · ISO/IEC 42001 · ISO/IEC 27001.

---

## Structure

```
askhub.py        CLI: sync · ask · chat · bot · proyectos · estado · acta
bot.py           the #preguntar bot (REST polling)
actas.py         audio → local transcription → minutes + prose summary → index and Discord
llm.py           Gemini or Ollama, same contract; retries on 429
store.py         askhub.db: SQLite + numpy vectors
connectors/      discord · trello · slack · docs
pruebas/         todas.py and one test per piece, no network
docs/            GUIA.md · INTEGRATION.md · generated minutes (outside git)
custodia/        identity · ledger · signoff · cli  — the three integration wires
tools/signoff.py
```

Daniel Martín · [epifaneia.dev](https://epifaneia.dev) · Apache-2.0
