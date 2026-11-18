"""Minimal end-to-end example: synthetic demo → console summary → Excel.

    python examples/example_basic.py
"""

from __future__ import annotations

from pathlib import Path

from heartmetric_core import exporter, load_csv, pipeline, synthetic


def main() -> None:
    # 1) Write the 100 % synthetic 14-day table (urban street vs forest walk).
    csv_path = Path(__file__).with_name("demo_urban_forest.csv")
    synthetic.write_demo_csv(str(csv_path))
    print(f"demo table written: {csv_path}")

    # 2) Load it back through the same loader a user's own file would go through.
    loaded = load_csv(csv_path)
    print(f"mapped columns: {loaded.mapping}")
    for warning in loaded.warnings:
        print("warning:", warning)

    # 3) Analyse: QC → indices → forest vs urban comparison.
    bundle = pipeline.analyze_loaded(loaded, group_a="forest", group_b="urban")

    summary = bundle["summary"]
    print(f"mean SBP/DBP {summary['sbp']}/{summary['dbp']} mmHg · MAP {summary['map']}")
    print(f"nocturnal dipping {summary['dipping']['dipping_pct']}% ({summary['dipping']['category']})")
    recovery = summary["hrv_recovery"]
    print(f"HRV recovery index {recovery['index']} ({recovery['band']})")
    print(f"environmental stress index {summary['stress_index']['index']}")

    for row in bundle["comparison"]:
        print(
            f"{row['metric']:>5}: forest {row['mean_a']} vs urban {row['mean_b']} "
            f"(Δ {row['diff']}, d={row['cohens_d']}, p={row['p_value']})"
        )

    # 4) Export a co-author-ready workbook.
    out = exporter.save(bundle, Path(__file__).with_name("heartmetric_demo_report.xlsx"))
    print(f"workbook written: {out}")


if __name__ == "__main__":
    main()
