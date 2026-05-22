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
from scraper.models import (
    DiscoveryClassificationUpdateRequest,
    DiscoveryClassifyItemsRequest,
    DiscoveryDeleteItemsRequest,
    DiscoveryMoveItemsRequest,
    DiscoveryRunJobsRequest,
    DiscoveryRunRequest,
    DiscoverySourceResolveRequest,
    UrlRequest,
)
from scraper.pipeline import run as run_pipeline
from scraper import discovery

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


@router.get("/discovery/industries")
def get_discovery_industries():
    """Return discovery presets, Skagit city list, and quota status."""
    return discovery.discovery_meta()


@router.get("/discovery/runs")
def get_discovery_runs(limit: int = 50):
    """List recent discovery runs."""
    return discovery.list_runs(limit=limit)


@router.post("/discovery/runs")
async def create_discovery(req: DiscoveryRunRequest):
    """Run Google Places discovery across the incorporated Skagit cities."""
    return await discovery.run_discovery(req.industry, req.custom_query)


@router.get("/discovery/runs/{run_id}")
def get_discovery_run(run_id: int):
    """Return a discovery run and its table rows."""
    return discovery.get_run(run_id)


@router.delete("/discovery/runs/{run_id}/items")
def delete_discovery_items(run_id: int, req: DiscoveryDeleteItemsRequest):
    """Delete selected discovery rows from a run."""
    return discovery.delete_items(run_id, req.item_ids)


@router.post("/discovery/runs/{run_id}/move-items")
def move_discovery_items(run_id: int, req: DiscoveryMoveItemsRequest):
    """Move selected discovery rows into another industry run."""
    return discovery.move_items(run_id, req.item_ids, req.target_industry)


@router.post("/discovery/runs/{run_id}/resolve-sources")
async def resolve_discovery_sources(run_id: int, req: DiscoverySourceResolveRequest):
    """Resolve best careers/jobs source URLs for discovery rows."""
    return await discovery.resolve_sources(run_id, req.item_ids)


@router.post("/discovery/runs/{run_id}/classify-items")
async def classify_discovery_items(run_id: int, req: DiscoveryClassifyItemsRequest):
    """Classify selected discovery rows against the run industry."""
    return await discovery.classify_items(run_id, req.item_ids)


@router.post("/discovery/runs/{run_id}/items/{item_id}/classification")
def update_discovery_item_classification(run_id: int, item_id: int, req: DiscoveryClassificationUpdateRequest):
    """Manually accept, reject, or update a discovery row classification."""
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    return discovery.update_item_classification(run_id, item_id, payload)


@router.post("/discovery/runs/{run_id}/run-jobs")
async def run_discovery_jobs(run_id: int, req: DiscoveryRunJobsRequest):
    """Run the current jobs pipeline for selected resolved discovery rows."""
    return await discovery.run_jobs_for_items(run_id, req.item_ids)
