"""
Backend optimizer admin CLI.

Examples:
  python backend/scripts/optimizer_admin.py list-active
  python backend/scripts/optimizer_admin.py cancel-all --force
  python backend/scripts/optimizer_admin.py cancel-job --job-id <id> --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure `api.*` imports resolve when launched from repo root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api.routes import (  # noqa: E402
    admin_cancel_all_optimizer_jobs,
    _optimizer_escalate_cancel,
    _optimizer_get_job,
    _optimizer_request_cancel,
)


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimizer admin helper")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list-active", help="List active queued/running jobs")
    list_cmd.add_argument("--limit", type=int, default=100)

    cancel_all_cmd = sub.add_parser("cancel-all", help="Cancel all queued/running jobs")
    cancel_all_cmd.add_argument("--force", action="store_true", help="Use hard cancel escalation")

    cancel_one_cmd = sub.add_parser("cancel-job", help="Cancel a single job id")
    cancel_one_cmd.add_argument("--job-id", required=True, help="Target optimizer job id")
    cancel_one_cmd.add_argument("--force", action="store_true", help="Use hard cancel escalation")

    args = parser.parse_args(argv)

    if args.command == "cancel-all":
        payload = admin_cancel_all_optimizer_jobs(force=bool(args.force))
        _print(payload)
        return 0

    if args.command == "cancel-job":
        job_id = str(args.job_id or "").strip()
        row = _optimizer_get_job(job_id)
        if row is None:
            _print({"success": False, "error": "job_not_found", "job_id": job_id})
            return 1
        _optimizer_request_cancel(
            job_id,
            message="Force cancel requested (cli)" if args.force else "Cancel requested (cli)",
            force=bool(args.force),
        )
        updated = _optimizer_escalate_cancel(job_id, force_now=bool(args.force)) or _optimizer_get_job(job_id)
        _print({"success": True, "job_id": job_id, "status": (updated or {}).get("status"), "row": updated})
        return 0

    if args.command == "list-active":
        # Reuse in-memory/persisted status lookup via direct access by requesting cancel-all in dry-style.
        # We call helper and simply display currently active rows before any cancellation.
        # To avoid side effects, gather via status lookups directly.
        from storage.database import SessionLocal  # noqa: E402
        from storage.service import StorageService  # noqa: E402

        db = SessionLocal()
        try:
            storage = StorageService(db)
            persisted = storage.list_recent_optimization_runs(
                statuses=["queued", "running"],
                sources=["async"],
                limit_total=max(1, int(args.limit)),
            )
            jobs = []
            for run in persisted:
                row = _optimizer_get_job(str(run.run_id))
                if row is None:
                    continue
                status = str(row.get("status") or "").lower()
                if status not in {"queued", "running"}:
                    continue
                jobs.append(
                    {
                        "job_id": str(row.get("job_id") or ""),
                        "strategy_id": str(row.get("strategy_id") or ""),
                        "status": status,
                        "progress_pct": float(row.get("progress_pct") or 0.0),
                        "message": str(row.get("message") or ""),
                        "cancel_requested": bool(row.get("cancel_requested")),
                    }
                )
            _print({"success": True, "count": len(jobs), "jobs": jobs})
            return 0
        finally:
            db.close()

    _print({"success": False, "error": "unknown_command"})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
