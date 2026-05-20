"""Runtime configuration loaded from .env / environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    tp_cookie: str
    icu_api_key: str
    icu_athlete_id: str

    @staticmethod
    def load() -> Config:
        load_dotenv()
        missing = [
            name
            for name in ("TP_AUTH_COOKIE", "ICU_API_KEY", "ICU_ATHLETE_ID")
            if not os.environ.get(name)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in values."
            )
        athlete = os.environ["ICU_ATHLETE_ID"].strip()
        if not athlete.startswith("i"):
            athlete = f"i{athlete}"
        return Config(
            tp_cookie=os.environ["TP_AUTH_COOKIE"].strip(),
            icu_api_key=os.environ["ICU_API_KEY"].strip(),
            icu_athlete_id=athlete,
        )
