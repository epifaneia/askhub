"""Conectores: cada uno saca información de una app por su API y la normaliza.

Un conector devuelve una lista de fragmentos:
    {"id", "source", "title", "url", "content", "hash"}

Se activan solos según qué credenciales haya en el .env.
"""

import hashlib
import os

from . import discord, docs, slack, trello

# (nombre, módulo, purgar_lo_que_ya_no_existe)
# Los chats NO se purgan: si Slack esconde los mensajes de hace >90 días,
# tu copia local los conserva igual.
REGISTRO = [
    ("trello", trello, True),
    ("discord", discord, False),
    ("slack", slack, False),
    ("docs", docs, True),
]


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:32]


def activos() -> list:
    return [(n, m, p) for n, m, p in REGISTRO if m.disponible()]


def inactivos() -> list:
    return [(n, m.FALTA) for n, m, _ in REGISTRO if not m.disponible()]
