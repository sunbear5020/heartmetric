"""Headless functional check of web/app.js using QuickJS + a tiny DOM stub.

This is a test harness (not part of the site): it runs the real workbench
script, then exercises the functions the page exposes and prints the numbers so
they can be compared with the Python engine.
"""

from __future__ import annotations

import json
import pathlib
import sys

import quickjs

HERE = pathlib.Path(__file__).resolve().parent
APP = (HERE.parent / "web" / "app.js").read_text(encoding="utf-8")

DOM_STUB = r"""
class FakeCtx {
  setTransform() {} clearRect() {} beginPath() {} moveTo() {} lineTo() {}
  stroke() {} fill() {} arc() {} fillRect() {} fillText() {} setLineDash() {}
}
class FakeEl {
  constructor(id) {
    this.id = id; this.innerHTML = ''; this.textContent = ''; this.className = '';
    this.disabled = false; this.value = ''; this.files = null; this.dataset = {};
    this.classList = { add() {}, remove() {} };
    this.children = []; this.style = {};
    this.clientWidth = 640; this.clientHeight = 240; this.width = 640; this.height = 240;
  }
  addEventListener() {}
  removeEventListener() {}
  querySelector() { return new FakeEl('child'); }
  querySelectorAll() { return []; }
  appendChild() {}
  remove() {}
  click() {}
  getContext() { return new FakeCtx(); }
  focus() {}
  setAttribute() {}
}
const ELEMENTS = {};
globalThis.document = {
  readyState: 'complete',
  getElementById(id) { if (!ELEMENTS[id]) ELEMENTS[id] = new FakeEl(id); return ELEMENTS[id]; },
  querySelector() { return new FakeEl('sel'); },
  querySelectorAll() { return []; },
  createElement() { return new FakeEl('created'); },
  addEventListener() {},
  body: new FakeEl('body'),
};
globalThis.window = globalThis;
globalThis.devicePixelRatio = 1;
globalThis.console = { log() {}, warn() {}, error() {} };
globalThis.addEventListener = function () {};
globalThis.URL = { createObjectURL() { return 'blob:x'; }, revokeObjectURL() {} };
globalThis.Blob = function (parts, options) { this.parts = parts; this.options = options; };
globalThis.setTimeout = function () { return 1; };
globalThis.clearTimeout = function () {};
"""

CSV_BP = """timestamp,subject_id,condition,sbp,dbp
2026-05-06 07:10,S-01,forest,126,78
2026-05-06 08:00,S-01,urban,134,84
2026-05-07 07:10,S-01,forest,124,77
2026-05-07 08:00,S-01,urban,133,83
"""
CSV_WEAR = """timestamp,subject_id,hr,rmssd,sdnn
2026-05-06 07:12,S-01,68,44,90
2026-05-06 08:03,S-01,72,38,80
2026-05-07 07:08,S-01,66,46,92
2026-05-07 08:05,S-01,73,37,79
"""
CSV_ENV = """timestamp,subject_id,pm25,temp_c,green_index
2026-05-06 07:05,S-01,8,23,0.8
2026-05-06 08:05,S-01,27,26,0.1
2026-05-07 07:06,S-01,9,22.5,0.79
2026-05-07 08:02,S-01,25,25.8,0.12
"""

