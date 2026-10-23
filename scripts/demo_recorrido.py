r"""Recorrido guiado de la demo (Issue #36): 5 preguntas curadas + generación DEM.

Cada item anota qué se espera mostrar. Ejecutar contra el stack local:

    uv run python -m scripts.demo_recorrido

Imprime pregunta respuesta y fuentes para ensayar antes de la demostración.
El paso 6 (Recombinación DEM · §4.1) corre contra el API en :8000, así que la
demo completa necesita el stack levantado (`docker compose up -d api qdrant ollama`).

Auth (#44): si ``API_KEY`` está en el ``.env`` el paso 6 manda ``X-API-Key``.
Equivalente con curl (exportá la key en tu shell; ``/health`` no la pide):

    curl -X POST localhost:8000/policy-recombine \
      -H 'Content-Type: application/json' -H "X-API-Key: $API_KEY" \
      -d '{"molde":"POL320200071","perfil":{"edad":"30-40","preexistencias":"no",
           "deportes_riesgo":"no","fonasa_isapre":"isapre","embarazo":"no",
           "cronicas":"no","colectivo":"no","residencia":"chile"}}'
"""

from __future__ import annotations

import httpx

from app.rag.config import get_settings
from app.rag.query import query

API_URL = "http://localhost:8000"
API_KEY_HEADER = "X-API-Key"

# Perfil curado sin PII (docs/CONTRACTS.md §4.1) sobre el molde base del catálogo.
MOLDE_DEM = "POL320200071"
PERFIL_DEM = {
    "edad": "30-40",
    "preexistencias": "no",
    "deportes_riesgo": "no",
    "fonasa_isapre": "isapre",
    "embarazo": "no",
    "cronicas": "no",
    "colectivo": "no",
    "residencia": "chile",
}

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


def _auth_headers() -> dict[str, str]:
    """Header ``X-API-Key`` con ``API_KEY`` del ``.env`` (vacío = modo dev sin auth)."""
    api_key = get_settings().api_key
    return {API_KEY_HEADER: api_key} if api_key else {}


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
    paso_generacion()


def paso_generacion() -> None:
    """Paso 6: recombinación DEM v0 (#36) vía POST /policy-recombine (§4.1)."""
    print("=" * 72)
    print("6. [Generación] Recombinación DEM demo v0 (#36)")
    print("   -> molde base + perfil curado -> borrador DEM (JSON §4.1 + PDF)")
    print("-" * 72)
    try:
        resp = httpx.post(
            f"{API_URL}/policy-recombine",
            json={"molde": MOLDE_DEM, "perfil": PERFIL_DEM},
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.ConnectError as exc:
        print(f"   ERROR: el API no responde en {API_URL}. Levantá el stack:")
        print("          docker compose up -d api qdrant ollama")
        print(f"          ({type(exc).__name__})")
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            print("   ERROR 401: el API exige X-API-Key. Definí en el .env la misma")
            print("          API_KEY que usa el API.")
            return
        print(f"   ERROR {exc.response.status_code}: {exc.response.text}")
        return

    payload = resp.json()
    print(f"   {payload['codigo']}  ·  molde_base: {payload['molde_base']}")
    print(f"   creado_en: {payload['creado_en']}")
    print(f"   perfil: {payload['perfil']}")
    print("\n   Secciones de cláusulas (con cita de origen del molde):")
    for s in payload["secciones"]:
        print(f"   - {s['titulo']}  [perfil: {s['perfil']} · pág. {s['pagina']}]")
    print(f"\n   pdf_url: http://localhost:8000{payload['pdf_url']}")
    print(f"   aviso: {payload['aviso']}")
    print()


if __name__ == "__main__":
    main()