"""Abre o Financeiro Métodos a partir do código: ``python main.py``.

Reaproveita o mesmo ponto de entrada do executável (``honorarios.app.main``);
funciona mesmo sem ``pip install -e .``, porque põe a pasta ``src`` no caminho.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from honorarios.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
