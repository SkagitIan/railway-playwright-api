import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from scraper.ats.signal_scanner import scan_url


def test_scan_url_detects_greenhouse():
    result = scan_url("https://boards.greenhouse.io/openai")
    assert result["ats"] == "greenhouse"
    assert result["strategy"] == "DIRECT_JSON_API"


def test_scan_url_detects_unknown():
    result = scan_url("https://example.com/careers")
    assert result["ats"] == "unknown"
    assert result["strategy"] == "BROWSER_HAR"
