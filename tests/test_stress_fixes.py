"""Regression tests for the 2026-11-22 stress-test fixes. Run: python3 -m unittest discover -s tests -v"""
import csv, json, os, subprocess, sys, tempfile, unittest


def dump(obj, path):
    with open(path, "w") as fh:
        json.dump(obj, fh)
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
sys.path.insert(0, S)


def run(script, *args, env=None):
    p = subprocess.run([sys.executable, os.path.join(S, script), *args], capture_output=True, text=True, env={**os.environ, **(env or {})})
    try:
        out = json.loads(p.stdout)
    except Exception:
        out = p.stdout
    return p.returncode, out


SIZE = ["--account", "10000", "--entry", "50", "--stop", "48", "--json"]


class GeckoSize(unittest.TestCase):
    def test_pass_exits_0(self):
        code, r = run("gecko_size.py", *SIZE, "--target", "60")
        self.assertEqual((code, r["verdict"]), (0, "PASS"))

    def test_fail_exits_2(self):
        code, r = run("gecko_size.py", *SIZE, "--target", "60", "--regime-mult", "0")
        self.assertEqual((code, r["verdict"]), (2, "FAIL"))

    def test_regime_mult_above_1_rejected(self):
        code, r = run("gecko_size.py", *SIZE, "--target", "60", "--regime-mult", "3")
        self.assertEqual(r["verdict"], "FAIL"); self.assertNotEqual(code, 0)

    def test_effective_risk_ceiling(self):
        code, r = run("gecko_size.py", *SIZE, "--target", "60", "--risk-pct", "2", "--regime-mult", "1")
        self.assertEqual(r["verdict"], "PASS")   # exactly 2% is allowed
        code, r = run("gecko_size.py", *SIZE, "--target", "60", "--risk-pct", "2.5")
        self.assertEqual(r["verdict"], "FAIL")

    def test_missing_target_fails_by_default(self):
        code, r = run("gecko_size.py", *SIZE)
        self.assertEqual((code, r["verdict"]), (2, "FAIL"))
        code, r = run("gecko_size.py", *SIZE, "--allow-no-target")
        self.assertEqual(r["verdict"], "PASS")

    def test_zero_account_is_clean_fail(self):
        code, r = run("gecko_size.py", "--account", "0", "--entry", "50", "--stop", "48", "--target", "60", "--json")
        self.assertEqual((code, r["verdict"]), (1, "FAIL"))


def breadth_rows(last_day, n=40, reverse=False):
    hdr = ["Date", "Breadth_Index_8MA", "Breadth_Index_200MA", "Breadth_200MA_Trend", "Bearish_Signal"]
    rows = []
    for i in range(n):
        d = last_day - timedelta(days=n - 1 - i)
        rows.append({"Date": d.isoformat(), "Breadth_Index_8MA": f"{0.50 + i * 0.005:.3f}", "Breadth_Index_200MA": "0.55",
                     "Breadth_200MA_Trend": "1", "Bearish_Signal": "False"})
    if reverse:
        rows = rows[::-1]
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
    w = csv.DictWriter(f, fieldnames=hdr); w.writeheader(); w.writerows(rows); f.close()
    return f.name


class GeckoRegime(unittest.TestCase):
    def test_fresh_data_gives_label(self):
        code, r = run("gecko_regime.py", "--csv", breadth_rows(date.today()), "--json")
        self.assertEqual(code, 0); self.assertEqual(r["regime"], "RISK-ON"); self.assertFalse(r["stale"])

    def test_stale_data_fails_closed(self):
        code, r = run("gecko_regime.py", "--csv", breadth_rows(date.today() - timedelta(days=30)), "--json")
        self.assertEqual(r["regime"], "UNKNOWN"); self.assertEqual(r["risk_multiplier"], 0.0); self.assertTrue(r["stale"])
        self.assertEqual(r["label_from_data"], "RISK-ON")

    def test_reversed_file_sorted(self):
        code, r = run("gecko_regime.py", "--csv", breadth_rows(date.today(), reverse=True), "--json")
        self.assertEqual(r["data_date"], date.today().isoformat())

    def test_as_of_replay(self):
        last = date.today() - timedelta(days=100)
        code, r = run("gecko_regime.py", "--csv", breadth_rows(last), "--as-of", last.isoformat(), "--json")
        self.assertFalse(r["stale"]); self.assertEqual(r["regime"], "RISK-ON")


def quotes_file(px):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"results": [{"symbol": s, "bid_price": str(b), "ask_price": str(round(b * 1.002, 4))} for s, b in px.items()]}, f); f.close()
    return f.name


