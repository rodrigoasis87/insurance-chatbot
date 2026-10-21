"""Run the curated local RAG evaluation and save a reproducible report.

Usage:
    uv run --group eval python scripts/evaluate_ragas.py --limit 1
    uv run --group eval python scripts/evaluate_ragas.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import subprocess
import sys
import types
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.config import get_settings  # noqa: E402
from app.rag.eval import (  # noqa: E402
    BEHAVIORS,
    cap_policy,
    cita_ok,
    expected_hit,
    load_golden,
)
from app.rag.llm import get_llm  # noqa: E402
from app.rag.query import NO_EN_FUENTES, query  # noqa: E402
from app.rag.vectordb import get_client, search  # noqa: E402
from app.rag.web_search import web_search  # noqa: E402

GOLDEN_PATH = ROOT / "data/evaluation/ragas_golden.jsonl"
RESULTS_ROOT = ROOT / "data/evaluation/results"
REPORT_DOC = ROOT / "docs/eval/LATEST.md"


def _progress(message: str) -> None:
    """Print an unbuffered progress line for long local model operations."""
    stamp = datetime.now().astimezone().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def _load_ragas():
    """Import RAGAS 0.4.x with a shim for its unused legacy VertexAI import.

    RAGAS 0.4.3 imports this optional integration unconditionally, although
    this evaluator uses only Ollama. langchain-community 0.4.2 removed the old
    module. Provide a placeholder class solely for RAGAS's isinstance list;
    no VertexAI client or request is created.
    """
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

    import langchain_community.chat_models as chat_models

    module_name = "langchain_community.chat_models.vertexai"
    module = types.ModuleType(module_name)
    module.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules[module_name] = module
    chat_models.vertexai = module

    import ragas
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    return ragas, AsyncOpenAI, llm_factory, {
        "faithfulness": Faithfulness,
        "context_recall": ContextRecall,
        "context_precision": ContextPrecisionWithReference,
    }


async def _score_policy_answer(
    row: dict[str, Any],
    response: str,
    contexts: list[str],
    metrics: dict[str, Any],
    metric_names: list[str],
) -> dict[str, Any]:
    if not contexts:
        return {"skipped": "sin contextos posteriores al hard gate"}
    scores: dict[str, Any] = {}
    for name in metric_names:
        metric = metrics[name]
        _progress(f"juez RAGAS: iniciando {name}")
        metric_started = time.monotonic()
        try:
            if name == "faithfulness":
                result = await metric.ascore(
                    user_input=row["question"],
                    response=response,
                    retrieved_contexts=contexts,
                )
            else:
                result = await metric.ascore(
                    user_input=row["question"],
                    reference=row["reference_answer"],
                    retrieved_contexts=contexts,
                )
            scores[name] = result.value
            _progress(
                f"juez RAGAS: {name} = {result.value} "
                f"({time.monotonic() - metric_started:.1f} s)"
            )
        except Exception as exc:  # Keep other metric scores and questions usable.
            scores[name] = {"error": f"{type(exc).__name__}: {exc}"}
            _progress(
                f"juez RAGAS: {name} falló tras "
                f"{time.monotonic() - metric_started:.1f} s: "
                f"{type(exc).__name__}: {exc}"
            )
    return scores


def _run_metadata(ragas_version: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    corpus = ROOT / "data/processed/articulos.jsonl"
    corpus_hash = (
        hashlib.sha256(corpus.read_bytes()).hexdigest() if corpus.exists() else None
    )
    collection = get_client().get_collection(settings.qdrant_collection)
    generator_models = {
        "ollama": settings.ollama_chat_model,
        "openai": settings.openai_chat_model,
        "anthropic": settings.anthropic_chat_model,
        "google": settings.google_chat_model,
    }
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "ragas_version": ragas_version,
        "generator_provider": settings.llm_provider,
        "generator_model": generator_models.get(
            settings.llm_provider, settings.ollama_chat_model
        ),
        "judge_provider": None,
        "judge_model": None,
        "ollama_base_url": settings.ollama_base_url,
        "embedding_model": settings.embedding_model,
        "qdrant_url": settings.qdrant_url,
        "qdrant_collection": settings.qdrant_collection,
        "qdrant_points_count": collection.points_count,
        "qdrant_status": str(collection.status),
        "corpus_sha256": corpus_hash,
        "score_threshold": settings.umbral_score,
        "top_k": 5,
    }


JUDGE_PROVIDERS = ("ollama", "google")
# Google expone un endpoint compatible con OpenAI; permite reusar el adapter
# instructor de RAGAS sin agregar litellm como dependencia.
GOOGLE_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _make_judge(args: argparse.Namespace, async_openai, llm_factory):
    """Crea el juez RAGAS segun ``--judge`` (adapter OpenAI-compatible).

    Returns:
        ``(judge, client, model)``: el LLM juez, su cliente async (a cerrar por
        el caller) y el nombre del modelo, para registrarlo en el reporte.
    """
    settings = get_settings()
    if args.judge == "google":
        if not settings.google_api_key:
            raise ValueError("--judge google requiere GOOGLE_API_KEY en el .env")
        client = async_openai(
            base_url=GOOGLE_OPENAI_BASE,
            api_key=settings.google_api_key,
            timeout=args.timeout,
        )
        model = settings.google_chat_model
    elif args.judge == "ollama":
        client = async_openai(
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            api_key="ollama",
            timeout=args.timeout,
        )
        model = settings.ollama_chat_model
    else:
        raise ValueError(f"juez no soportado: {args.judge!r}")
    judge = llm_factory(
        model, client=client, temperature=0.0, max_tokens=args.judge_max_tokens
    )
    return judge, client, model


async def run(args: argparse.Namespace) -> Path:
    if args.n is not None and args.limit:
        raise ValueError("Usa --n o --limit, no ambos")
    _progress("cargando RAGAS y sus métricas")
    ragas, async_openai, llm_factory, metric_classes = _load_ragas()
    _progress("validando el conjunto de referencia")
    rows = load_golden(GOLDEN_PATH)
    if args.behavior:
        rows = [row for row in rows if row["expected_behavior"] == args.behavior]
    if args.exclude_behavior:
        excluded = set(args.exclude_behavior)
        rows = [row for row in rows if row["expected_behavior"] not in excluded]
    if args.max_policy is not None:
        rows = cap_policy(rows, args.max_policy, args.seed)
    if args.n is not None:
        if args.n < 1:
            raise ValueError("--n debe ser al menos 1")
        if args.n > len(rows):
            raise ValueError(
                f"--n={args.n} supera las {len(rows)} preguntas disponibles "
                "después de aplicar los filtros"
            )
        rows = random.Random(args.seed).sample(rows, args.n)
    elif args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise ValueError("No hay preguntas para ejecutar con estos filtros")

    _progress(f"preparando ejecución: {len(rows)} preguntas; métricas={args.metrics}")
    _progress("consultando estado de Qdrant y registrando configuración")
    metadata = _run_metadata(ragas.__version__)
    metadata["metrics"] = args.metrics
    metadata["judge_provider"] = args.judge
    metadata["judge_max_tokens"] = args.judge_max_tokens
    metadata["sample_seed"] = (
        args.seed if (args.n is not None or args.max_policy is not None) else None
    )
    metadata["max_policy"] = args.max_policy
    metadata["behavior_filter"] = args.behavior
    metadata["excluded_behaviors"] = args.exclude_behavior
    metadata["no_web"] = args.no_web
    metadata["selected_question_ids"] = [row["id"] for row in rows]

    judge, client, judge_model = _make_judge(args, async_openai, llm_factory)
    metadata["judge_model"] = judge_model

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    metrics = {
        name: metric_classes[name](llm=judge) for name in args.metrics
    }
    _progress(
        f"iniciando evaluación; generador={metadata['generator_model']}; "
        f"juez={args.judge}:{judge_model}; "
        f"resultados={run_dir.relative_to(ROOT)}"
    )

    search_fn = lambda question, top_k: search(question, top_k=top_k)
    web_fn = lambda question, max_results=5: web_search(
        question, max_results=max_results
    )
    output_rows = []
    results_path = run_dir / "results.jsonl"
    try:
        for index, golden in enumerate(rows, start=1):
            case_started = time.monotonic()
            _progress(f"caso [{index}/{len(rows)}] {golden['id']}: consulta RAG")
            trace: dict[str, Any] = {}
            response = query(
                golden["question"],
                top_k=5,
                use_web=not args.no_web,
                llm=get_llm(),
                search_fn=search_fn,
                web_fn=web_fn,
                trace=trace,
                progress=lambda stage: _progress(
                    f"caso [{index}/{len(rows)}] {golden['id']}: {stage}"
                ),
            )
            behavior = golden["expected_behavior"]
            expected_context_hit = expected_hit(golden, trace)
            actual_sources = response["sources"]
            citations = cita_ok(response["answer"], actual_sources)
            is_abstention = behavior.startswith("abstain_")
            row_result: dict[str, Any] = {
                "id": golden["id"],
                "question": golden["question"],
                "expected_behavior": behavior,
                "actual_route": trace.get("route"),
                "expected_context_retrieved": expected_context_hit,
                "cita_ok": citations["ok"],
                "cita_ok_rate": citations["rate"],
                "citas": citations["detalle"],
                "expected_abstention_complied": (
                    trace.get("route") == "abstain"
                    and response["answer"] == NO_EN_FUENTES
                    if is_abstention
                    else None
                ),
                "web_source_returned": any(
                    source.get("origen") == "web" for source in actual_sources
                ),
                "answer": response["answer"],
                "sources": actual_sources,
                "retrieved_contexts": trace.get("answer_contexts", []),
                "policy_retrieved_contexts": trace.get(
                    "policy_retrieved_contexts", []
                ),
                "web_retrieved_contexts": trace.get("web_retrieved_contexts", []),
                "policy_retrieval_hits": trace.get("retrieval_hits", []),
            }
            if behavior == "answer_from_policy":
                row_result["ragas"] = await _score_policy_answer(
                    golden,
                    response["answer"],
                    trace.get("answer_contexts", []),
                    metrics,
                    args.metrics,
                )
            else:
                _progress(
                    f"caso [{index}/{len(rows)}] {golden['id']}: "
                    "sin métricas RAGAS para este comportamiento"
                )
            output_rows.append(row_result)
            with results_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row_result, ensure_ascii=False) + "\n")
            print(
                f"[{index}/{len(rows)}] {golden['id']} route={trace.get('route')} "
                f"expected_hit={expected_context_hit} "
                f"cita_ok={citations['ok']} "
                f"elapsed={time.monotonic() - case_started:.1f}s",
                flush=True,
            )
    finally:
        await client.close()

    behavior_totals: dict[str, Any] = {}
    for behavior in sorted({row["expected_behavior"] for row in output_rows}):
        subset = [row for row in output_rows if row["expected_behavior"] == behavior]
        expected_hits = [
            row["expected_context_retrieved"]
            for row in subset
            if row["expected_context_retrieved"] is not None
        ]
        cita_rates = [
            row["cita_ok_rate"]
            for row in subset
            if row["cita_ok_rate"] is not None
        ]
        behavior_totals[behavior] = {
            "count": len(subset),
            "routes": dict(Counter(row["actual_route"] for row in subset)),
            "expected_context_recall_at_k": (
                mean(expected_hits) if expected_hits else None
            ),
            "cita_ok_rate": mean(cita_rates) if cita_rates else None,
            "cita_ok_compliance": (
                mean(row["cita_ok"] for row in subset) if subset else None
            ),
            "abstention_compliance": (
                mean(
                    row["expected_abstention_complied"]
                    for row in subset
                    if row["expected_abstention_complied"] is not None
                )
                if any(row["expected_abstention_complied"] is not None for row in subset)
                else None
            ),
            "web_routing_rate": (
                mean(row["web_source_returned"] for row in subset)
                if behavior == "answer_from_web"
                else None
            ),
        }

    metric_totals = {}
    for name in args.metrics:
        values = [
            result["ragas"][name]
            for result in output_rows
            if isinstance(result.get("ragas", {}).get(name), (int, float))
        ]
        metric_totals[name] = {
            "mean": mean(values) if values else None,
            "scored": len(values),
            "errors": sum(
                isinstance(result.get("ragas", {}).get(name), dict)
                and "error" in result["ragas"][name]
                for result in output_rows
            ),
        }
    summary = {
        "metadata": metadata,
        "questions_run": len(output_rows),
        "by_behavior": behavior_totals,
        "ragas_metrics": metric_totals,
    }
    _progress("escribiendo resumen agregado")
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Resultados guardados en {run_dir.relative_to(ROOT)}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.report_doc:
        _write_report_doc(summary, args.report_doc)
        print(f"Reporte Markdown escrito en {args.report_doc}")
    return run_dir


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _render_report(summary: dict[str, Any]) -> str:
    """Renderiza el resumen de una corrida como Markdown (#19 · docs/eval/LATEST.md)."""
    meta = summary["metadata"]
    lines: list[str] = [
        "# Evaluación RAG (#19) · último reporte",
        "",
        f"Generado: `{meta['started_at']}` · commit `{meta['git_commit']}`",
        "",
        "> Reporte automático de `scripts/evaluate_ragas.py` (#19). Las métricas",
        "> RAGAS usan un LLM como juez y son estimaciones, no certificación legal.",
        "",
        "## Configuración",
        "",
        f"- Generador: `{meta['generator_provider']}` · `{meta['generator_model']}`",
        f"- Juez RAGAS: `{meta['judge_provider']}` · `{meta['judge_model']}`",
        f"- Embeddings: `{meta['embedding_model']}`",
        f"- Umbral (hard gate): `{meta['score_threshold']}` · top_k `{meta['top_k']}`",
        f"- Colección Qdrant: `{meta['qdrant_collection']}` "
        f"({meta['qdrant_points_count']} puntos, {meta['qdrant_status']})",
        f"- Corpus sha256: `{meta['corpus_sha256']}`",
        f"- RAGAS: `{meta['ragas_version']}` · métricas: `{', '.join(meta['metrics'])}`",
        f"- Web habilitada: `{not meta.get('no_web', False)}`"
        f" · filtro de comportamiento: `{meta.get('behavior_filter') or '—'}`"
        f" · excluidos: `{', '.join(meta.get('excluded_behaviors') or []) or '—'}`",
        f"- Muestra: seed `{meta.get('sample_seed')}`"
        f" · tope de póliza `{meta.get('max_policy')}`",
        "",
        "## Alcance de la corrida",
        "",
        f"- Preguntas ejecutadas: **{summary['questions_run']}**",
        f"- IDs: `{', '.join(meta['selected_question_ids'])}`",
        "",
        "## Métricas RAGAS (solo respuestas de póliza con contextos)",
        "",
        "| Métrica | Media | Evaluadas | Errores |",
        "|---|---|---|---|",
    ]
    for name, data in summary["ragas_metrics"].items():
        lines.append(
            f"| {name} | {_fmt(data['mean'])} | {data['scored']} | {data['errors']} |"
        )

    lines += [
        "",
        "## Por comportamiento",
        "",
        "| Comportamiento | n | Rutas | recall@k | cita_ok (rate) | cita_ok (cumple) "
        "| abstención | ruteo web |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for behavior, data in summary["by_behavior"].items():
        routes = ", ".join(f"{k}={v}" for k, v in data["routes"].items())
        lines.append(
            f"| {behavior} | {data['count']} | {routes} "
            f"| {_fmt(data['expected_context_recall_at_k'])} "
            f"| {_fmt(data.get('cita_ok_rate'))} "
            f"| {_fmt(data.get('cita_ok_compliance'))} "
            f"| {_fmt(data.get('abstention_compliance'))} "
            f"| {_fmt(data.get('web_routing_rate'))} |"
        )

    lines += [
        "",
        "## Límites",
        "",
        "- El juez por defecto es el mismo modelo local (`qwen3:4b-instruct`) que "
        "genera: puede correlacionar errores. Usar `--judge google` para una "
        "corrida más independiente.",
        "- Los prompts de RAGAS están en inglés; el contenido evaluado es español.",
        "- Las 20 filas `answer_from_web` son comportamiento esperado, no una "
        "garantía de ruteo web (ver `RAGAS.md`).",
        "- `cita_ok` es determinista: verifica que cada cita inline exista en las "
        "fuentes devueltas; no juzga si la cita es la más pertinente.",
        "- El golden set requiere revisión humana; el piloto detectó preguntas "
        "ambiguas (varias pólizas válidas). Ver `RAGAS.md`.",
        "",
    ]
    return "\n".join(lines)


def _write_report_doc(summary: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_report(summary), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=0, help="máximo de casos (0 = todos)"
    )
    parser.add_argument(
        "--n",
        type=int,
        help="selecciona N preguntas aleatorias sin reemplazo",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="semilla opcional para repetir la misma muestra de --n/--max-policy",
    )
    parser.add_argument("--behavior", choices=BEHAVIORS, help="filtra el tipo de caso")
    parser.add_argument(
        "--exclude-behavior",
        action="append",
        choices=BEHAVIORS,
        default=[],
        help="excluye uno o más tipos de caso (repetible); útil para dejar los "
        "casos web fuera de la corrida base con --no-web",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="no ejecutar búsquedas web (recomendado para la corrida base de "
        "póliza/abstención; los casos web van en una corrida aparte)",
    )
    parser.add_argument(
        "--max-policy",
        type=int,
        help="tope de casos answer_from_policy (muestra aleatoria reproducible con "
        "--seed); mantiene el resto de comportamientos. Útil para acotar el tiempo "
        "de una corrida base representativa",
    )
    parser.add_argument(
        "--judge",
        choices=JUDGE_PROVIDERS,
        default="ollama",
        help="LLM juez de RAGAS: 'ollama' local (default) o 'google' (Gemini)",
    )
    parser.add_argument(
        "--report-doc",
        type=Path,
        default=None,
        help=f"escribe el resumen como Markdown (p. ej. {REPORT_DOC})",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=("faithfulness", "context_recall", "context_precision"),
        default=("faithfulness", "context_recall", "context_precision"),
    )
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=1024,
        help="límite de salida para cada respuesta estructurada del juez",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
