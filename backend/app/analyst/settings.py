"""AI settings (Feature 015): the process environment wins over `backend/.env` (git-ignored, never committed).

Only `AI_*` names and `<PROVIDER>_API_KEY` names are read; a blank value counts as unset. `AI_DOTENV=0` disables the
file (the test suite sets it so a developer `.env` never makes an offline test call a model).
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_NAME = re.compile(r"^(?:AI_[A-Z0-9_]+|[A-Z0-9]+_API_KEY)$")


def ai_env(environ: Mapping[str, str] | None = None, *, path: Path = DOTENV_PATH,
           use_dotenv: bool | None = None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    if use_dotenv is None:
        use_dotenv = environ.get("AI_DOTENV", "1") != "0"
    merged: dict[str, str] = {}
    if use_dotenv and path.is_file():
        merged.update({k: v for k, v in dotenv_values(path).items() if v is not None and _NAME.match(k)})
    merged.update({k: v for k, v in environ.items() if _NAME.match(k)})
    return {k: v.strip() for k, v in merged.items() if v.strip()}
