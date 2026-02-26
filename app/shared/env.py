from __future__ import annotations

import os

from app.shared.paths import find_repo_root


def load_repo_dotenv(start_dir: str | None = None, *, override: bool = False) -> str | None:
    """Load repo-local .env/.env.local without affecting other projects."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return None

    repo_root = find_repo_root(start_dir or os.getcwd())
    loaded_path: str | None = None

    for name in (".env", ".env.local"):
        path = os.path.join(repo_root, name)
        if not os.path.exists(path):
            continue
        # .env.local should override repo-default .env values for local machine config.
        file_override = True if name == ".env.local" else override
        load_dotenv(path, override=file_override)
        loaded_path = path

    return loaded_path
