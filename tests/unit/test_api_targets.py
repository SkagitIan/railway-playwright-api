from scraper.ats.api_targets import build_api_target


def test_build_greenhouse_api_target():
    target = build_api_target("https://boards.greenhouse.io/openai", "greenhouse")

    assert target["api_target_url"] == "https://boards-api.greenhouse.io/v1/boards/openai/jobs"
    assert target["method"] == "GET"


def test_build_lever_api_target():
    target = build_api_target("https://jobs.lever.co/netflix", "lever")

    assert target["api_target_url"] == "https://api.lever.co/v0/postings/netflix?mode=json"
    assert target["method"] == "GET"


def test_build_ashby_api_target():
    target = build_api_target("https://jobs.ashbyhq.com/example", "ashby")

    assert target["api_target_url"] == "https://api.ashbyhq.com/posting-api/job-board/example"
    assert target["method"] == "GET"
