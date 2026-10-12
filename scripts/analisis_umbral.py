"""Mide la distribucion de scores de ``search()`` para fijar ``UMBRAL_SCORE``.

Corre las queries de ``QUERIES`` contra la coleccion indexada (requiere Qdrant
+ Ollama arriba) y vuelca el detalle crudo a ``data/processed/umbral_raw.json``
(gitignored). El resumen numerico se imprime en consola y la interpretacion
vive en ``docs/umbral_score.md``.

Uso:

    uv run python scripts/analisis_umbral.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paths import PROCESSED_DIR  # noqa: E402
from app.rag.vectordb import search  # noqa: E402

OUT = PROCESSED_DIR / "umbral_raw.json"

# Clase "dominio": pregunta contestable con las polizas, con el canonico que
# deberia ganar (ground truth). Clase "adyacente": del rubro salud/seguros pero
# NO contestable con el corpus. Clase "ajena": sin relacion con seguros.
QUERIES: list[dict] = [
    # --- dominio (relevante, con ground truth por canonico) ---
    {"clase": "dominio", "q": "¿Qué gastos médicos me reembolsa el seguro?", "canonico": "cobertura"},
    {"clase": "dominio", "q": "¿Cuánto tengo que esperar para que me cubran un parto?", "canonico": "carencia"},
    {"clase": "dominio", "q": "¿Qué operaciones estéticas no cubre la póliza?", "canonico": "exclusiones"},
    {"clase": "dominio", "q": "¿Dentro de qué plazo debo denunciar un siniestro?", "canonico": "denuncia de siniestro"},
    {"clase": "dominio", "q": "¿Cómo se calcula el monto que me van a reembolsar?", "canonico": "calculo de gastos"},
    {"clase": "dominio", "q": "¿Qué pasa si no pago la prima a tiempo?", "canonico": "primas"},
    {"clase": "dominio", "q": "¿A quién se le paga la indemnización si el asegurado muere?", "canonico": "beneficiarios"},
    {"clase": "dominio", "q": "¿Cuánto dura vigente el contrato de seguro?", "canonico": "vigencia"},
    {"clase": "dominio", "q": "¿Puede la compañía darme por terminada la póliza?", "canonico": "terminacion"},
    {"clase": "dominio", "q": "¿Qué obligaciones tiene el asegurado con la compañía?", "canonico": "obligaciones"},
    {"clase": "dominio", "q": "¿Qué pasa si el asegurado tiene otra póliza que cubre lo mismo?", "canonico": "otros seguros"},
    {"clase": "dominio", "q": "¿Me pagan dos veces si tengo dos seguros?", "canonico": "duplicacion de beneficios"},
    {"clase": "dominio", "q": "¿Cuál es la unidad monetaria en que está pactada la póliza?", "canonico": "unidad del contrato"},
    {"clase": "dominio", "q": "¿Qué debo hacer si quiero agregar a mi hijo a la póliza?", "canonico": "incorporacion"},
    {"clase": "dominio", "q": "¿Puedo retractarme después de firmar el contrato?", "canonico": "retracto"},
    {"clase": "dominio", "q": "¿Se puede rehabilitar la póliza después de un impago?", "canonico": "rehabilitacion"},
    {"clase": "dominio", "q": "¿Hay tope máximo de gastos que me reembolsan en el año?", "canonico": "monto maximo de reembolso"},
    {"clase": "dominio", "q": "¿Qué gastos no son reembolsables según el contrato?", "canonico": "exclusiones"},
    {"clase": "dominio", "q": "¿Qué pasa si mi estado de salud empeora y no lo aviso?", "canonico": "agravacion del riesgo"},
    {"clase": "dominio", "q": "¿Cómo se notifican las comunicaciones entre las partes?", "canonico": "comunicaciones"},
    {"clase": "dominio", "q": "¿Dónde debo vivir para que aplique el seguro?", "canonico": "pais de residencia"},
    {"clase": "dominio", "q": "¿Qué moneda se usa para calcular y pagar?", "canonico": "unidad del contrato"},
    {"clase": "dominio", "q": "¿Cuándo empieza a correr la cobertura para un asegurado nuevo?", "canonico": "cobertura"},
    {"clase": "dominio", "q": "¿Qué significan los términos usados en la póliza?", "canonico": "definiciones"},
    {"clase": "dominio", "q": "¿Qué pasa si el asegurado no dice toda la verdad al contratar?", "canonico": "declaraciones"},
    {"clase": "dominio", "q": "¿El seguro se hace cargo de los impuestos que genera?", "canonico": "impuestos"},
    # --- adyacente: del rubro, pero injuntable con el corpus ---
    {"clase": "adyacente", "q": "¿Cuál es el color del auto del asegurado?", "canonico": None},
    {"clase": "adyacente", "q": "¿Qué número de teléfono tengo que marcar para el servicio de urgencias?", "canonico": None},
    {"clase": "adyacente", "q": "¿Dónde queda la sucursal más cercana de la compañía?", "canonico": None},
    {"clase": "adyacente", "q": "¿Cuánto cuesta sacar turno con el cardiólogo que recomiendan?", "canonico": None},
    {"clase": "adyacente", "q": "¿Cuál es el nombre del médico de cabecera asignado a mi plan?", "canonico": None},
    {"clase": "adyacente", "q": "¿La póliza cubre a mi perro?", "canonico": None},
    {"clase": "adyacente", "q": "¿Me hacen descuento si pago todo el año por adelantado?", "canonico": None},
    {"clase": "adyacente", "q": "¿Puedo pagar con tarjeta de crédito americana?", "canonico": None},
    {"clase": "adyacente", "q": "¿Cuánto tarda la ambulancia?", "canonico": None},
    {"clase": "adyacente", "q": "¿Qué pasa con mi cobertura si me cambio de trabajo?", "canonico": None},
    {"clase": "adyacente", "q": "¿El seguro cubre los gimnasios?", "canonico": None},
    {"clase": "adyacente", "q": "¿Qué médico de urgencias atiende los domingos de madrugada?", "canonico": None},
    # --- ajena: sin relacion ---
    {"clase": "ajena", "q": "¿Quién ganó el mundial de 2022?", "canonico": None},
    {"clase": "ajena", "q": "¿Cómo se prepara un pan casero?", "canonico": None},
    {"clase": "ajena", "q": "¿Cuál es la capital de Australia?", "canonico": None},
    {"clase": "ajena", "q": "¿Qué es un agujero negro?", "canonico": None},
    {"clase": "ajena", "q": "¿Cuántos planetas hay en el sistema solar?", "canonico": None},
    {"clase": "ajena", "q": "¿Quién escribió Cien años de soledad?", "canonico": None},
]


def main() -> int:
    records: list[dict] = []
    for spec in QUERIES:
        hits = search(spec["q"], top_k=5)
        top = hits[0] if hits else None
        records.append(
            {
                "clase": spec["clase"],
                "q": spec["q"],
                "canonico_esperado": spec["canonico"],
                "scores": [h["score"] for h in hits],
                "top5_canonicos": [h["metadata"]["titulo_canonico"] for h in hits],
                "top1": (
                    {
                        "canonico": top["metadata"]["titulo_canonico"],
                        "poliza": top["metadata"]["poliza"],
                        "articulo": top["metadata"]["articulo"],
                    }
                    if top
                    else None
                ),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    def stats(vals: list[float]) -> str:
        if not vals:
            return "—"
        v = sorted(vals)
        n = len(v)
        p = lambda q: v[min(n - 1, max(0, int(q * (n - 1))))]
        return (
            f"n={n:>2} min={v[0]:.3f} p10={p(.1):.3f} p50={p(.5):.3f} "
            f"p90={p(.9):.3f} max={v[-1]:.3f}"
        )

    por_clase = {c: sum(1 for r in records if r["clase"] == c) for c in ("dominio", "adyacente", "ajena")}
    print(f"Escrito: {OUT} | dominio={por_clase['dominio']} adyacente={por_clase['adyacente']} ajena={por_clase['ajena']}")
    print("\nTop-1 score por clase:")
    for clase in ("dominio", "adyacente", "ajena"):
        print(f"  {clase:<10} {stats([r['scores'][0] for r in records if r['clase'] == clase])}")
    print("\nMax score (lo peor que un umbral tendria que dejar pasar):")
    for clase in ("dominio", "adyacente", "ajena"):
        print(f"  {clase:<10} {stats([max(r['scores']) for r in records if r['clase'] == clase])}")

    rel = [r for r in records if r["clase"] == "dominio"]
    hit1 = sum(1 for r in rel if r["canonico_esperado"] == r["top1"]["canonico"]) if rel else 0
    hit5 = sum(1 for r in rel if r["canonico_esperado"] in r["top5_canonicos"])
    print(f"\nHit@1 (canonico esperado en top-1): {hit1}/{len(rel)}")
    print(f"Hit@5 (canonico esperado en top-5): {hit5}/{len(rel)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())