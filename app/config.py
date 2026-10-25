import os
from dotenv import load_dotenv

load_dotenv()


def _list(v: str):
    return [x.strip() for x in v.split(",") if x.strip()]


# Any OpenAI-compatible provider works. Defaults to OpenRouter's free router.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
MODEL = os.getenv("MODEL", "openrouter/free")
MODEL_FALLBACKS = _list(os.getenv("MODEL_FALLBACKS", ""))  # OpenRouter only
APP_TOKEN = os.getenv("APP_TOKEN", "")
ALLOWED_NAMESPACES = _list(os.getenv("ALLOWED_NAMESPACES", "default,demo,err-scheduling,err-quota,err-config,err-image,err-runtime,err-network,err-storage"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))
LOG_TAIL_LINES = int(os.getenv("LOG_TAIL_LINES", "100"))
DB_PATH = os.getenv("DB_PATH", "data/investigations.db")
