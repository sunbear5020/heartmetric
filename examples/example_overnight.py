"""v0.3 overnight_morning example: a nightly wearable file + a morning cuff file.

    python examples/example_overnight.py

`examples/streams/night_wearable.csv` holds the wearable's night aggregate
(03:00 of each day, like an Oura nightly summary), `morning_cuff.csv` the one
cuff reading taken after waking (07:10), and `morning_environment.csv` the
logger's morning row (07:03) and the previous evening's row (21:35).

They never share a timestamp, so the `overnight_morning` preset anchors on the
morning cuff and looks back over the night. Every match carries its lag in
minutes; every miss carries its reason. The timeline gap map then states, per
day and per stream, which rows were joined and which days are simply absent —
without filling anything in.
"""

from __future__ import annotations

from pathlib import Path

from heartmetric_core import align, analyze, exporter


def main() -> None:
    here = Path(__file__).resolve().parent
    streams = [
        here / "streams" / "morning_cuff.csv",
        here / "streams" / "night_wearable.csv",
        here / "streams" / "morning_environment.csv",
    ]

    aligned = align.align_streams([str(path) for path in streams], mode="overnight_morning")
    report = aligned.report.to_dict()
    print(f"preset {report['mode']} · morning window {report['morning_window']} · "
          f"look-back {report['overnight_lookback_hours']} h")
    print(f"rows in {report['rows_in']} → out {report['rows_out']} · "
          f"anchors matched {report['anchors_matched']}/{report['anchors']} ({report['match_rate_pct']}%)")
    for stream in report["streams"]:
        print(f"  {stream['name']:<24} {stream['role']:<12} "
              f"{stream['matched_rows']}/{stream['rows']} joined, {stream['unmatched_rows']} unmatched")
    lag = report["lag_minutes"]
    print(f"  lag minutes: n={lag['n']} min={lag.get('min')} median={lag.get('median')} max={lag.get('max')}")
    for reason, count in (report["unmatched_reasons"] or {}).items():
        print(f"  unmatched {reason}: {count}")

    gap = align.build_timeline_gap_map([str(path) for path in streams], aligned.report)
    summary = gap["summary"]
    print(f"gap map: {summary['dates']} days × {summary['streams']} streams · "
          f"matched {summary['cells_matched']} · partial {summary['cells_partial']} · "
          f"unmatched {summary['cells_unmatched']} · missing {summary['cells_missing']} "
          f"(coverage {summary['coverage_pct']}%)")

    bundle = analyze(aligned.frame, alignment=report)
    bundle["alignment"] = report
    bundle["timeline_gap_map"] = gap
    print(f"paired_by={bundle['meta']['comparison']['paired_by']} "
          f"family m={bundle['meta']['multiple_comparison']['family_size']}")
    for row in bundle["comparison"][:4]:
        print(f"  {row['metric']:>9}: {row['mean_a']} vs {row['mean_b']} "
              f"(p={row['p_value']}, q(BH)={row['q_value_bh']}, p(Holm)={row['p_holm']})")

    markdown = exporter.to_markdown(bundle, here / "heartmetric_overnight_report.md")
    workbook = exporter.save(bundle, here / "heartmetric_overnight_report.xlsx")
    print(f"markdown: {markdown}")
    print(f"workbook: {workbook}")


if __name__ == "__main__":
    main()
