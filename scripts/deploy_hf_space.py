"""Publish the app to a Hugging Face Docker Space.

    pip install huggingface_hub
    hf auth login
    python scripts/deploy_hf_space.py your-username/portfolio-analytics-agent

GEMINI_API_KEY is read from your environment or .env and stored as an encrypted Space
secret. It is never uploaded as a file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portfolio_agent.config import Settings  # noqa: E402

SPACE_README = """---
title: Portfolio Analytics Agent
sdk: docker
app_port: 7860
pinned: false
---

Natural-language analytics over a sample portfolio dataset. Not investment advice.
"""
UPLOAD = ["portfolio_agent/**", "data/**", "reports/live_extended.json", "database_schema.sql", "requirements.txt", "Dockerfile", ".dockerignore"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("space", help="username/space-name")
    args = parser.parse_args()

    key = Settings.from_env().gemini_api_key
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it to .env first.")

    api = HfApi()
    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    api.add_space_secret(args.space, "GEMINI_API_KEY", key)
    api.upload_folder(
        repo_id=args.space,
        repo_type="space",
        folder_path=ROOT,
        allow_patterns=UPLOAD,
        ignore_patterns=["**/__pycache__/**", "**/*.pyc"],
    )
    api.upload_file(
        path_or_fileobj=SPACE_README.encode(),
        path_in_repo="README.md",
        repo_id=args.space,
        repo_type="space",
    )
    owner, name = args.space.split("/")
    print(f"Deployed. It builds in a few minutes: https://{owner}-{name}.hf.space")


if __name__ == "__main__":
    main()
