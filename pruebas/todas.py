"""Lanza todas las pruebas: python pruebas/todas.py"""

import os
import pathlib
import subprocess
import sys
import tempfile

AQUI = pathlib.Path(__file__).resolve().parent

# Custodia: ninguna prueba pasa por askhub.main(), asi que el actor no es
# obligatorio, pero se fija por si alguna lo necesita; y las que tocan llm._post
# escriben en el libro de custodia, que no debe ensuciar el repo.
env = dict(os.environ, PYTHONIOENCODING="utf-8")
env.setdefault("CUSTODIA_ACTOR", "prueba")
env.setdefault("CUSTODIA_LEDGER", str(pathlib.Path(tempfile.mkdtemp(prefix="askhub_pruebas_")) / "custody.jsonl"))
sys.stdout.reconfigure(errors="replace")

fallos = 0
for prueba in sorted(AQUI.glob("test_*.py")):
    print(f"===== {prueba.stem} =====")
    r = subprocess.run([sys.executable, str(prueba)], capture_output=True, text=True,
                       encoding="utf-8", env=env)
    print(r.stdout.strip() or r.stderr.strip())
    # test_custodia.py viene del toolkit de custodia y remata con "TODO OK".
    if "todo bien" not in r.stdout and "TODO OK" not in r.stdout:
        fallos += 1
print()
print("TODO VERDE" if not fallos else f"{fallos} ficheros con fallos")
sys.exit(1 if fallos else 0)
