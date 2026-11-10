"""The second domain's adapter: web routes, the layout log as observations, behaviour, and the bench."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import web_bench
from expectrail.contracts import load, validate
from expectrail.evaluator import evaluate
from harness.run import REPO
from harness.web import layout
from harness.web.run import WebHarnessError, load_route

SPECS = {p.stem: load(p, "test-spec") for p in (REPO / "apps" / "checkout" / "specs").glob("*.json")}


def element(box, shown=True, painted=None):
    return {"shown": shown, "layout": list(box), "painted": list(painted or box)}


def trace(button=(332, 1358, 940, 1406), form=(332, 328, 940, 1406), logo=(764, 48, 836, 105), frames=14,
          submitted=True, **overrides):
    rows = []
    for n in range(frames):
        elements = {"button": element(button), "form": element(form), "logo": element(logo)}
        elements.update(overrides)
        rows.append({"frame": n, "step": "fill", "elements": elements})
    return {"format": "expectrail.web-trace/v0", "viewport": [1600, 1680], "rows": rows,
            "outcome": {"submitted": submitted, "error": None if submitted else "click did not go through"}}


def judged(spec_id: str, t: dict) -> str:
    spec = SPECS[spec_id]
    obs = layout.layout_observations(t, spec)
    validate(obs, "observations")
    return evaluate(spec, obs)["result"]


class LayoutTest(unittest.TestCase):
    def test_the_specs_are_valid_test_specs(self):
        self.assertEqual(sorted(SPECS), ["checkout-button-inside-form", "checkout-button-visible", "logo-visible"])

    def test_the_clean_page_passes_every_spec(self):
        for spec_id in SPECS:
            self.assertEqual(judged(spec_id, trace()), "pass", spec_id)

    def test_a_button_off_screen_or_hidden_is_not_visible(self):
        self.assertEqual(judged("checkout-button-visible", trace(button=(332, 1998, 940, 2046))), "fail")
        self.assertEqual(judged("checkout-button-visible", trace(button=(332, -400, 940, -352))), "fail")
        hidden = trace(); [r["elements"].update(button=element((332, 1358, 940, 1406), shown=False)) for r in hidden["rows"]]
        self.assertEqual(judged("checkout-button-visible", hidden), "fail")

    def test_layout_cannot_see_paint(self):
        # A transform moves what is drawn, not the layout box; opacity hides it but CSS still "shows" it.
        moved = trace(); [r["elements"].update(button=element((332, 1358, 940, 1406), painted=(332, 1394, 940, 1442)))
                          for r in moved["rows"]]
        self.assertEqual(judged("checkout-button-inside-form", moved), "pass")
        self.assertEqual(judged("checkout-button-inside-form", trace(button=(332, 1394, 940, 1442))), "fail")

    def test_sam_boxes_count_only_on_the_page_s_paint_box_for_the_element(self):
        t = trace(frames=2)
        t["rows"][1]["elements"]["button"] = element((332, 1358, 940, 1406), shown=False)
        keep = layout.agreeing(t, ["button"])
        badge = {"box": [1233, 299, 1268, 330], "score": 0.9}
        real = {"box": [333, 1357, 939, 1407], "score": 0.6}
        got = keep({0: {"button": [badge, real], "form": [badge]}, 1: {"button": [real]}})
        self.assertEqual(got[0]["button"], [real])     # the look-alike elsewhere is dropped
        self.assertEqual(got[0]["form"], [badge])      # objects it was not asked about are untouched
        self.assertEqual(got[1]["button"], [])         # hidden by CSS: nothing SAM says there counts

    def test_behaviour_is_the_order_going_through(self):
        self.assertEqual(layout.behaviour(trace())["result"], "pass")
        self.assertEqual(layout.behaviour(trace(submitted=False))["result"], "fail")

    def test_engine_objects_give_the_form_to_the_sam_adapter(self):
        objs = layout.engine_objects(trace(), ["form"])
        self.assertEqual(objs[0]["form"][0]["box"], [332, 328, 940, 1406])


class RouteTest(unittest.TestCase):
    def test_public_routes_load(self):
        for path in web_bench.ROUTES:
            route = load_route(path)
            self.assertEqual(route["steps"][0]["do"], "load")
            self.assertTrue(route["steps"][-1].get("submits"))
            for spec in SPECS.values():
                for name in spec["objects"]:
                    self.assertIn(name, route["elements"], f"{path.name} names no element {name!r}")

    def test_a_game_route_is_refused(self):
        with self.assertRaises(WebHarnessError):
            load_route(REPO / "harness" / "routes" / "smoke.json")


class BenchTest(unittest.TestCase):
    def test_eight_dev_variants_two_per_family(self):
        ids = web_bench.set_ids("dev")
        self.assertEqual(ids[0], "clean")
        self.assertEqual(len(ids), 9)
        self.assertEqual({i.split("/")[1] for i in ids[1:]}, {"layering", "missing-texture", "fall-through", "sinking"})

    def test_held_out_variants_come_from_the_private_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp) / "web"
            web.mkdir()
            (web / "manifest.json").write_text(json.dumps({"variants": [
                {"family": "layering", "id": "v3", "patch": "layering/v3.patch"},
                {"family": "sinking", "id": "v3", "patch": "sinking/v3.patch", "retired": True}]}))
            with mock.patch.dict("os.environ", {"EXPECTRAIL_HELDOUT_DIR": tmp}):
                self.assertEqual(web_bench.set_ids("held-out"), ["clean", "layering/v3"])

    def test_the_annotation_is_the_one_the_collector_reads(self):
        from agents.bench_collect import TITLE, parse_message

        per_route = [{"route": "checkout-desktop", "checks": {"layout": "pass", "behaviour": "fail"}},
                     {"route": "checkout-mobile", "checks": {"layout": "pass", "behaviour": "fail"}}]
        with mock.patch.object(web_bench, "judge_route", side_effect=[r["checks"] for r in per_route]), \
                mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"}), \
                tempfile.TemporaryDirectory() as tmp:
            doc = web_bench.bench("dev/layering/v1", Path(tmp))
        from agents.heldout_bench import annotation

        line = annotation(doc).splitlines()[0]
        title, message = line.split("title=", 1)[1].split("::", 1)
        self.assertEqual(TITLE.match(title)["id"], "dev/layering/v1")
        row = parse_message(message)
        self.assertEqual(row["caughtWithSamOff"], "yes")
        self.assertEqual(row["checks"]["behaviour"]["fail"], 2)

    def test_the_detail_line_shows_what_sam_found_against_what_the_page_drew(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "trace.json").write_text(json.dumps(trace(frames=3)))
            boxes = [{"box": [1200, 300, 1230, 322], "score": 0.71}, {"box": [10, 10, 20, 20], "score": 0.3},
                     {"box": [1300, 900, 1330, 920], "score": 0.55}]
            (run_dir / "sam-checkout-button-visible.json").write_text(json.dumps({
                "model": {"prompts": {"button": "blue button"}},
                "frames": [{"frame": 0, "objects": {"button": []}}, {"frame": 2, "objects": {"button": boxes}}]}))
            (run_dir / "sam-logo-visible.json").write_text(json.dumps({
                "model": {"prompts": {"logo": "purple logo"}}, "frames": [{"frame": 2, "objects": {"logo": []}}]}))
            seen = web_bench.sam_seen(run_dir)
        self.assertEqual(seen, ["SAM button: [1200, 300, 1230, 322] @0.71 +1 (drawn at [332, 1358, 940, 1406]); "
                                "no match, other max 0.71",
                                "SAM logo: none (drawn at [764, 48, 836, 105]); no match, other max 0.00"])
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "trace.json").write_text(json.dumps(trace(frames=3)))
            (run_dir / "sam-checkout-button-visible.json").write_text(json.dumps({
                "model": {"prompts": {"button": "blue button"}},
                "frames": [{"frame": n, "objects": {"button": [{"box": [332, 1358, 940, 1406], "score": s},
                                                              {"box": [1200, 300, 1230, 322], "score": 0.6}]}}
                           for n, s in ((0, 0.8), (1, 0.77), (2, 0.9))]}))
            seen = web_bench.sam_seen(run_dir)
        self.assertEqual(seen, ["SAM button: [332, 1358, 940, 1406] @0.90 +1 (drawn at [332, 1358, 940, 1406]); "
                                "match min 0.77 (3 frames), other max 0.60"])


@unittest.skipUnless(__import__("importlib").util.find_spec("playwright"), "playwright is not installed")
class ReplayTest(unittest.TestCase):
    def test_two_replays_are_byte_identical_and_the_clean_page_submits(self):
        from harness.web.run import run

        route = REPO / "harness" / "web" / "routes" / "checkout-desktop.json"
        with tempfile.TemporaryDirectory() as tmp:
            try:
                a = run(route, Path(tmp) / "a")
            except Exception as exc:  # noqa: BLE001 - no browser on this machine
                self.skipTest(f"chromium unavailable: {exc}")
            b = run(route, Path(tmp) / "b")
        self.assertEqual(a["frameSha256"], b["frameSha256"])
        self.assertEqual(a["capture"]["frames"], 14)
        self.assertTrue(a["trace"]["outcome"]["submitted"])


@unittest.skipUnless(__import__("importlib").util.find_spec("playwright"), "playwright is not installed")
class FixLoopTest(unittest.TestCase):
    """agents.web_fix offline: the game's fixer and the verifier's contract and decision, on the page."""

    def reverse_fix(self, key: str, tmp: Path) -> Path:
        import difflib
        import shutil
        import subprocess

        from agents.web_fix import SITE, dev_variants

        bugged = tmp / "bugged"
        shutil.copytree(SITE, bugged)
        subprocess.run(["patch", "-s", "-p1", "-d", str(bugged), "-i", str(dev_variants()[key].resolve())], check=True)
        diff = ""
        for rel in ("checkout/index.html", "checkout/checkout.css"):
            a, b = (bugged / rel).read_text().splitlines(True), (SITE / rel).read_text().splitlines(True)
            diff += "".join(difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        path = tmp / "fix.patch"
        path.write_text(diff)
        return path

    def test_a_real_fix_is_accepted_with_the_private_sessions_mounted(self):
        from agents.web_fix import run_case

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            held = tmp / "held" / "web" / "routes"
            held.mkdir(parents=True)
            (held / "a.json").write_text((REPO / "harness" / "web" / "routes" / "checkout-desktop.json").read_text())
            with mock.patch.dict("os.environ", {"EXPECTRAIL_HELDOUT_DIR": str(tmp / "held"), "EXPECTRAIL_OBS_PROVIDER": "trace"}):
                try:
                    row = run_case("dev/layering/v1", "expectrail", tmp / "out", live=False,
                                   fixture=self.reverse_fix("dev/layering/v1", tmp))
                except Exception as exc:  # noqa: BLE001 - no browser on this machine
                    self.skipTest(f"chromium unavailable: {exc}")
            self.assertEqual(row["detected"], "fail")
            self.assertEqual(row["outcome"], "fixed", row)
            v = json.loads((tmp / "out" / "dev_layering_v1" / "expectrail" / "verify" / "attempt-01" / "verification.json").read_text())
            validate(v, "verification")
            self.assertEqual({c["kind"] for c in v["checks"]}, {"regression", "gameplay", "clean", "held-out"})

    def test_without_the_private_sessions_nothing_is_accepted(self):
        from agents.web_fix import run_case

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with mock.patch.dict("os.environ", {"EXPECTRAIL_HELDOUT_DIR": "", "EXPECTRAIL_OBS_PROVIDER": "trace"}):
                row = run_case("dev/layering/v1", "expectrail", tmp / "out", live=False,
                               fixture=self.reverse_fix("dev/layering/v1", tmp))
        self.assertEqual(row["outcome"], "needs-review")

    def test_the_preflight_says_whether_each_private_session_passes_on_the_clean_page(self):
        from agents.web_fix import check_held_out

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            routes = tmp / "held" / "web" / "routes"
            routes.mkdir(parents=True)
            good = json.loads((REPO / "harness" / "web" / "routes" / "checkout-desktop.json").read_text())
            (routes / "a.json").write_text(json.dumps(good))
            # Too short for the page: the button starts below the fold, and filling the card scrolls the logo away.
            short = dict(good, viewport=[1600, 900])
            (routes / "b.json").write_text(json.dumps(short))
            (routes / "c.json").write_text("{}")
            with mock.patch.dict("os.environ", {"EXPECTRAIL_HELDOUT_DIR": str(tmp / "held")}):
                try:
                    lines = check_held_out(tmp / "out")
                except Exception as exc:  # noqa: BLE001 - no browser on this machine
                    self.skipTest(f"chromium unavailable: {exc}")
        self.assertEqual(lines, ["held-out r0: the clean page passes",
                                 "held-out r1: the clean page fails layout "
                                 "(layout: checkout-button-inside-form, checkout-button-visible, logo-visible)",
                                 "held-out r2: not a valid web route"])

    def test_a_bug_its_checks_cannot_see_is_not_detected_without_sam(self):
        from agents.web_fix import run_case

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"}):
            row = run_case("dev/layering/v2", "expectrail", Path(tmp), live=False)
        self.assertEqual(row["outcome"], "not-detected")


class JudgeTest(unittest.TestCase):
    def test_every_case_names_patches_that_exist(self):
        from agents import web_judge

        for case in web_judge.CASES:
            for patch in web_judge.patches(case):
                self.assertTrue(patch.is_file(), f"{case}: {patch}")
        labels = [v[0] for v in web_judge.CASES.values()]
        self.assertEqual((labels.count("good"), labels.count("bad")), (5, 5))

    def test_any_failing_check_rejects_and_a_missing_one_is_undecided(self):
        from agents.web_judge import decide

        self.assertEqual(decide({"layout": "pass", "behaviour": "pass"}, ["layout", "behaviour"]), "accept")
        self.assertEqual(decide({"layout": "fail", "behaviour": "pass"}, ["layout", "behaviour"]), "reject")
        self.assertEqual(decide({"layout": "pass"}, ["layout", "behaviour"]), "undecided")

    def test_collect_reads_the_annotations_back(self):
        from agents import web_judge

        doc = {"case": "bad/fix-logo-remove", "label": "bad", "failing": ["logo-visible"],
               "decisions": {"expectrailSam": "reject", "expectrailNoSam": "accept", "pixelDiff": "reject"}}
        line = web_judge.annotation(doc)
        title, message = line.split("title=", 1)[1].split("::", 1)

        def fetch(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"name": "web-judge (bad/fix-logo-remove)", "id": 1}]}
            if "/check-runs/" in path:
                return [{"title": title, "message": message}]
            return {"html_url": "https://github.com/Expectrail/Expectrail/actions/runs/9", "head_sha": "abc", "created_at": "2026-10-30T18:00:00Z"}

        back = web_judge.collect(9, fetch=fetch)
        self.assertEqual(back["rows"][0]["expectrailNoSam"], "accept")
        t = web_judge.tally(back)
        self.assertEqual(t["expectrailSam"]["badAccepted"], 0)
        self.assertEqual(t["expectrailNoSam"]["badAccepted"], 1)
        self.assertIn("| bad/fix-logo-remove", web_judge.markdown(back))


if __name__ == "__main__":
    unittest.main()