CHECK = r"""
(() => {
  const H = window.HEARTMETRIC;
  const out = { version: H.version, schema: H.schemaVersion };
  out.demo = { rows: H.state.rows.length, qcRows: H.state.qc.rowsOut, subjects: H.state.qc.subjects.length };

  const unpaired = H.compareTable(H.state.rows, ['sbp'], 'forest', 'urban', false);
  out.unpaired = { mode: unpaired.mode, n: unpaired.rows.length,
    meanA: unpaired.rows[0].meanA, meanB: unpaired.rows[0].meanB, p: unpaired.rows[0].p };

  const paired = H.compareTable(H.state.rows, ['sbp'], 'forest', 'urban', true);
  out.pairedSingle = { mode: paired.mode, dz: paired.rows[0].dz, permP: paired.rows[0].permP, note: paired.note };

  const corr = H.correlationRow(H.state.rows, 'pm25', 'sbp');
  out.corr = { r: corr.r, rho: corr.rho, slope: corr.slope, p: corr.rP, n: corr.n };

  const cohort = H.generateCohort(6, 8, 123);
  out.cohort = { rows: cohort.length, subjects: new Set(cohort.map(r => r.subject_id)).size };

  const split = (rows) => ([
    { name: 'cuff_bp.csv', rows: rows.map(r => ({ timestamp: new Date(r.timestamp), subject_id: r.subject_id, condition: r.condition, sbp: r.sbp, dbp: r.dbp })) },
    { name: 'wearable.json', rows: rows.map(r => ({ timestamp: new Date(r.timestamp.getTime() + 3 * 60000), subject_id: r.subject_id, condition: r.condition, hr: r.hr, rmssd: r.rmssd, sdnn: r.sdnn })) },
    { name: 'environment.csv', rows: rows.map(r => ({ timestamp: new Date(r.timestamp.getTime() - 7 * 60000), subject_id: r.subject_id, condition: r.condition, pm25: r.pm25, temp_c: r.temp_c, green_index: r.green_index, forest: r.forest })) },
  ]);
  const streams = split(cohort);
  const aligned = H.alignStreams(streams, 30, 'tolerance');
  out.alignment = {
    mode: aligned.report.mode, anchors: aligned.report.anchors, matched: aligned.report.anchors_matched,
    rate: aligned.report.match_rate_pct, rowsIn: aligned.report.rows_in, rowsOut: aligned.report.rows_out,
    streams: aligned.report.streams.map(s => [s.name, s.role, s.matched_rows, s.rows, s.unmatched_rows]),
    warnings: aligned.report.warnings,
  };

  const cleaned = H.cleanRows(aligned.rows.map(r => ({ ...r })));
  out.mergedQc = { rowsOut: cleaned.qc.rowsOut, subjects: cleaned.qc.subjects.length, conditions: cleaned.qc.conditions, flags: cleaned.qc.flagged };

  const mergedCompare = H.compareTable(cleaned.rows, ['sbp', 'rmssd'], 'forest', 'urban', true);
  out.subjectPaired = {
    mode: mergedCompare.mode, nSubjects: mergedCompare.nSubjects,
    rows: mergedCompare.rows.map(r => ({ metric: r.metric, meanA: r.meanA, meanB: r.meanB, dz: r.dz, p: r.p, perm: r.permP, sign: r.signP, n: r.nA })),
  };

  const daily = H.alignStreams(streams, 0, 'daily');
  out.daily = { rows: daily.rows.length, matched: daily.report.anchors_matched, anchors: daily.report.anchors,
    first: { sbp: daily.rows[0].sbp, rmssd: daily.rows[0].rmssd, pm25: daily.rows[0].pm25 } };

  const bp = H.loadText(JSON.parse(__CSV_BP__), 'bp.csv');
  const wear = H.loadText(JSON.parse(__CSV_WEAR__), 'wear.csv');
  const env = H.loadText(JSON.parse(__CSV_ENV__), 'env.csv');
  out.csvRoles = [H.roleOf(bp.rows), H.roleOf(wear.rows), H.roleOf(env.rows)];
  const three = H.alignStreams([{ name: 'bp.csv', rows: bp.rows }, { name: 'wear.csv', rows: wear.rows }, { name: 'env.csv', rows: env.rows }], 15, 'tolerance');
  out.threeCsv = { rows: three.rows.length, matched: three.report.anchors_matched,
    sbp: three.rows[0].sbp, rmssd: three.rows[0].rmssd, pm25: three.rows[0].pm25 };

  const tight = H.alignStreams([{ name: 'bp.csv', rows: bp.rows }, { name: 'wear.csv', rows: wear.rows }], 0, 'tolerance');
  out.zeroTolerance = { rows: tight.rows.length, matched: tight.report.anchors_matched };

  const bundle = H.buildBundle();
  out.bundle = { schema: bundle.meta.schema_version, version: bundle.meta.heartmetric_version,
    alignment: Boolean(bundle.meta.alignment), correlations: bundle.correlations.length,
    methodology: Object.keys(bundle.methodology.indicators).length, series: bundle.series.length,
    multiple: bundle.meta.multiple_comparison, gap: bundle.timeline_gap_map && bundle.timeline_gap_map.summary };
  out.bundleJson = JSON.stringify(bundle).length;
  const md = H.markdownReport();
  out.markdown = { chars: md.length, sections: ['# HEARTMETRIC 분석 리포트', '## 3. 조건별 비교', '## 5. 스트림 타임라인 갭 맵', '## 7. 지표 정의와 경계'].every(s => md.includes(s)), q: md.includes('q_bh') };

  // ---- v0.3: BH-FDR / Holm beside the raw p
  const ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216, 0.222, 0.251];
  out.multiple = { bh: H.benjaminiHochberg(ps), holm: H.holmBonferroni(ps) };
  const table = H.compareTable(H.state.rows, ['sbp', 'dbp', 'map', 'pp', 'hr', 'rmssd', 'sdnn', 'env_load'], 'forest', 'urban', false);
  out.fdrTable = { family: table.multiple.family_size, rejected: table.multiple.rejected_bh_fdr,
    rows: table.rows.map(r => ({ metric: r.metric, p: r.p, q: r.qBH, holm: r.pHolm, sig: r.sigFDR })) };

  // ---- v0.3: overnight_morning preset + timeline gap map
  const demo = H.generateDemo(6, 123, '2026-05-06', 'S-01', false);
  const minute = (d) => d.getHours() * 60 + d.getMinutes();
  const shift = (d, m) => new Date(d.getTime() + m * 60000);
  const morning = demo.filter(r => minute(r.timestamp) === 430).map(r => ({ timestamp: r.timestamp, subject_id: r.subject_id, condition: r.condition, sbp: r.sbp, dbp: r.dbp }));
  const night = demo.filter(r => minute(r.timestamp) === 180).map(r => ({ timestamp: r.timestamp, subject_id: r.subject_id, hr: r.hr, rmssd: r.rmssd }));
  const overnightEnv = demo.filter(r => minute(r.timestamp) === 430 || minute(r.timestamp) === 1300).map(r => ({ timestamp: shift(r.timestamp, minute(r.timestamp) === 430 ? -7 : -5), subject_id: r.subject_id, pm25: r.pm25, temp_c: r.temp_c, green_index: r.green_index }));
  const nightStreams = [{ name: 'morning_cuff.csv', rows: morning }, { name: 'night_wearable.json', rows: night }, { name: 'morning_env.csv', rows: overnightEnv }];
  const overnight = H.alignStreams(nightStreams, 0, 'overnight_morning');
  out.overnight = {
    mode: overnight.report.mode, anchors: overnight.report.anchors, matched: overnight.report.anchors_matched,
    rate: overnight.report.match_rate_pct, lookback: overnight.report.overnight_lookback_hours,
    window: overnight.report.morning_window, lag: overnight.report.lag_minutes,
    matches: overnight.report.matches.length, reasons: overnight.report.unmatched_reasons,
    first: { rmssd: overnight.rows[0].rmssd, pm25: overnight.rows[0].pm25, flags: overnight.rows[0].flags },
  };
  const gap = H.buildTimelineGapMap(nightStreams, overnight.report);
  out.gapMap = { dates: gap.summary.dates, streams: gap.summary.streams, cells: gap.summary.cells,
    matched: gap.summary.cells_matched, partial: gap.summary.cells_partial, missing: gap.summary.cells_missing,
    coverage: gap.summary.coverage_pct };

  // the panel path: the demo button drives renderFiles → mergeStreams → renderAll
  H.loadOvernightDemo();
  out.uiOvernightDemo = { files: H.state.files.length, mode: H.state.alignment && H.state.alignment.mode,
    rows: H.state.rows.length, gapCells: H.state.gapMap ? H.state.gapMap.summary.cells : 0,
    bundleGap: H.buildBundle().timeline_gap_map ? H.buildBundle().timeline_gap_map.summary.cells_missing : null };
  return out;
})()
"""


