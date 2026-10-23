"""CLI entrypoint para recombinación DEM demo v0 (#36).

Permite ejecutar la recombinación desde la terminal:
    uv run python -m app.generation.dem --molde POL320200071 --perfil '{"edad":"30-40",...}'
o también:
    uv run python -m app.generation --molde POL320200071 --perfil '{"edad":"30-40",...}'
"""

from __future__ import annotations

import sys

from app.generation.dem import main

if __name__ == "__main__":
    sys.exit(main())
