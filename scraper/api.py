"""V2 API routes backed by the pipeline orchestrator."""

from fastapi import APIRouter

from scraper.models import UrlRequest
from scraper.pipeline import run as run_pipeline

router = APIRouter(prefix="/v2", tags=["v2"])


@router.post("/jobs")
async def extract_jobs_v2(req: UrlRequest):
    """Pipeline entrypoint: classify → acquire → extract → validate."""
    return await run_pipeline({"url": req.url})
