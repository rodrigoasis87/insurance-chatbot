"""Prueba de la busqueda web del Issue #8 contra el buscador real.

Necesita internet (es la unica pieza del stack que lo usa). No necesita
Docker, Ollama ni Qdrant.

1. Busquedas reales del rubro: assert del shape ``{titulo, url, snippet}``,
   URLs http(s) y tope ``max_results``.
2. Fuentes para #17: ``to_sources()`` (``origen: "web"``) y el bloque de
   ``format_web_context()`` con la cita ``[fuente web: <dominio>]``.
3. Fallback controlado: red caida (cliente real con un proxy que no existe),
   timeout y rate limit simulados. Debe devolver ``[]`` y un mensaje, nunca
   lanzar excepcion.

Sale con codigo 1 si algo falla. Los tests unitarios (sin red) estan en
tests/test_rag_web_search.py.

Uso:
    uv run python scripts/test_search.py
    uv run python scripts/test_search.py --query "tope de reembolso seguro catastrofico" --max-results 3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

# El proyecto no se instala como paquete: agregamos la raiz al sys.path para
# poder correr "uv run python scripts/test_search.py" desde la raiz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ddgs import DDGS  # noqa: E402
from ddgs.exceptions import RatelimitException, TimeoutException  # noqa: E402

import app.rag.web_search as ws  # noqa: E402
from app.rag.web_search import (  # noqa: E402
    format_web_context,
    to_sources,
    web_search,
    web_search_with_status,
)

# Preguntas del dominio que el corpus no responde (precios, normativa, mercado).
QUERIES: list[str] = [
    "precio seguro complementario de salud Chile",
    "CMF norma de carácter general 349 depósito de pólizas",
    "qué cubre un seguro catastrófico de salud Chile",
    "requisitos seguro de accidentes personales Chile",
]
# Pausa entre busquedas reales. Con rafagas (pausa ~1 s) los buscadores empiezan
# a devolver vacio sin avisar y ddgs lo reporta como "No results found".
PAUSE_S = 3.0
# Puerto local donde no escucha nadie: la conexion se rechaza al instante.
DEAD_PROXY = "http://127.0.0.1:9"
EXPECTED_KEYS = {"titulo", "url", "snippet"}


def check_shape(results: list[dict[str, str]], max_results: int) -> list[str]:
    """Valida el contrato de cada resultado. Devuelve los problemas encontrados."""
    problems: list[str] = []
    if len(results) > max_results:
        problems.append(f"{len(results)} resultados > max_results={max_results}")
    for r in results:
        if set(r) != EXPECTED_KEYS:
            problems.append(f"claves {sorted(r)} != {sorted(EXPECTED_KEYS)}")
        elif not all(isinstance(v, str) for v in r.values()):
            problems.append(f"valores no str en {r['url']!r}")
        elif not r["url"].startswith(("http://", "https://")):
            problems.append(f"url no http(s): {r['url']!r}")
        elif not r["titulo"]:
            problems.append(f"titulo vacio en {r['url']!r}")
    return problems


def check_live(queries: list[str], max_results: int) -> tuple[list[str], list[dict[str, str]]]:
    """Corre busquedas reales.

    Una consulta sin resultados es un aviso (el buscador varia); que ninguna
    traiga resultados es un fallo.

    Returns:
        ``(fallos, resultados de la primera consulta con resultados)``.
    """
    failures: list[str] = []
    first_hit: list[dict[str, str]] = []
    hits = 0

    print(f"     {'consulta':<56} {'n':>2}  {'seg':>4}  dominios")
    for i, query in enumerate(queries):
        if i:
            time.sleep(PAUSE_S)
        start = time.perf_counter()
        results, message = web_search_with_status(query, max_results)
        elapsed = time.perf_counter() - start

        problems = check_shape(results, max_results)
        failures += [f"shape: {query!r}: {p}" for p in problems]
        if results:
            hits += 1
            first_hit = first_hit or results
        domains = ", ".join(ws.web_domain(r["url"]) for r in results) or f"({message})"
        status = "FAIL" if problems else ("OK  " if results else "WARN")
        print(f"{status} {query[:56]:<56} {len(results):>2}  {elapsed:>4.1f}  {domains[:70]}")

    print()
    if hits == 0:
        failures.append(
            "ninguna busqueda devolvio resultados. Revisa la conexion a internet "
            "o espera unos minutos (rate limit)."
        )
    elif not failures:
        print(f"[OK] busqueda real: {hits}/{len(queries)} consultas con resultados y shape correcto")
    return failures, first_hit


def check_sources(results: list[dict[str, str]]) -> list[str]:
    """Muestra y valida lo que recibiria query() de #17 con resultados reales."""
    if not results:
        return []
    failures: list[str] = []

    sources = to_sources(results)
    for s in sources:
        if s.get("origen") != "web" or set(s) != {"origen", "url", "titulo"}:
            failures.append(f"to_sources: entrada fuera de contrato {s}")

    context = format_web_context(results)
    for r in results:
        tag = f"[fuente web: {ws.web_domain(r['url'])}]"
        if tag not in context:
            failures.append(f"format_web_context: falta la cita {tag}")
    if "[fuente: POL" in context:
        failures.append("format_web_context: el bloque web parece una cita de poliza")

    print("     Bloque para el prompt (format_web_context):")
    for line in context.splitlines():
        print(f"       {line[:110]}")
    print("\n     sources[] (to_sources):")
    for s in sources:
        print(f"       {s}")
    print()
    if not failures:
        print("[OK] fuentes web: origen 'web' + url en sources y cita [fuente web: <dominio>] marcada")
    return failures


