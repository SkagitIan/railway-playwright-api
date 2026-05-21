"""V2 API routes backed by the pipeline orchestrator."""

from fastapi import APIRouter, HTTPException

from scraper.ats.spec_store import delete_specs_for_domain, list_specs
from scraper.models import UrlRequest
from scraper.pipeline import run as run_pipeline

router = APIRouter(prefix="/v2", tags=["v2"])


@router.post("/jobs")
async def extract_jobs_v2(req: UrlRequest):
    """Pipeline entrypoint: classify → acquire → extract → validate."""
    return await run_pipeline({"url": req.url})


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
