"""All inputs are synthetic. Tests must not read any production log/config/image."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import main
from models import EvidenceFile, Line, Reference
from parser import KNOWN_EXCEPTIONS, parse_file
from reader import FIXTURE_ROOT, OAS_ROOT, TOOL_ROOT, allowed, collect, output_path, parse_time, validate_limits
from report import build_report, five_answers, markdown


def record(body, source="game_ui.py", level="INFO", time="19:00:00.000"):
    return f"2026-10-02 {time} | {source}:0123 | {level} | {body}\n"


def memory(text, start=None, end=None, minutes=30):
    item = EvidenceFile("log/2026-10-02_memory.txt", "memory", None, len(text.encode()), len(text.encode()), 0)
    offset = 0
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        length = len(raw.encode())
        item.lines.append(Line(raw.rstrip("\r\n"), Reference(item.path, offset, offset + length, number, number)))
        offset += length
    window = parse_file(item, start, end, minutes)
    return item, window


class DiagnosticTests(unittest.TestCase):
    def load(self, name, **kwargs):
        item = collect([f"log/2026-10-02_{name}.txt"], None, FIXTURE_ROOT, **kwargs)[0]
        window = parse_file(item)
        return item, window

    def data(self, item, window):
        return build_report([item], [window], {}, "synthetic")

    def codes(self, item):
        return {i.code for i in item.issues}

    def test_normal_boundaries_do_not_prove_business_success(self):
        item, window = self.load("normal")
        result = self.data(item, window)
        answers = result["sources"][0]["five_questions"]
        self.assertIn("调度结束", answers[0]["text"])
        self.assertIn("业务目标成功 unknown", answers[0]["text"])
        self.assertEqual(answers[1]["status"], "confirmed")
        self.assertIn("page_example", answers[1]["text"])
        self.assertEqual(answers[4]["status"], "unknown")
        self.assertNotIn("missing_end", self.codes(item))
        self.assertEqual({e.fields["ev"] for e in item.events if e.kind == "stat"},
                         {"run_start", "run_end", "acc_start", "acc_end", "task_start", "task_end"})

    def test_planned_destination_is_not_observed(self):
        item, window = self.load("plan")
        answers = self.data(item, window)["sources"][0]["five_questions"]
        self.assertIn("page_main", answers[1]["text"])
        self.assertNotIn("page_target", answers[1]["text"])
        self.assertIn("stale_page", self.codes(item))
        self.assertIn("target_appear_then_operate", answers[3]["text"])
        self.assertIn("游戏响应 unknown", answers[2]["text"])

    def test_backend_exception_after_click_is_not_success_or_cause(self):
        item, _ = self.load("backend")
        answers = five_answers(item)
        self.assertIn("ConnectionError", answers[4].text)
        self.assertIn("根因 unknown", answers[4].text)
        self.assertIn("后端发送/返回 unknown", answers[2].text)
        self.assertFalse(any("成功点击" in a.text for a in answers))
        self.assertTrue(any(e.kind == "traceback" for e in item.events))

    def test_taskend_does_not_override_subtask_failure(self):
        item, _ = self.load("taskend")
        answers = five_answers(item)
        self.assertIn("业务目标成功 unknown", answers[0].text)
        self.assertEqual(answers[4].status, "confirmed")
        self.assertIn("失败标记", answers[4].text)
        self.assertIn("GamePageUnknownError", answers[4].text)
        self.assertIn("因果关联 unknown", answers[4].text)
        self.assertEqual(len(answers[4].refs), 2)

    def test_folded_stat_conservative_status_and_exact_span(self):
        item, _ = self.load("folded")
        events = [e for e in item.events if e.kind == "stat"]
        self.assertEqual(len(events), 4)
        self.assertEqual(events[1].status, "inferred")
        self.assertEqual((events[1].ref.first_line, events[1].ref.last_line), (3, 5))
        self.assertEqual(events[1].fields["task"], "ExampleTask")
        self.assertEqual(five_answers(item)[4].status, "inferred")

    def test_bad_json_keeps_later_valid_evidence(self):
        item, _ = self.load("badjson")
        self.assertEqual(sum(e.kind == "invalid_stat" for e in item.events), 3)
        self.assertIn("page_main", five_answers(item)[1].text)
        self.assertNotIn("Fake", five_answers(item)[0].text)
        self.assertIn("ExampleTask", five_answers(item)[0].text)

    def test_half_json_cannot_close_task(self):
        item, window = self.load("truncated")
        self.data(item, window)
        self.assertIn("bad_stat", self.codes(item))
        self.assertIn("missing_end", self.codes(item))
        self.assertFalse(any(e.kind == "stat" and e.fields["ev"] == "task_end" for e in item.events))

    def test_crossday_start_not_new_session(self):
        item, window = self.load("crossday")
        self.data(item, window)
        self.assertIn("start_not_session", self.codes(item))
        self.assertNotIn("missing_end", self.codes(item))
        self.assertEqual(sum(e.kind == "task_start" for e in item.events), 1)
        self.assertTrue(any(e.kind == "rollover" for e in item.events))
        self.assertFalse(any("session_id" in e.fields for e in item.events))

    def test_unowned_error_package_stays_separate(self):
        files = collect(["log/2026-10-02_plan.txt"], "log/error/1790928000000", FIXTURE_ROOT)
        windows = [parse_file(i) for i in files]
        result = build_report(files, windows, {}, "synthetic")
        self.assertEqual(len(result["sources"]), 2)
        self.assertIsNone(result["sources"][1]["instance_candidate"])
        self.assertIn("unknown_package_owner", self.codes(files[1]))
        self.assertIn("page_main", result["sources"][0]["five_questions"][1]["text"])
        self.assertNotIn("page_package_only", result["sources"][0]["five_questions"][1]["text"])

    def test_underscore_collision_does_not_merge(self):
        files = collect(["log/2026-10-02_demo_alpha.txt", "log/2026-10-02_demo_beta.txt"], None, FIXTURE_ROOT)
        result = build_report(files, [parse_file(i) for i in files], {}, "synthetic")
        self.assertEqual(len(result["sources"]), 2)
        self.assertTrue(all("ambiguous_instance" in self.codes(i) for i in files))
        self.assertIn("AlphaTask", result["sources"][0]["five_questions"][0]["text"])
        self.assertNotIn("BetaTask", result["sources"][0]["five_questions"][0]["text"])

    def test_same_filename_candidate_not_process_identity(self):
        item, window = self.load("normal")
        data = self.data(item, window)["sources"][0]
        self.assertEqual(data["instance_status"], "inferred")
        self.assertIn("identity_gap", self.codes(item))

    def test_actions_waits_unknown_and_rich_fold(self):
        item, _ = self.load("extra")
        actions = [e.fields["kind"] for e in item.events if e.kind == "action"]
        self.assertEqual(actions, ["long_click", "swipe", "drag"])
        self.assertIn("scheduler_due", {e.fields["reason"] for e in item.events if e.kind == "wait"})
        self.assertIn("rich_fold", self.codes(item))
        self.assertTrue(any(e.kind == "page_plan" and e.status == "inferred" for e in item.events))
        self.assertIn("wait_or_navigation_timeout", five_answers(item)[4].text)

    def test_no_page_in_plan_only(self):
        item, _ = memory(record("Page switch: page_a -> page_b"))
        self.assertEqual(five_answers(item)[1].status, "unknown")

    def test_folded_page_not_reliable_observation(self):
        item, _ = memory(record("[UI]") + "    page_main\n")
        self.assertEqual(five_answers(item)[1].status, "unknown")

    def test_wait_alone_does_not_prove_failure(self):
        item, _ = memory(record("Waiting for page_main"))
        self.assertEqual(five_answers(item)[3].status, "confirmed")
        self.assertEqual(five_answers(item)[4].status, "unknown")

    def test_control_end_alone_has_unknown_business_outcome(self):
        item, _ = memory(record("TaskEnd final task name: ExampleTask", "script.py"))
        self.assertIn("业务目标成功 unknown", five_answers(item)[0].text)
        self.assertEqual(five_answers(item)[4].status, "unknown")

    def test_error_level_without_trigger_is_unknown(self):
        item, _ = memory(record("Synthetic operation failed", "any.py", "ERROR"))
        self.assertEqual(five_answers(item)[4].status, "unknown")

    def test_known_condition_whitelist_without_arbitrary_messages(self):
        item, _ = memory(record("GameStuckError: Wait too long", "device.py", "ERROR"))
        self.assertIn("条件 stuck_wait_too_long", five_answers(item)[4].text)
        self.assertIn("根因 unknown", five_answers(item)[4].text)
        item, _ = memory(record("Game page unknown (1/3)", "script.py", "CRITICAL"))
        self.assertIn("page_unrecognized_record", five_answers(item)[4].text)

    def test_navigation_timeout_budget_is_evidence(self):
        item, _ = memory(record("Cannot goto page[page_target], timeout[10s] reached", level="ERROR"))
        self.assertIn("局部预算(s) 10", five_answers(item)[3].text)
        self.assertEqual(five_answers(item)[1].status, "unknown")

    def test_all_known_failure_types_indexed_without_root_cause(self):
        for kind in KNOWN_EXCEPTIONS - {"TaskEnd", "CampaignEnd", "MapEnemyMoved", "ScriptEnd"}:
            with self.subTest(kind=kind):
                item, _ = memory(record(kind + ": synthetic message", "device.py", "ERROR"))
                self.assertIn(kind, five_answers(item)[4].text)
                self.assertIn("根因 unknown", five_answers(item)[4].text)

    def test_string_fold_not_reconstructed_identity_or_task(self):
        item, _ = memory(record('[STAT] {"ev":"task_start","task":"Example', "stat_log.py") + '    Task"}\n' + record("[UI] page_main"))
        self.assertIn("string_fold", self.codes(item))
        self.assertEqual(five_answers(item)[0].status, "unknown")
        self.assertIn("page_main", five_answers(item)[1].text)

    def test_stat_cannot_swallow_timestamp_or_boundary(self):
        text = record('[STAT] {"ev":', "stat_log.py") + record('Click (1, 2) @ I_EXAMPLE', "control.py")
        item, _ = memory(text)
        self.assertTrue(any(e.kind == "action" for e in item.events))

    def test_json_schema_bad_values_are_not_true(self):
        for bad in ('"true"', '1', '{}', '[]', 'null'):
            item, _ = memory(record('{ignored}', "unused.py") + record('[STAT] {"ev":"task_end","task":{},"ok":' + bad + '}', "stat_log.py"))
            events = [e for e in item.events if e.kind == "stat"]
            self.assertIsNone(events[0].fields["ok"])
            self.assertIsNone(events[0].fields["task"])
            self.assertEqual(five_answers(item)[4].status, "unknown")

    def test_duplicate_json_keys_and_nan_rejected(self):
        for payload in ('{"ev":"task_end","ev":"error"}', '{"ev":"error","dur":NaN}'):
            item, _ = memory(record('[STAT] ' + payload, "stat_log.py"))
            self.assertFalse(any(e.kind == "stat" for e in item.events))

    def test_invalid_timestamp_does_not_abort(self):
        item, _ = memory(record("[UI] fake").replace("2026-10-02", "2026-99-99") + record("[UI] page_main"))
        self.assertIn("bad_timestamp", self.codes(item))
        self.assertIn("page_main", five_answers(item)[1].text)

    def test_date_conflict_preserves_physical_order(self):
        item, window = memory(record("[UI] page_a", time="19:00:02.000") + record("[UI] page_b", time="19:00:01.000"))
        self.data(item, window)
        self.assertIn("time_conflict", self.codes(item))
        self.assertIn("page_b", five_answers(item)[1].text)

    def test_explicit_window_excludes_old_context(self):
        item, _ = memory(record("[UI] page_old", time="18:59:59.000") + record("Click (1, 2) @ I_EXAMPLE", "control.py", time="19:00:01.000"),
                         datetime(2026, 10, 2, 19), datetime(2026, 10, 2, 19, 0, 2))
        self.assertEqual(five_answers(item)[1].status, "unknown")
        self.assertIn("time_filter", self.codes(item))

    def test_default_window_always_bounded(self):
        item, window = memory(record("[UI] page_old", time="17:00:00.000") + record("Waiting for page_main", time="19:00:00.000"))
        self.assertEqual((window[1] - window[0]).total_seconds(), 1800)
        self.assertEqual(five_answers(item)[1].status, "unknown")

    def test_untimestamped_ui_or_fake_source_not_observation(self):
        item, _ = memory("[UI] page_fake\n" + record("[UI] page_fake", "arbitrary.py"))
        self.assertEqual(five_answers(item)[1].status, "unknown")

    def test_stale_page_after_unknown_page(self):
        item, window = memory(record("[UI] page_main") + record("Unknown ui page", level="WARNING", time="19:01:01.000"))
        self.data(item, window)
        self.assertIn("stale_page", self.codes(item))
        self.assertIn("故障时/当前页面 unknown", five_answers(item)[1].text)

    def test_boundary_mismatch_reported(self):
        item, window = memory(record("Scheduler: Start task `Alpha`", "script.py") + record("Scheduler: End task `Beta`", "script.py"))
        self.data(item, window)
        self.assertIn("boundary_conflict", self.codes(item))

    def test_raw_account_secret_locals_not_exported(self):
        text = record('[STAT] {"ev":"error","acc":"SECRET_ACC","char":"SECRET_CHAR","svr":"SECRET_SVR","etype":"ValueError","emsg":"SECRET_MESSAGE"}', "stat_log.py")
        text += record("SECRET_LOG_MESSAGE", "script.py", "ERROR") + 'Traceback (most recent call last):\n  secret="SECRET_LOCAL"\nValueError: SECRET_EXCEPTION\n'
        item, window = memory(text)
        result = self.data(item, window)
        exported = json.dumps(result) + markdown(result)
        for secret in ("SECRET_ACC", "SECRET_CHAR", "SECRET_SVR", "SECRET_MESSAGE", "SECRET_LOG_MESSAGE", "SECRET_LOCAL", "SECRET_EXCEPTION"):
            self.assertNotIn(secret, exported)

    def test_traceback_locals_cannot_become_page_action_failure(self):
        text = record("synthetic failure", "script.py", "ERROR") + '╭─ Traceback (most recent call last) ─╮\n│ [UI] page_fake                    │\n│ ValueError: a local string         │\n│ Click (1, 2) @ I_FAKE              │\n╰───────────────────────────────────╯\nConnectionError: synthetic terminal exception\n'
        item, _ = memory(text)
        self.assertEqual(five_answers(item)[1].status, "unknown")
        self.assertEqual(five_answers(item)[2].status, "unknown")
        self.assertEqual([e.fields["exception"] for e in item.events if e.kind == "exception"], ["ConnectionError"])

    def test_sections_and_traceable_refs(self):
        item, window = self.load("normal")
        result = self.data(item, window)
        output = markdown(result)
        for name in ("Analysis Scope", "Execution Context", "Five Questions", "Timeline", "Failure Trigger", "Evidence", "Missing / Stale / Conflicting Evidence", "Suggested Next Observation"):
            self.assertIn("## " + name, output)
        raw = (FIXTURE_ROOT / item.path).read_bytes()
        for e in item.events:
            self.assertLess(e.ref.start, e.ref.end)
            self.assertLessEqual(e.ref.end, len(raw))
            if e.ts:
                self.assertIn(str(e.ts).split(".")[0].encode(), raw[e.ref.start:e.ref.end])
        for a in five_answers(item):
            if a.status != "unknown":
                self.assertTrue(a.refs)

    def test_byte_budget_is_actual_total_and_offsets_valid(self):
        files = collect(["log/2026-10-02_normal.txt", "log/2026-10-02_plan.txt"], None, FIXTURE_ROOT, max_bytes=600)
        self.assertLessEqual(sum(i.read_bytes for i in files), 600)
        for item in files:
            parse_file(item)
            self.assertIn("byte_limit", self.codes(item))
            raw = (FIXTURE_ROOT / item.path).read_bytes()
            for e in item.events:
                self.assertIsNone(e.ref.first_line)
                self.assertIn(b"2026-10-02", raw[e.ref.start:e.ref.end])

    def test_tiny_budget_produces_unknown_without_overread(self):
        item = collect(["log/2026-10-02_normal.txt"], None, FIXTURE_ROOT, max_bytes=1)[0]
        parse_file(item)
        self.assertEqual(item.read_bytes, 1)
        self.assertTrue(all(a.status == "unknown" for a in five_answers(item)))

    def test_selected_files_only_no_history_config_image_reads(self):
        opened = []
        original = Path.open
        def spy(path, *args, **kwargs):
            opened.append(Path(path).resolve())
            self.assertTrue(Path(path).resolve().is_relative_to(FIXTURE_ROOT.resolve()))
            self.assertNotEqual(Path(path).suffix.lower(), ".png")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", spy):
            files = collect(["log/2026-10-02_plan.txt"], "log/error/1790928000000", FIXTURE_ROOT)
        self.assertEqual(len(opened), 2)
        self.assertEqual(len(files), 2)

    def test_path_rejects_config_worklog_handoff_other_project(self):
        for path in ("config/secret.json", "../logs/worklog/OAS/AI_WORKLOG.md", "../logs/handoff/OAS/handoff.md", "../OASX/log/2026-10-02_demo.txt", "script.py", "log/error/1790928000000/log.txt"):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                allowed(path, FIXTURE_ROOT)

    def test_max_files_and_duplicate_inputs_rejected_before_read(self):
        with patch.object(Path, "open", side_effect=AssertionError("No text reads allowed")):
            with self.assertRaises(ValueError):
                collect(["log/2026-10-02_normal.txt"], "log/error/1790928000000", FIXTURE_ROOT, max_files=1)
            with self.assertRaises(ValueError):
                collect(["log/2026-10-02_normal.txt"] * 2, None, FIXTURE_ROOT)
            with self.assertRaises(ValueError):
                collect([], None, FIXTURE_ROOT)

    def test_limits_and_window_errors(self):
        for values in ((0, 100, 30), (4, 0, 30), (17, 100, 30), (4, 17000000, 30), (4, 100, 1441), (4, 100, float("nan"))):
            with self.assertRaises(ValueError):
                validate_limits(*values)
        with self.assertRaises(ValueError):
            validate_limits(4, 100, 30, datetime(2026, 10, 2), None)
        with self.assertRaises(ValueError):
            validate_limits(4, 100, 30, datetime(2026, 10, 2), datetime(2026, 10, 3))
        with self.assertRaises(ValueError):
            validate_limits(4, 100, 30, datetime(2026, 10, 3), datetime(2026, 10, 2))
        with self.assertRaises(ValueError):
            parse_time("2026-10-02T09:00:00+08:00")

    def test_output_outside_tool_reports_rejected(self):
        for path in (OAS_ROOT / "log/2026-10-02_diagnostic.md", OAS_ROOT / "config/report.json", TOOL_ROOT / "README.md"):
            with self.assertRaises(ValueError):
                output_path(path)

    def test_cli_json_fixtures_and_no_implicit_scan(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            result = main(["--fixtures", "--log", "log/2026-10-02_normal.txt", "--format", "json"])
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())["sources"]), 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--fixtures"]), 2)

    def test_output_created_once_without_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="d1_output_") as directory:
            temporary_root = Path(directory)
            (temporary_root / "reports").mkdir()
            target = temporary_root / "reports/report.json"
            with patch("reader.TOOL_ROOT", temporary_root):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--fixtures", "--log", "log/2026-10-02_normal.txt", "--format", "json", "--output", str(target)]), 0)
                before = target.read_bytes()
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["--fixtures", "--log", "log/2026-10-02_plan.txt", "--format", "json", "--output", str(target)]), 2)
                self.assertEqual(target.read_bytes(), before)


class TemporarySyntheticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oas_d1_synthetic_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "log").mkdir()
        self.path = self.root / "log/2026-10-02_test.txt"

    def test_partial_final_line_not_a_fact(self):
        self.path.write_bytes((record("[UI] page_main") + record("Click (1, 2) @ I_FAKE", "control.py").rstrip("\n")).encode())
        item = collect([self.path], None, self.root)[0]
        parse_file(item)
        self.assertIn("partial_tail", {i.code for i in item.issues})
        self.assertEqual(five_answers(item)[2].status, "unknown")

    def test_bad_utf8_does_not_hide_valid_events(self):
        self.path.write_bytes(b"\xff\n" + record("[UI] page_main").encode())
        item = collect([self.path], None, self.root)[0]
        parse_file(item)
        self.assertIn("bad_utf8", {i.code for i in item.issues})
        self.assertIn("page_main", five_answers(item)[1].text)

    def test_empty_file_all_unknown(self):
        self.path.write_bytes(b"")
        item = collect([self.path], None, self.root)[0]
        parse_file(item)
        self.assertTrue(all(a.status == "unknown" for a in five_answers(item)))

    def test_overlong_line_is_not_interpreted(self):
        self.path.write_bytes(record("[UI] page_main").encode() + record("X" * 70000).encode())
        item = collect([self.path], None, self.root)[0]
        parse_file(item)
        self.assertIn("line_limit", {i.code for i in item.issues})
        self.assertIn("page_main", five_answers(item)[1].text)

    def test_many_lines_memory_retention_limit(self):
        self.path.write_bytes(record("[UI] page_old").encode() + b"synthetic unknown\n" * 20001 + record("Waiting for page_main").encode())
        item = collect([self.path], None, self.root)[0]
        self.assertLessEqual(len(item.lines), 20000)
        parse_file(item)
        self.assertIn("line_count_limit", {i.code for i in item.issues})
        self.assertEqual(five_answers(item)[1].status, "unknown")

    def test_png_metadata_only_and_missing_error_text(self):
        directory = self.root / "log/error/1790928000000"
        directory.mkdir(parents=True)
        (directory / "synthetic_name_only.png").write_bytes(b"NOT A REAL IMAGE")
        with patch.object(Path, "open", side_effect=AssertionError("Must not open any image")):
            item = collect([], directory, self.root)[0]
        self.assertEqual(item.image_refs, ["log/error/1790928000000/synthetic_name_only.png"])
        self.assertIn("missing_text", {i.code for i in item.issues})

    def test_hardlink_input_rejected(self):
        outside = self.root / "synthetic_secret.txt"
        outside.write_text("NOT REAL CONFIG", encoding="utf-8")
        os.link(outside, self.path)
        with self.assertRaises(ValueError):
            allowed(self.path, self.root)

    def test_symlink_escape_rejected(self):
        outside = self.root / "synthetic_secret.txt"
        outside.write_text("NOT REAL CONFIG", encoding="utf-8")
        try:
            self.path.symlink_to(outside)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable; reparse check tested separately")
        with self.assertRaises(ValueError):
            allowed(self.path, self.root)

    def test_reparse_attribute_rejected(self):
        self.path.write_text("SYNTHETIC", encoding="utf-8")
        actual = self.path.lstat()
        class Reparse:
            st_mode = actual.st_mode
            st_file_attributes = 0x400
        original = Path.lstat
        def fake(path, *args, **kwargs):
            return Reparse() if path == self.path else original(path, *args, **kwargs)
        with patch.object(Path, "lstat", fake), self.assertRaises(ValueError):
            allowed(self.path, self.root)


if __name__ == "__main__":
    unittest.main()