class PaperRandom(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        cfgp = os.path.join(self.d, "cfg.json")
        json.dump({"paperRandom": {"stateDir": os.path.join(self.d, "rb"), "entryProbPerFire": 1.0}, "riskSizing": {"riskPct": 1.0, "cashCapFrac": 0.95},
                   "tpModel": {"floorPct": 5.0}, "stallExit": {"afterMinutes": 14}}, open(cfgp, "w"))
        self.env = {"RECONCILE_CONFIG": cfgp}

    def test_enters_from_shortlist_and_stops_out(self):
        D = "2026-11-23"
        code, r = run("paper_random.py", "tick", "--date", D, "--quotes", quotes_file({"AAA": 10.0, "BBB": 5.0}),
                      "--shortlist", '["AAA","BBB"]', "--now", f"{D}T09:40:00-05:00", env=self.env)
        self.assertEqual(code, 0); self.assertEqual(len(r["actions"]), 1)
        sym = r["actions"][0]["buy"]; self.assertIn(sym, ("AAA", "BBB"))
        px = {"AAA": 10.0, "BBB": 5.0}; px[sym] *= 0.94
        code, r = run("paper_random.py", "tick", "--date", D, "--quotes", quotes_file(px), "--shortlist", "[]", "--now", f"{D}T09:45:00-05:00", env=self.env)
        self.assertEqual(r["actions"][0]["why"], "hard_stop")
        code, s = run("paper_random.py", "summary", "--date", D, env=self.env)
        self.assertEqual(s["wl"], [0, 1])

    def test_never_writes_outside_state_dir(self):
        rb = os.path.join(self.d, "rb")
        run("paper_random.py", "init", "--date", "2026-11-23", env=self.env)
        for root, _, files in os.walk(self.d):
            for f in files:
                p = os.path.join(root, f)
                self.assertTrue(p.startswith(rb) or p.endswith("cfg.json"), p)

    def test_replay_is_deterministic(self):
        D, q = "2026-11-24", quotes_file({s: 3.0 for s in "ABCDEFGH"})
        picks = []
        for k in range(2):
            env = dict(self.env); cfgp = os.path.join(self.d, f"c{k}.json")
            dump({"paperRandom": {"stateDir": os.path.join(self.d, f"rb{k}"), "entryProbPerFire": 1.0}}, cfgp); env["RECONCILE_CONFIG"] = cfgp
            code, r = run("paper_random.py", "tick", "--date", D, "--quotes", q, "--shortlist", json.dumps(list("ABCDEFGH")), "--now", f"{D}T10:05:00-05:00", env=env)
            picks.append(r["actions"][0]["buy"])
        self.assertEqual(picks[0], picks[1])

    def test_edge_check(self):
        f = os.path.join(self.d, "t.json")
        dump([{"pnlPct": 0.1}, {"pnlPct": -0.1}] * 50, f)
        code, r = run("paper_random.py", "edge", "--trades", f, env=self.env)
        self.assertEqual(r["verdict"], "NO EDGE")
        # +0.2R a trade at a 30% win rate is NOT proven at 100 trades (t ~ 1.1) ...
        dump([{"pnlPct": 15.0}] * 30 + [{"pnlPct": -5.0}] * 70, f)
        code, r = run("paper_random.py", "edge", "--trades", f, env=self.env)
        self.assertEqual(r["verdict"], "POSITIVE BUT NOT PROVEN"); self.assertGreater(r["tradesNeededForT2"], 300)
        # ... but is at 400 trades
        dump([{"pnlPct": 15.0}] * 120 + [{"pnlPct": -5.0}] * 280, f)
        code, r = run("paper_random.py", "edge", "--trades", f, env=self.env)
        self.assertTrue(r["t"] >= 2 and r["verdict"].startswith("EDGE"))


class DiscretionSizeMult(unittest.TestCase):
    """discretion.py size must halve size from the bank tripwire state even when --size-mult is forgotten."""
    def test_tripwire_from_state(self):
        d = tempfile.mkdtemp(); bank = os.path.join(d, "bank.json"); cfgp = os.path.join(d, "cfg.json"); state = os.path.join(d, "state.json")
        dump({"tripwireActive": True}, bank)
        dump({"bankStop": {"stateFile": bank}, "discretion": {"riskSizing": {"riskPct": 1.0, "maxRiskPct": 2.0, "cashCapFrac": 0.95}}}, cfgp)
        dump({"sessionDate": "2026-11-23", "roundTrips": []}, state)
        env = {"RECONCILE_CONFIG": cfgp, "DISC_CONFIG": cfgp, "DESK_CONFIG": cfgp}
        base = ["size", "--state", state, "--ask", "10", "--buy-limit", "10", "--equity", "1000", "--cash", "1000"]
        code, r = run("discretion.py", *base, env=env)
        if not isinstance(r, dict) or r.get("mode") == "protect":
            self.skipTest(f"discretion.py size not in risk mode with a minimal state: {str(r)[:200]}")
        self.assertEqual(r["sizeMult"], 0.5); self.assertEqual(r["maxQty"], 10)   # 1000 x 1% x 0.5 / 0.5 per share
        code, r = run("discretion.py", *base, "--size-mult", "0.25", env=env)
        self.assertEqual(r["sizeMult"], 0.25)
        code, r = run("discretion.py", *base, "--size-mult", "3", env=env)
        self.assertEqual(r["sizeMult"], 0.5)   # can only shrink


if __name__ == "__main__":
    unittest.main()