EXPECTED_BH = [0.012, 0.048, 0.1008, 0.1008, 0.1008, 0.12, 0.12686, 0.24218, 0.24218,
               0.24218, 0.24218, 0.251]
EXPECTED_HOLM = [0.012, 0.088, 0.39, 0.39, 0.39, 0.42, 0.444, 1.0, 1.0, 1.0, 1.0, 1.0]


def verify(result: dict) -> list[str]:
    """Checks the run must satisfy; returns the failures (empty means pass)."""
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if not condition:
            failures.append(f"{label}{(': ' + detail) if detail else ''}")

    check("version 0.3.0", result.get("version") == "0.3.0" and result.get("schema") == "0.3.0",
          str(result.get("version")))
    check("demo rows", result["demo"]["rows"] > 0)
    check("welch row", result["unpaired"]["n"] == 1)
    check("paired mode", result["pairedSingle"]["mode"] in {"subject", "row"})
    check("correlation r", abs(result["corr"]["r"]) <= 1)
    check("alignment matched", result["alignment"]["matched"] > 0)
    check("three csv joined", result["threeCsv"]["sbp"] == 126 and result["threeCsv"]["rmssd"] == 44)
    check("zero tolerance unmatched", result["zeroTolerance"]["matched"] == 0)
    check("bundle schema", result["bundle"]["schema"] == "0.3.0", str(result["bundle"]["schema"]))
    check("markdown sections", result["markdown"]["sections"] is True)
    check("markdown q column", result["markdown"]["q"] is True)

    bh = [round(float(v), 5) for v in result["multiple"]["bh"]]
    holm = [round(float(v), 5) for v in result["multiple"]["holm"]]
    check("BH matches SciPy values", bh == [round(v, 5) for v in EXPECTED_BH], str(bh))
    check("Holm matches statsmodels values", holm == [round(v, 5) for v in EXPECTED_HOLM], str(holm))
    table = result["fdrTable"]
    check("family size", table["family"] == len(table["rows"]), str(table["family"]))
    check("FDR rejects some", table["rejected"] >= 1)
    for row in table["rows"]:
        check(f"{row['metric']} q >= p", row["q"] >= row["p"] - 1e-12)
        check(f"{row['metric']} holm >= bh", row["holm"] >= row["q"] - 1e-12)

    overnight = result["overnight"]
    check("overnight mode", overnight["mode"] == "overnight_morning")
    check("overnight anchors matched", overnight["matched"] == overnight["anchors"] and overnight["anchors"] > 0)
    check("overnight lookback", overnight["lookback"] == 14)
    check("overnight lag recorded", overnight["lag"]["n"] == overnight["matches"] > 0)
    check("overnight flag", "align:overnight_morning" in str(overnight["first"]["flags"]))
    check("overnight merged night value", overnight["first"]["rmssd"] is not None)

    gap = result["gapMap"]
    check("gap cells", gap["cells"] == gap["dates"] * gap["streams"], str(gap))
    check("gap matched cells", gap["matched"] > 0)
    check("gap coverage", gap["coverage"] > 0)

    ui = result["uiOvernightDemo"]
    check("UI overnight demo", ui["mode"] == "overnight_morning" and ui["rows"] > 0 and ui["gapCells"] > 0, str(ui))
    return failures


def main() -> int:
    ctx = quickjs.Context()
    ctx.eval(DOM_STUB)
    ctx.eval(APP)
    script = (
        CHECK.replace("__CSV_BP__", json.dumps(json.dumps(CSV_BP)))
        .replace("__CSV_WEAR__", json.dumps(json.dumps(CSV_WEAR)))
        .replace("__CSV_ENV__", json.dumps(json.dumps(CSV_ENV)))
    )
    raw = ctx.eval(script)
    raw = ctx.eval("JSON.stringify(" + "(" + script + "))") if not isinstance(raw, (dict, list, str)) else raw
    result = raw if isinstance(raw, (dict, list)) else json.loads(raw)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    failures = verify(result)
    if failures:
        print("\nFAILED CHECKS:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"\nall checks passed ({len(result)} sections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
