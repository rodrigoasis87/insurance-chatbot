"""Re-score offline de una corrida del eval: recalcula ``cita_ok`` con el codigo actual.

No hace red ni llama al juez LLM: solo relee el ``results.jsonl`` de una corrida
guardada y revalida las citas inline de cada respuesta contra las fuentes que ya
quedaron registradas. Sirve para dos cosas:

* corregir la metrica de trazabilidad de corridas anteriores tras un fix del
  validador (``app/rag/eval.py``), sin volver a gastar API;
* auditar la trazabilidad de una corrida existente (cuantas filas cited, cuantas
  citas verificables) en modo offline, reproducible.

Uso:
    uv run python scripts/rescore_citas.py data/evaluation/results/<run_id>
    uv run python scripts/rescore_citas.py data/evaluation/results/<run_id> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.eval import cita_ok  # noqa: E402


def _load_rows(run_dir: Path) -> list[dict[str, Any]]:
    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        raise SystemExit(f"no existe {results_path}")
    rows = []
    with results_path.open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _ragas_means(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    means: dict[str, float | None] = {}
    metric_names = sorted(
        {
            metric
            for row in rows
            for metric in (row.get("ragas") or {})
            if (row.get("ragas") or {}).get(metric) is not None
        }
    )
    for metric in metric_names:
        values = [
            row["ragas"][metric]
            for row in rows
            if (row.get("ragas") or {}).get(metric) is not None
        ]
        means[metric] = mean(values) if values else None
    return means


def rescore(run_dir: Path) -> dict[str, Any]:
    """Recalcula ``cita_ok`` para cada fila y devuelve el agregado."""
    rows = _load_rows(run_dir)
    detalle: list[dict[str, Any]] = []
    for row in rows:
        citations = cita_ok(row.get("answer", ""), row.get("sources", []))
        detalle.append(
            {
                "id": row.get("id"),
                "expected_behavior": row.get("expected_behavior"),
                "actual_route": row.get("actual_route"),
                "cita_ok_registrado": row.get("cita_ok"),
                "cita_ok_rate_registrado": row.get("cita_ok_rate"),
                "cita_ok": citations["ok"],
                "cita_ok_rate": citations["rate"],
                "citas": citations["citadas"],
                "citas_validas": citations["validas"],
            }
        )

    con_cita = [item for item in detalle if item["citas"] > 0]
    citas = sum(item["citas"] for item in detalle)
    validas = sum(item["citas_validas"] for item in detalle)
    run_meta: dict[str, Any] = {}
    run_json = run_dir / "run.json"
    if run_json.exists():
        run_meta = json.loads(run_json.read_text(encoding="utf-8"))

    return {
        "run_dir": str(run_dir),
        "run_metadata": run_meta,
        "n_rows": len(detalle),
        "rows_con_cita": len(con_cita),
        "rows_cita_ok": sum(1 for item in detalle if item["cita_ok"]),
        "citas_totales": citas,
        "citas_validas": validas,
        "citas_invalidas": citas - validas,
        "cita_ok_registrado": sum(
            1 for item in detalle if item["cita_ok_registrado"]
        ),
        "ragas_means": _ragas_means(rows),
        "detalle": detalle,
    }


def _render(resumen: dict[str, Any]) -> str:
    lines = [
        f"corrida: {resumen['run_dir']}",
        "",
        f"{'id':<12} {'behavior':<22} {'route':<8} {'registrado':>10} "
        f"{'recalculado':>12} {'citas':>6} {'validas':>8}",
    ]
    for item in resumen["detalle"]:
        lines.append(
            f"{str(item['id']):<12} {str(item['expected_behavior']):<22} "
            f"{str(item['actual_route']):<8} "
            f"{str(item['cita_ok_registrado']):>10} "
            f"{str(item['cita_ok']):>12} "
            f"{item['citas']:>6} {item['citas_validas']:>8}"
        )
    meta = resumen["run_metadata"]
    if meta:
        lines += [
            "",
            "metadata: "
            f"generador={meta.get('generator_provider')}/{meta.get('generator_model')} "
            f"juez={meta.get('judge_provider')}/{meta.get('judge_model')} "
            f"commit={str(meta.get('git_commit'))[:7]} "
            f"corpus={str(meta.get('corpus_sha256'))[:12]} "
            f"umbral={meta.get('score_threshold')} top_k={meta.get('top_k')}",
        ]
    lines += [
        "",
        f"filas: {resumen['n_rows']} | filas con cita: {resumen['rows_con_cita']} "
        f"| cita_ok (recalculado): {resumen['rows_cita_ok']}/{resumen['n_rows']} "
        f"| cita_ok (registrado): {resumen['cita_ok_registrado']}/{resumen['n_rows']}",
        f"citas: {resumen['citas_totales']} "
        f"| válidas: {resumen['citas_validas']} "
        f"| inválidas: {resumen['citas_invalidas']}",
    ]
    if resumen["ragas_means"]:
        lines.append(
            "medias RAGAS: "
            + " | ".join(
                f"{name}={value:.3f}"
                for name, value in resumen["ragas_means"].items()
                if value is not None
            )
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="carpeta de la corrida")
    parser.add_argument(
        "--json", action="store_true", help="imprime el agregado en JSON"
    )
    args = parser.parse_args()

    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    resumen = rescore(run_dir)
    (run_dir / "rescore.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(resumen, ensure_ascii=False, indent=2))
    else:
        print(_render(resumen))
    print(f"\nrescore.json escrito en {run_dir / 'rescore.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
