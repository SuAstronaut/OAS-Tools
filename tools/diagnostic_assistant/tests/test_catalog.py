"""Synthetic-only discovery/reader regression tests."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import discover
from main import main
from parser import classify, parse_file
from reader import FIXTURE_ROOT, collect
from report import five_answers


def line(body, time="19:02:00.000", source="script.py"):
    return f"2026-09-27 {time} | {source}:0123 | INFO | {body}\n"


class UIRegressionTests(unittest.TestCase):
    def test_real_source_fixture_and_semantics(self):
        item = collect(["log/2026-10-02_logger_ui.txt"], None, FIXTURE_ROOT)[0]
        parse_file(item)
        self.assertEqual([e.fields["page"] for e in item.events if e.kind == "page"], ["page_main"])
        answers = five_answers(item)
        self.assertIn("当前页面 unknown", answers[1].text)
        self.assertIn("游戏响应 unknown", answers[2].text)
        self.assertEqual(answers[4].status, "unknown")

    def test_both_sources_strict(self):
        for source in ("logger.py", "game_ui.py"):
            self.assertEqual(classify("[UI] page_main", source, "INFO")[0], "page")
            for body in ("[UI] page main", "locals [UI] page_main", "[UI] page_main extra", "[UI] " + "a"*129):
                self.assertEqual(classify(body, source, "INFO")[0], "unknown")

    def test_other_sources_and_arrival_stay_restricted(self):
        self.assertEqual(classify("[UI] page_main", "unknown.py", "INFO")[0], "unknown")
        self.assertEqual(classify("Page arrived page_main", "logger.py", "INFO")[0], "unknown")
        self.assertEqual(classify("Page switch: page_main -> page_other", "game_ui.py", "INFO")[0], "page_plan")


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.log = self.root / "log"
        self.log.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name="2026-09-27_桌面版.txt", text=None):
        path = self.log / name
        path.write_text(text or line("Scheduler: Start task `BondlingFairyland`") + line("Current tasks: 契灵之境", source="battle.py"), encoding="utf-8")
        return path

    def get(self, **kwargs):
        return discover(self.log, self.root, **kwargs)

    def test_date_instance_keyword_and_refs(self):
        self.write()
        self.write("2026-09-28_Other.txt")
        data = self.get(date_from=date(2026,9,27), date_to=date(2026,9,27), instance="桌面版", keyword="契灵")
        self.assertEqual(len(data["logs"]), 1)
        item = data["logs"][0]
        self.assertEqual(item["filename_instance"]["value"], "桌面版")
        self.assertEqual(item["instance"]["status"], "inferred")
        self.assertEqual(item["keyword"]["status"], "confirmed")
        self.assertTrue(item["keyword"]["evidence"])
        self.assertEqual(len(item["task_clues"]), 2)
        self.assertEqual(item["actual_run_range"]["status"], "unknown")

    def test_unrelated_complete_file_not_labeled_match(self):
        self.write(text=line("Scheduler: Start task `Other`"))
        item = self.get(keyword="契灵")["logs"][0]
        self.assertEqual(item["keyword"]["value"], False)
        self.assertEqual(item["keyword"]["status"], "confirmed")

    def test_partial_absence_is_unknown(self):
        self.write(text=line("nothing")*2000)
        item = self.get(keyword="契灵", per_file=1024)["logs"][0]
        self.assertEqual(item["keyword"]["status"], "unknown")
        self.assertLessEqual(item["read_bytes"], 1024)
        self.assertEqual(item["failure_presence"]["status"], "unknown")

    def test_truncated_and_invalid_utf8_absence_unknown(self):
        path = self.write()
        for raw in (line("nothing").encode() + b"unfinished", line("nothing").encode() + b"\xff\n"):
            path.write_bytes(raw)
            item = self.get(keyword="契灵")["logs"][0]
            self.assertEqual(item["keyword"]["status"], "unknown")
            self.assertEqual(item["failure_presence"]["status"], "unknown")

    def test_actual_io_budgets_and_max_candidates(self):
        for index in range(4):
            self.write(f"2026-09-27_{index}.txt", line("nothing")*2000)
        actual = []
        from catalog import Budget
        original = Budget.read
        def read(budget, *args):
            data = original(budget, *args)
            actual.append(len(data))
            return data
        with patch.object(Budget, "read", read):
            data = self.get(per_file=101, total=150, max_candidates=3)
        self.assertEqual(sum(actual), data["read_bytes"])
        self.assertLessEqual(sum(actual), 150)
        self.assertEqual(len(data["logs"]), 3)
        self.assertEqual(data["omitted_candidates"], 1)
        self.assertTrue(all(e["read_bytes"] <= 101 for e in data["logs"]))

    def test_locator_budget_and_time_filter(self):
        self.write(text=line("old", time="18:00:00.000")*500 + line("契灵", source="battle.py")*500 + line("late", time="20:00:00.000")*500)
        data = self.get(keyword="契灵", start=datetime(2026,9,27,19,1,30), end=datetime(2026,9,27,19,3,30), per_file=32768, total=32768)
        self.assertLessEqual(data["read_bytes"],32768)
        self.assertTrue(data["logs"][0]["keyword"]["value"])

    def test_time_filter_does_not_use_outside_keyword(self):
        self.write(text=line("契灵",time="18:00:00.000") + line("Other"))
        item = self.get(keyword="契灵",start=datetime(2026,9,27,19,0),end=datetime(2026,9,27,20,0))["logs"][0]
        self.assertFalse(item["keyword"]["value"])

    def test_invalid_limits_and_dates(self):
        for kwargs in ({"total":0},{"per_file":0},{"max_candidates":65},{"date_from":date(2026,9,28),"date_to":date(2026,9,27)}, {"start":datetime(2026,9,27)}, {"keyword":"x\n"}):
            with self.assertRaises(ValueError):
                self.get(**kwargs)

    def test_root_escape(self):
        with self.assertRaises(ValueError):
            discover(self.root,self.root)
        outside = self.root / "other" / "log"
        outside.mkdir(parents=True)
        with self.assertRaises(ValueError):
            discover(outside,self.root)

    def test_hardlink_escape(self):
        import os
        outside = self.root / "secret.txt"
        outside.write_text("SYNTHETIC SECRET")
        os.link(outside,self.log / "2026-09-27_escape.txt")
        with self.assertRaises(ValueError):
            self.get()

    def test_reparse_root_rejected(self):
        actual = self.log.lstat()
        original = Path.lstat
        class Reparse:
            st_mode = actual.st_mode
            st_file_attributes = 0x400
        def fake(path,*args,**kwargs):
            return Reparse() if path == self.log else original(path,*args,**kwargs)
        with patch.object(Path,"lstat",fake), self.assertRaises(ValueError):
            self.get()

    def test_error_package_unknown_without_body_read(self):
        package = self.log / "error" / "1790500000000"
        package.mkdir(parents=True)
        (package / "log.txt").write_text("MUST NOT READ")
        (package / "screen.png").write_bytes(b"MUST NOT OPEN")
        data = self.get(include_errors=True)
        self.assertEqual(data["read_bytes"],0)
        self.assertEqual(data["error_packages"][0]["instance"]["status"],"unknown")

    def test_underscore_names_not_normalized(self):
        self.write("2026-09-27_A_B.txt")
        self.write("2026-09-27_AB.txt")
        data = self.get(instance="A_B")
        self.assertEqual(len(data["logs"]),1)
        self.assertEqual(data["logs"][0]["filename_instance"]["value"],"A_B")

    def test_stat_and_start_and_failure(self):
        self.write(text="════════════════════════════════════════\n─────────────── START ──────────────────\n════════════════════════════════════════\n" + line('[STAT] {"ev":"task_start","task":"BondlingFairyland"}',source="stat_log.py") + line('[STAT] {"ev":"task_end","task":"BondlingFairyland","ok":false}',source="stat_log.py"))
        item = self.get()["logs"][0]
        self.assertEqual(len(item["start_clues"]),1)
        self.assertEqual(item["failure_marker_count"]["value"],1)

    def test_cli_dispatch_json(self):
        self.write()
        with patch("catalog.OAS_ROOT",self.root),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["catalog","--log-root",str(self.log),"--date","2026-09-27"]),0)
        self.assertEqual(len(json.loads(out.getvalue())["logs"]),1)


if __name__ == "__main__":
    unittest.main()
