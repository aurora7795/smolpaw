"""compare_runs (#132): the Fisher exact p against known values, and pooling over fixture logs. No model needed."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tests import compare_runs as c  # noqa: E402

failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


def near(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


# Known values: the lady tasting tea (4/4 vs 0/4 is 1/70); equal arms give p = 1 at the extreme; identical rates give above 0.5
check("fisher 4/4 against 0/4 is 1/70", near(c.fisher_greater(4, 4, 0, 4), 1 / 70))
check("fisher 3/3 against 0/3 is 1/20", near(c.fisher_greater(3, 3, 0, 3), 1 / 20))
check("fisher 0/5 against 5/5 is 1", near(c.fisher_greater(0, 5, 5, 5), 1.0))
check("fisher 5/10 against 5/10 is above 0.5", c.fisher_greater(5, 10, 5, 10) > 0.5)
check("fisher 9/12 against 4/12 matches a brute-force count over all 24-run arrangements (0.049766)",
      abs(c.fisher_greater(9, 12, 4, 12) - 0.04976635963309809) < 1e-9)

tmp = Path(tempfile.mkdtemp())


def log(name: str, model: str, label: str, passes: list[bool], stalled: int = 0) -> None:
    runs = [{"passed": p, "stalled": i < stalled, "steps": 4, "input_tokens": 1000, "wall_s": 10.0} for i, p in enumerate(passes)]
    (tmp / name).write_text(json.dumps({"model": model, "label": label, "runs": runs}))


log("eval-a1.json", "m1", "housekeeping-x", [True, True, True])
log("eval-a2.json", "m1", "housekeeping-x", [True, True, False], stalled=1)
log("eval-a3.json", "m1", "tracking-y", [False, False, False])  # another family
log("eval-b1.json", "m1", "housekeeping-x", [False, False, True])
log("eval-b2.json", "m2", "housekeeping-x", [True, False, False])
(tmp / "eval-bad.json").write_text("[1, 2]")  # an older shape with no runs list
(tmp / "eval-junk.json").write_text("not json")

a = c.pool(c.load(str(tmp / "eval-a*.json"), "housekeeping"))
check("pooling keeps the family and sums runs, passes, stalls", a["m1"]["n"] == 6 and a["m1"]["passed"] == 5 and a["m1"]["stalled"] == 1)
check("pooling counts the logs per model", a["m1"]["files"] == 2)
check("without --family every shape-valid log is pooled", c.pool(c.load(str(tmp / "eval-a*.json"), None))["m1"]["n"] == 9)
check("malformed logs are skipped", len(c.load(str(tmp / "eval-*.json"), None)) == 5)
b = c.pool(c.load(str(tmp / "eval-b*.json"), None))
check("models stay separate", set(b) == {"m1", "m2"} and b["m2"]["n"] == 3)

import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402

buf = io.StringIO()
with redirect_stdout(buf):
    rc = c.main(["--arm", f"A={tmp}/eval-a*.json", "--arm", f"B={tmp}/eval-b*.json", "--family", "housekeeping"])
out = buf.getvalue()
check("the report prints both arms, the pass counts and a one-sided p for the shared model",
      rc == 0 and "5/6" in out and "1/3" in out and "Fisher exact, one-sided, A better than B" in out)
check("the report notes the small-n limit", "Small n shows little" in out)

# Outliers (#134): one runaway run moves the mean; the report shows the median and names the run.
runs = [{"passed": True, "steps": 3, "input_tokens": 100, "wall_s": s} for s in (50.0, 60.0, 3152.0, 55.0, 52.0)]
(tmp / "outlier-1.json").write_text(json.dumps({"model": "m3", "label": "x", "runs": runs}))
(tmp / "outlier-2.json").write_text(json.dumps({"model": "m3", "label": "x", "runs": [dict(runs[0]), dict(runs[1])]}))
pooled = c.pool(c.load(str(tmp / "outlier-1.json"), None))["m3"]
check("outliers lists the runaway run with its seconds and run number",
      [(t, i) for t, _, i in c.outliers(pooled)] == [(3152.0, 3)])
check("a cell with no runaway run lists no outliers", c.outliers(c.pool(c.load(str(tmp / "outlier-2.json"), None))["m3"]) == [])
buf = io.StringIO()
with redirect_stdout(buf):
    c.main(["--arm", f"O={tmp}/outlier-1.json"])
out = buf.getvalue()
check("the report prints the mean, the median and the outlier's log file",
      "mean  674s" in out and "median   55s" in out and "outlier: 3152s" in out and "run 3 of outlier-1.json" in out)

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
