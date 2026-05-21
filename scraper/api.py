"""V2 API routes backed by the pipeline orchestrator."""

import time

from fastapi import APIRouter, HTTPException

from scraper.ats.spec_store import (
    clear_all_data,
    clear_pipeline_runs,
    delete_specs_for_domain,
    get_pipeline_run,
    list_pipeline_runs,
    list_specs,
    save_pipeline_run,
)
from scraper.models import UrlRequest
from scraper.pipeline import run as run_pipeline

router = APIRouter(prefix="/v2", tags=["v2"])


@router.post("/jobs")
async def extract_jobs_v2(req: UrlRequest):
    """Pipeline entrypoint: classify → acquire → extract → validate."""
    started = time.perf_counter()
    result = await run_pipeline({"url": req.url})
    duration_ms = int((time.perf_counter() - started) * 1000)
    run_id = save_pipeline_run(result, duration_ms=duration_ms)
    return {**result, "saved_run_id": run_id, "duration_ms": duration_ms}


@router.get("/runs")
def get_runs(limit: int = 50):
    """List recent saved pipeline runs."""
    return {"runs": list_pipeline_runs(limit=limit)}


@router.get("/runs/{run_id}")
def get_run(run_id: int):
    """Return a saved pipeline run with its jobs and original response."""
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"No saved run found: {run_id}")
    return run


@router.delete("/runs")
def delete_runs():
    """Clear saved run history and saved jobs."""
    return {"deleted": clear_pipeline_runs()}


@router.delete("/database")
def delete_database_data():
    """Clear all persisted data so the pipeline starts fresh."""
    return {"deleted": clear_all_data()}


@router.get("/specs")
def get_specs():
    """List all stored scraper specs, one per domain."""
    return {"specs": list_specs()}


@router.delete("/specs/{domain:path}")
def delete_domain_specs(domain: str):
    """Remove all specs for a domain so the pipeline re-learns it."""
    count = delete_specs_for_domain(domain)
    if count == 0:
        raise HTTPException(status_code=404, detail=f"No specs found for domain: {domain}")
    return {"deleted": count, "domain": domain}
