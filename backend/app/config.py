import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")

# Server-side speech provider. Never expose these credentials through NEXT_PUBLIC_*.
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_SUBSCRIPTION_KEY", "")
SARVAM_API_BASE_URL = os.getenv("SARVAM_API_BASE_URL", "https://api.sarvam.ai").rstrip("/")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v4-flash")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "shubh_enhi_ads")

if not GOOGLE_API_KEY:
    import warnings
    warnings.warn(
        "GOOGLE_API_KEY is not set. Add it to .env — server will start but LLM calls will fail.",
        RuntimeWarning,
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Indian Kanoon API
# ---------------------------------------------------------------------------
INDIAN_KANOON_TOKEN = os.getenv("INDIAN_KANOON_TOKEN", "")

if not INDIAN_KANOON_TOKEN:
    import warnings
    warnings.warn(
        "INDIAN_KANOON_TOKEN is not set. Add it to .env — legal research calls will fail.",
        RuntimeWarning,
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Latest Gemini Models (September 2026)
# ---------------------------------------------------------------------------
MODEL_VOICE  = os.getenv("MODEL_VOICE",  "gemini-3.1-flash-lite-preview")   # Realtime audio dialog
MODEL_PRO    = os.getenv("MODEL_PRO",    "gemini-3.1-pro-preview")  # Verified through provider model discovery
MODEL_FLASH  = os.getenv("MODEL_FLASH",  "gemini-3.1-flash-lite")           # Fast extraction agents
MODEL_SEARCH = os.getenv("MODEL_SEARCH", "gemini-3.1-flash-lite")           # Keyword generation & search queries

# ---------------------------------------------------------------------------
# Storage & Paths
# ---------------------------------------------------------------------------
SQLITE_CHECKPOINT_PATH  = os.getenv("SQLITE_CHECKPOINT_PATH", "./checkpoints.db")
