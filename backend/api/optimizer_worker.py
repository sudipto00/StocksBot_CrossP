"""
Detached optimizer worker entrypoint.

This module is launched by the API dispatcher as:
    python -m api.optimizer_worker --job-id <job_id>
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from api.routes import (
    _optimizer_hydrate_runtime_credentials_from_env,
    _run_optimizer_job,
)

logger = logging.getLogger("stocksbot.optimizer_worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one optimizer job worker")
    parser.add_argument("--job-id", required=True, help="Optimization job id")
    args = parser.parse_args(argv)

    job_id = str(args.job_id or "").strip()
    if not job_id:
        print("Missing --job-id", file=sys.stderr)
        return 2

    os.environ["STOCKSBOT_OPTIMIZER_CHILD"] = "1"
    try:
        _optimizer_hydrate_runtime_credentials_from_env()
        _run_optimizer_job(job_id)
        return 0
    except Exception:
        logger.exception("Optimizer worker crashed for job_id=%s", job_id)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
