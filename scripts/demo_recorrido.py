"""Recorrido guiado de la demo (Issue #36): 5 preguntas curadas.

Cada item anota qué se espera mostrar. Ejecutar contra el stack local:

    uv run python -m scripts.demo_recorrido

Imprime pregunta respuesta y fuentes para ensayar antes de la demostración.
"""

from __future__ import annotations

from app.rag.query import query

DEMO = [
    {
        "pregunta": "¿Cuál es el plazo para denunciar un siniestro?",
        "esperado": "Cita interna a la cláusula de denuncia de un contrato (plazo y forma).",
    },
    {
        "pregunta": "¿Cuáles son las coberturas que ofrece la póliza de salud?",
        "esperado": "Bloques del contrato: coberturas otorgadas, riesgos cubiertos (Arts. 2/4/5).",
    },
    {
        "pregunta": "¿Qué limita la cobertura cuando hay preexistencias?",
        "esperado": "Cláusula de exclusiones / declaraciones de salud del corpus.",
    },
    {
        "pregunta": "¿Cuántos planes de isapre hay vigentes en Chile para 2026?",
        "esperado": "Mercado: fuente EXTERNA citada (2.274 planes, [fuente web: …]), marcada como web.",
    },
    {
        "pregunta": "¿Cuáles son los beneficios del plan de estadio del Banco de Chile?",
        "esperado": "Fuera de las fuentes: respuesta curada de alcance (sin inventar).",
    },
]


def main() -> None:
    for i, item in enumerate(DEMO, start=1):
        print("=" * 72)
        print(f"{i}. {item['pregunta']}")
        print(f"   -> esperado: {item['esperado']}")
        print("-" * 72)
        try:
            res = query(item["pregunta"])
        except Exception as exc:
            print(f"   ERROR: {type(exc).__name__}: {exc}")
            continue
        print(res["answer"])
        if res["sources"]:
            print("\n   Fuentes:")
            for s in res["sources"]:
                if s["origen"] == "poliza":
                    print(f"   - [póliza] {s['poliza']} · Art. {s['articulo']} · pág. {s.get('pagina')}")
                else:
                    print(f"   - [web] {s.get('titulo')} — {s['url']}")
        print()


if __name__ == "__main__":
    main()