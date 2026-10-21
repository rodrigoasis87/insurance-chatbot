"""Logica pura de la evaluacion RAG (#19), sin dependencias de RAGAS ni de red.

Estas funciones son la parte deterministica y testeable del runner
``scripts/evaluate_ragas.py``:

* ``load_golden``: carga y valida el golden set curado.
* ``expected_hit``: ¿el articulo de referencia aparece entre los hits recuperados?
* ``cita_ok``: ¿las citas inline de la respuesta existen en las fuentes devueltas?

La parte con jueces LLM (RAGAS) y captura de contexto vive en el runner.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

POLICY_BEHAVIOR = "answer_from_policy"

# Comportamientos esperados por fila del golden set. Los ``abstain_*`` comparten
# que la respuesta correcta es abstenerse (NO_EN_FUENTES).
BEHAVIORS: tuple[str, ...] = (
    "answer_from_policy",
    "answer_from_web",
    "abstain_personal_information",
    "abstain_insufficient_information",
    "abstain_missing_information",
    "abstain_missing_contact",
)

# Campos obligatorios por fila; ``reference_contexts`` (solo póliza) y
# ``reference_sources`` (solo web) son opcionales segun el comportamiento.
REQUIRED_FIELDS = ("id", "question", "reference_answer", "expected_behavior")

# Cita interna: "[fuente: POL320200071 · Art. 13]" (separador U+00B7).
_CITA_POLIZA = re.compile(r"\[fuente:\s*([A-Za-z0-9]+)\s*·\s*Art\.?\s*(\d+)\s*\]")
# Cita web: "[fuente web: https://...]".
_CITA_WEB = re.compile(r"\[fuente\s+web:\s*(\S+?)\s*\]", re.IGNORECASE)


def load_golden(path: Path) -> list[dict[str, Any]]:
    """Lee el golden set ``.jsonl`` y valida cada fila.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: JSON invalido, campos faltantes, IDs duplicados o
            ``expected_behavior`` no reconocido.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el golden set: {path}")

    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSON invalido en linea {line_number}: {exc}"
                ) from exc
            missing = [field for field in REQUIRED_FIELDS if field not in row]
            if missing:
                raise ValueError(
                    f"Linea {line_number}: faltan campos {sorted(missing)}"
                )
            rows.append(row)

    if not rows:
        raise ValueError(f"El golden set esta vacio: {path}")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("El golden set contiene IDs duplicados")
    unknown = {row["expected_behavior"] for row in rows} - set(BEHAVIORS)
    if unknown:
        raise ValueError(f"expected_behavior no reconocido: {sorted(unknown)}")
    return rows


def cap_policy(
    rows: list[dict[str, Any]],
    max_policy: int | None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Acota los casos ``answer_from_policy`` a ``max_policy`` (muestra reproducible).

    Mantiene intactos el resto de comportamientos (abstención, web). Devuelve la
    lista original si ``max_policy`` es ``None`` o mayor/igual al número de casos
    de póliza. Los casos de póliza seleccionados van primero.

    Raises:
        ValueError: si ``max_policy`` es menor que 1.
    """
    if max_policy is None:
        return list(rows)
    if max_policy < 1:
        raise ValueError("max_policy debe ser al menos 1")
    policy = [r for r in rows if r["expected_behavior"] == POLICY_BEHAVIOR]
    others = [r for r in rows if r["expected_behavior"] != POLICY_BEHAVIOR]
    if max_policy < len(policy):
        policy = random.Random(seed).sample(policy, max_policy)
    return policy + others


def expected_hit(row: dict[str, Any], trace: dict[str, Any]) -> bool | None:
    """¿Alguno de los ``reference_contexts`` quedo entre los hits post-gate?

    Returns:
        ``True``/``False`` si la fila declara contextos de referencia, ``None``
        si no (p. ej. casos web o de abstencion).
    """
    expected = row.get("reference_contexts", [])
    if not expected:
        return None
    wanted = {
        (item.get("poliza"), item.get("documento"), item.get("articulo"))
        for item in expected
    }
    found = {
        (
            hit["metadata"].get("poliza"),
            hit["metadata"].get("documento"),
            hit["metadata"].get("articulo"),
        )
        for hit in trace.get("retrieval_hits", [])
    }
    return bool(wanted & found)


def cita_ok(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Valida que cada cita inline de ``answer`` exista en ``sources``.

    Citas internas ``[fuente: POL… · Art. N]`` deben corresponder a una fuente
    ``origen == "poliza"`` con el mismo ``poliza`` y ``articulo``; las web
    ``[fuente web: <url>]`` a una fuente ``origen == "web"`` con la misma URL.

    Returns:
        ``{"citadas", "validas", "ok", "rate", "detalle"}`` donde ``ok`` exige
        al menos una cita y que todas sean validas, y ``rate`` es ``None`` si no
        hubo citas (la fila no aporta al promedio).
    """
    polizas = {
        (str(source.get("poliza")), str(source.get("articulo")))
        for source in sources
        if source.get("origen") == "poliza"
    }
    webs = {
        str(source.get("url"))
        for source in sources
        if source.get("origen") == "web"
    }

    detalle: list[dict[str, Any]] = []
    for poliza, articulo in _CITA_POLIZA.findall(answer):
        detalle.append(
            {
                "tipo": "poliza",
                "cita": f"{poliza} · Art. {articulo}",
                "valida": (poliza, str(int(articulo))) in polizas,
            }
        )
    for url in _CITA_WEB.findall(answer):
        detalle.append({"tipo": "web", "cita": url, "valida": url in webs})

    citadas = len(detalle)
    validas = sum(1 for item in detalle if item["valida"])
    return {
        "citadas": citadas,
        "validas": validas,
        "ok": citadas > 0 and validas == citadas,
        "rate": (validas / citadas) if citadas else None,
        "detalle": detalle,
    }
