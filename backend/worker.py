"""Standalone background worker to process the OpsFlow transactional outbox queue.

Usage:
  python worker.py --once       # Process pending jobs once and exit
  python worker.py --interval 2 # Run continuously, polling every 2 seconds
"""
import argparse
import sys
import time

from app.database import SessionLocal
from app.services.outbox import process_pending_outbox_jobs


def run_worker(once: bool = False, poll_interval: float = 2.0) -> None:
    print(f"[worker] OpsFlow outbox worker started (poll_interval={poll_interval}s, once={once})")
    try:
        while True:
            with SessionLocal() as db:
                try:
                    count = process_pending_outbox_jobs(db, batch_size=20)
                    if count > 0:
                        db.commit()
                        print(f"[worker] Successfully processed {count} outbox job(s)")
                except Exception as exc:
                    db.rollback()
                    print(f"[worker] Error processing outbox batch: {exc}", file=sys.stderr)

            if once:
                break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\n[worker] Worker stopped by user.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpsFlow Transactional Outbox Worker")
    parser.add_argument("--once", action="store_true", help="Run one pass over pending jobs and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()
    run_worker(once=args.once, poll_interval=args.interval)
