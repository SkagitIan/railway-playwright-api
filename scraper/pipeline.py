"""Simple classify → acquire → extract → validate pipeline."""

from scraper.stages import acquirer, classifier, extractor, validator


async def run(stage_input: dict) -> dict:
    """Run all pipeline stages in sequence."""
    classified = await classifier.run(stage_input)
    acquired = await acquirer.run(classified)
    extracted = await extractor.run(acquired)
    validated = await validator.run(extracted)
    return validated