class _Raises:
    """Buscador falso que siempre lanza ``error`` (imita ``DDGS.text``)."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def text(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        raise self.error


def check_fallback() -> list[str]:
    """La tool nunca rompe el pipeline: ``[]`` + mensaje legible en cada falla."""
    failures: list[str] = []
    cases: list[tuple[str, Any, str]] = [
        # Red caida real: el cliente de verdad no logra conectarse.
        ("red caida", lambda **_: DDGS(proxy=DEAD_PROXY, timeout=3), ws.MSG_UNAVAILABLE),
        ("timeout", lambda **_: _Raises(TimeoutException("timed out")), ws.MSG_TIMEOUT),
        ("rate limit", lambda **_: _Raises(RatelimitException("202")), ws.MSG_RATELIMIT),
    ]
    for name, factory, expected in cases:
        # Se reemplaza el cliente por defecto para probar web_search() tal como
        # la llamara query(), sin parametros extra. Los warnings de estas fallas
        # son esperados: se silencian para no ensuciar la salida.
        with mock.patch.object(ws, "DDGS", factory), mock.patch.object(ws.logger, "disabled", True):
            try:
                results = web_search("precio seguro complementario de salud Chile")
                _, message = web_search_with_status("precio seguro complementario de salud Chile")
            except Exception as exc:
                failures.append(f"fallback {name}: lanzo {exc!r} (debe devolver [])")
                print(f"FAIL {name:<11} lanzo {type(exc).__name__}")
                continue
        ok = results == [] and message == expected
        if not ok:
            failures.append(f"fallback {name}: devolvio {results!r} / {message!r}")
        print(f"{'OK  ' if ok else 'FAIL'} {name:<11} -> [] + {message!r}")

    print()
    if not failures:
        print("[OK] fallback: red caida, timeout y rate limit devuelven [] sin romper")
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Lee las opciones de la linea de comandos (ver ``--help``)."""
    parser = argparse.ArgumentParser(description="Prueba de la busqueda web del Issue #8.")
    parser.add_argument(
        "--query",
        action="append",
        help="consulta propia (se puede repetir); reemplaza las de ejemplo",
    )
    parser.add_argument("--max-results", type=int, default=ws.DEFAULT_MAX_RESULTS)
    parser.add_argument(
        "--skip-live", action="store_true", help="solo probar el fallback (sin internet)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Corre los chequeos en orden e imprime OK o FAIL por cada uno.

    Returns:
        0 si todo pasa, 1 si algun chequeo falla.
    """
    args = parse_args(argv)

    print("== Test de busqueda web (Issue #8) ==")
    print(f"ddgs: region={ws.REGION} backend={ws.BACKEND} timeout={ws.TIMEOUT_S}s\n")

    failures: list[str] = []
    if not args.skip_live:
        live_failures, first_hit = check_live(args.query or QUERIES, args.max_results)
        failures += live_failures
        failures += check_sources(first_hit)
    failures += check_fallback()

    if failures:
        print(f"\nRESULTADO: FALLO ({len(failures)} problema/s)")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nRESULTADO: OK - busqueda web validada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
