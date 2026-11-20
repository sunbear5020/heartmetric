"""v0.2 alignment example: three files → one table → paired stats + correlation.

    python examples/example_align.py

The three CSVs in examples/streams/ are the same synthetic 6-day study written
by three different loggers: the cuff file starts at :10, the wearable 3 minutes
later, and the environment logger 7 minutes earlier. Aligning them by time
proximity is exactly what a real study needs.
"""

from __future__ import annotations

from pathlib import Path

from heartmetric_core import align_streams, analyze, exporter


def main() -> None:
    here = Path(__file__).resolve().parent
    streams = [
        here / "streams" / "cuff_bp.csv",
        here / "streams" / "wearable.csv",
        here / "streams" / "environment.csv",
    ]

    aligned = align_streams([str(path) for path in streams], tolerance_minutes=15)
    report = aligned.report.to_dict()
    print(f"rows in {report['rows_in']} → out {report['rows_out']}")
    print(f"anchor {report['anchor']} matched {report['anchors_matched']}/{report['anchors']} "
          f"({report['match_rate_pct']}%)")
    for stream in report["streams"]:
        print(f"  {stream['name']:<16} {stream['role']:<12} "
              f"{stream['matched_rows']}/{stream['rows']} joined, {stream['unmatched_rows']} unmatched")

    # A single subject's demo has one person, so the paired mode falls back to
    # time-order pairing; use examples/demo_cohort_6x6.csv for subject pairing.
    bundle = analyze(aligned.frame, paired=True)
    print(f"paired_by={bundle['meta']['comparison']['paired_by']} "
          f"n_subjects={bundle['meta']['comparison']['n_subjects']}")

    for row in bundle["comparison"][:3]:
        print(f"  {row['metric']:>5}: {row['mean_a']} vs {row['mean_b']} "
              f"(Δ {row['diff']}, d_z={row['cohens_dz']}, perm p={row['permutation_p']})")

    for row in bundle["correlations"][:3]:
        print(f"  {row['x']:>11} × {row['y']:<5}: r={row['pearson_r']} "
              f"ρ={row['spearman_rho']} slope={row['slope']} n={row['n']}")

    markdown = exporter.to_markdown(bundle, here / "heartmetric_align_report.md")
    workbook = exporter.save(bundle, here / "heartmetric_align_report.xlsx")
    print(f"markdown: {markdown}")
    print(f"workbook: {workbook}")


if __name__ == "__main__":
    main()
