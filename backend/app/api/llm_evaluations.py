"""Configuración > Evaluación de IA (admins): compare providers/models on the same cases.

POST starts an evaluation in the background (it makes dozens of LLM calls) and
returns its id; GET polls it. Results are stored in in_llm_evaluations so a
comparison can be shown later ("switching to vLLM did not degrade quality").
"""
import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.security.context import CurrentUser
from app.services import audit
from app.services import llm_evaluation as evaluation
from app.services import supabase_rest as db
from app.services.db import new_id, now_iso
from app.services.observability import get_observability

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm/evaluations", tags=["llm"])
TABLE = "in_llm_evaluations"
_tasks: set[asyncio.Task] = set()


class CandidateIn(BaseModel):
    provider: Literal["cloud", "local", "vllm"]
    model: str | None = Field(default=None, max_length=200)


class EvaluationIn(BaseModel):
    candidates: list[CandidateIn] = Field(min_length=1, max_length=4)
    repetitions: int = Field(default=2, ge=1, le=3)


async def _run(evaluation_id: str, candidates: list[evaluation.Candidate], repetitions: int) -> None:
    results: list[dict] = []
    try:
        await db.update(TABLE, {"id": evaluation_id}, {"status": "running"})
        cases = evaluation.load_cases()
        for candidate in candidates:
            results.append(await evaluation.evaluate_candidate(candidate, cases, repetitions=repetitions))
            await db.update(TABLE, {"id": evaluation_id}, {"results": results})
        summary = evaluation.compare(results)
        await db.update(TABLE, {"id": evaluation_id},
                        {"status": "completed", "results": results, "summary": summary, "completed_at": now_iso()})
        await audit.record("llm.evaluation_completed", module="ia", resource_type="llm_evaluation",
                           resource_id=evaluation_id, context={"ranking": summary["ranking"],
                                                               "degradations": summary["degradations"]})
        await get_observability().emit("INFO", "llm", "llm.evaluation_completed",
                                       f"Evaluación de IA terminada ({len(results)} candidatos)",
                                       context={"evaluation_id": evaluation_id})
    except Exception as exc:  # noqa: BLE001 - reported on the evaluation row
        logger.exception("Evaluación de IA %s falló", evaluation_id)
        await db.update(TABLE, {"id": evaluation_id},
                        {"status": "failed", "results": results, "error": str(exc)[:500], "completed_at": now_iso()})
        await get_observability().emit("ERROR", "llm", "llm.evaluation_failed", f"Evaluación de IA falló: {exc}",
                                       context={"evaluation_id": evaluation_id})


@router.post("")
async def start_evaluation(body: EvaluationIn, user: CurrentUser = Depends(require_admin)):
    if any(t for t in _tasks if not t.done()):
        raise HTTPException(status_code=409, detail="Ya hay una evaluación en curso. Espera a que termine.")
    candidates = [evaluation.Candidate(c.provider, c.model or None) for c in body.candidates]
    row = await db.insert(TABLE, {
        "id": new_id("eval"),
        "status": "queued",
        "candidates": [c.model_dump() for c in body.candidates],
        "repetitions": body.repetitions,
        "results": [],
        "created_by": user.member_id,
        "created_at": now_iso(),
    })
    await audit.record("llm.evaluation_started", module="ia", resource_type="llm_evaluation", resource_id=row["id"],
                       context={"candidates": row["candidates"], "repetitions": body.repetitions})
    task = asyncio.create_task(_run(row["id"], candidates, body.repetitions))  # inherits the user's context
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return row


@router.get("")
async def list_evaluations(_: CurrentUser = Depends(require_admin)):
    return await db.select(TABLE, order="created_at.desc", limit=20)


@router.get("/{evaluation_id}")
async def get_evaluation(evaluation_id: str, _: CurrentUser = Depends(require_admin)):
    rows = await db.select(TABLE, filters={"id": evaluation_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada.")
    return rows[0]
