import os

AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
AI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "510"))
