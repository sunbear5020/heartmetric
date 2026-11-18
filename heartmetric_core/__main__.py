"""Command line entry point: ``python -m heartmetric_core``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, exporter, loader, pipeline, synthetic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heartmetric",
        description="HEARTMETRIC Core — analyse cuff BP + wearable HR/HRV + environment exposure.",
    )
    parser.add_argument("--version", action="version", version=f"HEARTMETRIC {__version__}")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", "-i", help="CSV / TSV / JSON / Apple Health XML file")
    source.add_argument("--demo", action="store_true", help="use the bundled synthetic 14-day series")
    parser.add_argument("--out", "-o", default="heartmetric_report.xlsx", help="output .xlsx / .csv / .json")
    parser.add_argument("--condition", default=None, help="label every row of --input with this condition")
    parser.add_argument("--group-a", default="forest", help="condition compared as 'a' (default: forest)")
    parser.add_argument("--group-b", default="urban", help="condition compared as 'b' (default: urban)")
    parser.add_argument("--paired", action="store_true", help="use a paired t-test (matched days)")
    parser.add_argument("--night-start", type=int, default=22)
    parser.add_argument("--night-end", type=int, default=6)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    night = (args.night_start, args.night_end)

    if args.demo:
        bundle = pipeline.demo_bundle(group_a=args.group_a, group_b=args.group_b, paired=args.paired, night=night)
    else:
        loaded = loader.load_file(args.input, condition=args.condition)
        for warning in loaded.warnings:
            print(f"[load] {warning}", file=sys.stderr)
        bundle = pipeline.analyze_loaded(
            loaded, group_a=args.group_a, group_b=args.group_b, paired=args.paired, night=night
        )

    quality = bundle["quality"]
    summary = bundle["summary"]
    print(f"rows: {quality['rows_out']} / {quality['rows_in']} · conditions: {quality['conditions']}")
    if summary.get("sbp") is not None:
        print(f"mean SBP/DBP: {summary.get('sbp')} / {summary.get('dbp')} mmHg · MAP {summary.get('map')} · PP {summary.get('pp')}")
    if summary.get("hrv_recovery", {}).get("available"):
        recovery = summary["hrv_recovery"]
        print(f"HRV recovery index: {recovery['index']} ({recovery['band']}, baseline {recovery['baseline']})")
    if summary.get("dipping", {}).get("available"):
        dipping = summary["dipping"]
        print(f"nocturnal dipping: {dipping['dipping_pct']}% ({dipping['category']})")
    if summary.get("stress_index", {}).get("available"):
        stress = summary["stress_index"]
        print(f"environmental stress index: {stress['index']} ({stress['band']})")
    for row in bundle.get("comparison", []):
        p_value = row.get("p_value")
        if p_value is None:
            p_text = "p=—"
        elif p_value < 0.0001:
            p_text = "p<0.0001"
        else:
            p_text = f"p={p_value:.4f}"
        print(
            f"  {row['metric']:>5}: {row['mean_a']} vs {row['mean_b']} "
            f"(Δ {row['diff']}, d={row['cohens_d']}, {p_text})"
        )

    written = exporter.save(bundle, args.out)
    print(f"written: {Path(written).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
