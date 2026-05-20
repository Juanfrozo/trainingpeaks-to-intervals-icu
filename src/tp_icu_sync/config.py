"""Runtime configuration loaded from .env / environment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _default_env_search_paths() -> list[Path]:
    """Locations searched for a .env file, in order of precedence."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return [
        Path.cwd() / ".env",
        Path(xdg) / "tp-icu-sync" / ".env",
        Path.home() / ".tp-icu-sync.env",
    ]


def _find_env_file(explicit: str | os.PathLike[str] | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"--env-file not found: {p}")
        return p
    for candidate in _default_env_search_paths():
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Config:
    tp_cookie: str
    icu_api_key: str
    icu_athlete_id: str

    @staticmethod
    def load(env_file: str | os.PathLike[str] | None = None) -> Config:
        """Load config from env vars, optionally seeded by a .env file.

        Search order for .env when `env_file` is not given:
          1. ./.env in current working directory
          2. $XDG_CONFIG_HOME/tp-icu-sync/.env (default ~/.config/tp-icu-sync/.env)
          3. ~/.tp-icu-sync.env
        Already-set environment variables always take precedence over file values.
        """
        found = _find_env_file(env_file)
        if found is not None:
            logger.info("Using env file: %s", found)
            load_dotenv(dotenv_path=found, override=False)
        elif env_file is None:
            logger.debug(
                "No .env file found in %s; relying on environment variables only.",
                ", ".join(str(p) for p in _default_env_search_paths()),
            )

        missing = [
            name
            for name in ("TP_AUTH_COOKIE", "ICU_API_KEY", "ICU_ATHLETE_ID")
            if not os.environ.get(name)
        ]
        if missing:
            search_hint = "\n  ".join(str(p) for p in _default_env_search_paths())
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)}.\n"
                f"Either set them in your shell, or put them in a .env file at one of:\n"
                f"  {search_hint}\n"
                f"You can also pass --env-file PATH to point at a specific file."
            )
        athlete = os.environ["ICU_ATHLETE_ID"].strip()
        if not athlete.startswith("i"):
            athlete = f"i{athlete}"
        return Config(
            tp_cookie=os.environ["TP_AUTH_COOKIE"].strip(),
            icu_api_key=os.environ["ICU_API_KEY"].strip(),
            icu_athlete_id=athlete,
        )
