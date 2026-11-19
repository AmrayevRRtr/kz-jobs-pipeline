"""Command line entry point: ``kzjobs run`` and ``kzjobs demo``."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta

from kzjobs.config import REPO_ROOT, Settings
from kzjobs.pipeline import run_all

SAMPLE_DIR = REPO_ROOT / "data" / "sample"
DEMO_DAY1 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def _cmd_run(settings: Settings, _args: argparse.Namespace) -> int:
    report = run_all(settings)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


def _cmd_demo(settings: Settings, _args: argparse.Namespace) -> int:
    """Offline demo on synthetic data: two daily snapshots to show validation and SCD2."""
    fx_xml = (SAMPLE_DIR / "nbk_rates.xml").read_text(encoding="utf-8")
    for offset, name in enumerate(("hh_day1.json", "hh_day2.json")):
        payloads = json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))
        report = run_all(
            settings, hh_payloads=payloads, fx_xml=fx_xml, now=DEMO_DAY1 + timedelta(days=offset)
        )
        print(f"--- {name} ---")
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kzjobs", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the pipeline against the live hh and NBK sources")
    sub.add_parser("demo", help="run the pipeline offline on bundled synthetic sample data")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings.from_env()
    handlers = {"run": _cmd_run, "demo": _cmd_demo}
    return handlers[args.command](settings, args)


if __name__ == "__main__":
    raise SystemExit(main())
