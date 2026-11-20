"""Command line entry point: ``python -m heartmetric_core``.

    python -m heartmetric_core --demo -o report.xlsx
    python -m heartmetric_core -i bp.csv -i oura.json -i env.csv --merge --tolerance-minutes 30 -o report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import SCHEMA_VERSION, __version__, exporter, loader, pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heartmetric",
        description="HEARTMETRIC Core — align and analyse cuff BP + wearable HR/HRV + environment exposure.",
    )
    parser.add_argument("--version", action="version", version=f"HEARTMETRIC {__version__} (bundle schema {SCHEMA_VERSION})")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input",
        "-i",
        action="append",
        help="CSV / TSV / JSON / Apple Health XML file. Repeat it (or add --merge) to combine streams.",
    )
    source.add_argument("--demo", action="store_true", help="use the bundled synthetic 14-day series")
    source.add_argument(
        "--demo-streams",
        action="store_true",
        help="split the demo into BP / wearable / environment files and align them again",
    )
    parser.add_argument("--out", "-o", default="heartmetric_report.xlsx", help="output .xlsx / .csv / .json / .md")
    parser.add_argument("--condition", default=None, help="label every row of the input with this condition")
    parser.add_argument(
        "--conditions",
        default=None,
        help="comma-separated condition per --input, e.g. 'forest,,' (empty keeps the file's own labels)",
    )
    parser.add_argument("--group-a", default="forest", help="condition compared as 'a' (default: forest)")
    parser.add_argument("--group-b", default="urban", help="condition compared as 'b' (default: urban)")
    parser.add_argument("--paired", action="store_true", help="use a paired comparison")
    parser.add_argument(
        "--paired-by",
        choices=["auto", "subject", "row"],
        default="auto",
        help="pair by subject_id when present (auto), by subject only, or by observation order (row)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="align several --input files into one table (implied when --input is given more than once)",
    )
    parser.add_argument(
        "--tolerance-minutes",
        type=float,
        default=30.0,
        help="maximum time difference for joining two streams (default: 30)",
    )
    parser.add_argument(
        "--align-mode",
        choices=["tolerance", "daily"],
        default="tolerance",
        help="join single measurements by time proximity, or aggregate per subject and day first",
    )
    parser.add_argument(
        "--anchor",
        choices=["bp", "wearable", "environment"],
        default=None,
        help="stream whose rows become the output rows (default: bp when present)",
    )
    parser.add_argument("--night-start", type=int, default=22)
    parser.add_argument("--night-end", type=int, default=6)
    return parser


def _print_bundle(bundle: dict) -> None:
    quality = bundle["quality"]
    summary = bundle["summary"]
    print(f"rows: {quality['rows_out']} / {quality['rows_in']} · conditions: {quality['conditions']}")
    alignment = bundle.get("alignment") or (bundle.get("meta") or {}).get("alignment")
    if alignment:
        print(
            f"aligned: {alignment['mode']} · tolerance {alignment['tolerance_minutes']} min · "
            f"anchor matched {alignment['anchors_matched']}/{alignment['anchors']} ({alignment['match_rate_pct']}%)"
        )
        for stream in alignment.get("streams", []):
            print(
                f"  {stream['name']} ({stream['role']}): {stream['matched_rows']}/{stream['rows']} rows joined, "
                f"{stream['unmatched_rows']} unmatched"
            )
    if summary.get("sbp") is not None:
        print(f"mean SBP/DBP: {summary.get('sbp')} / {summary.get('dbp')} mmHg · MAP {summary.get('map')} · PP {summary.get('pp')}")
    if (summary.get("hrv_recovery") or {}).get("available"):
        recovery = summary["hrv_recovery"]
        print(f"HRV recovery index: {recovery['index']} ({recovery['band']}, baseline {recovery['baseline']})")
    if (summary.get("dipping") or {}).get("available"):
        dipping = summary["dipping"]
        print(f"nocturnal dipping: {dipping['dipping_pct']}% ({dipping['category']})")
    if (summary.get("stress_index") or {}).get("available"):
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
        dz = row.get("cohens_dz")
        dz_text = f", d_z={dz}" if dz is not None else ""
        perm = row.get("permutation_p")
        perm_text = f", perm p={perm}" if perm is not None else ""
        print(
            f"  {row['metric']:>5}: {row['mean_a']} vs {row['mean_b']} "
            f"(Δ {row['diff']}, d={row['cohens_d']}{dz_text}, {p_text}{perm_text}, by {row.get('paired_by')})"
        )
    correlations = bundle.get("correlations") or []
    if correlations:
        print("correlations (r / rho / slope per x unit):")
        for row in correlations[:6]:
            print(
                f"  {row['x']:>12} × {row['y']:<5}: r={row.get('pearson_r')} ρ={row.get('spearman_rho')} "
                f"slope={row.get('slope')} p={row.get('slope_p')} n={row.get('n')}"
            )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    night = (args.night_start, args.night_end)
    common = dict(group_a=args.group_a, group_b=args.group_b, paired=args.paired, paired_by=args.paired_by, night=night)

    if args.demo:
        bundle = pipeline.demo_bundle(**common)
    elif args.demo_streams:
        bundle = pipeline.demo_streams(tolerance_minutes=args.tolerance_minutes, **common)
    else:
        paths = list(args.input or [])
        if args.merge or len(paths) > 1:
            conditions = None
            if args.conditions:
                parts = [part.strip() or None for part in args.conditions.split(",")]
                conditions = parts
            bundle = pipeline.analyze_streams(
                paths,
                tolerance_minutes=args.tolerance_minutes,
                mode=args.align_mode,
                anchor=args.anchor,
                conditions=conditions,
                **common,
            )
            for path in paths:
                try:
                    loaded = loader.load_file(path)
                except Exception:  # noqa: BLE001 - the pipeline already reported failures
                    continue
                for warning in loaded.warnings:
                    print(f"[load] {path}: {warning}", file=sys.stderr)
        else:
            loaded = loader.load_file(paths[0], condition=args.condition)
            for warning in loaded.warnings:
                print(f"[load] {warning}", file=sys.stderr)
            bundle = pipeline.analyze_loaded(loaded, **common)

    _print_bundle(bundle)

    written = exporter.save(bundle, args.out)
    print(f"written: {Path(written).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
