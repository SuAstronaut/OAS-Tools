"""Independent synthetic tests; all config writes and backups stay in tempfile."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core

HEADER = ["系统", "位置", "邮箱", "名称", "区服", "羁绊情况"]


def row(index, position="Demo", system="安卓", flower="1"):
    return [system, position, f"test{index}@example.invalid", f"SYNTHETIC_ROLE_{index}", "SYNTHETIC_SERVER", flower]


def config(count):
    account_data = {"multi_daily_alt_acc_config": {"sup_account_count": count}}
    for index in range(1, count + 1):
        account_data[f"sup_account_list_{index}"] = {
            "account": f"test{index}@example.invalid", "character": f"SYNTHETIC_ROLE_{index}",
            "svr": "SYNTHETIC_SERVER", "apple_or_android": True, "isflower": 1,
            "last_complete_time": "2025-01-01 00:00:00", "unrelated_state": "preserve",
        }
    return {"multi_daily_alt_acc": account_data, "unrelated_root": "preserve"}


class MirrorTests(unittest.TestCase):
    def parse(self, rows):
        positions, errors, warnings = core.parse_excel([HEADER] + rows)
        return positions, errors, warnings

    def test_interleaved_positions_preserve_order(self):
        positions, errors, _ = self.parse([row(1, "A"), row(2, "B"), row(3, "A")])
        self.assertEqual(errors, [])
        self.assertEqual([item["name"] for item in positions["A"]], ["SYNTHETIC_ROLE_1", "SYNTHETIC_ROLE_3"])
        self.assertEqual([item["index"] for item in positions["A"]], [1, 2])

    def test_blank_system_inherits(self):
        positions, errors, _ = self.parse([row(1), row(2, system="")])
        self.assertEqual(errors, [])
        self.assertTrue(positions["Demo"][1]["system"])

    def test_invalid_flower_blocks(self):
        _, errors, _ = self.parse([row(1, flower="4")])
        self.assertTrue(errors)

    def test_preview_is_nonmutating_and_detects_append(self):
        positions, errors, _ = self.parse([row(i) for i in range(1, 32)])
        self.assertEqual(errors, [])
        data = {"Demo": config(30)}
        before = copy.deepcopy(data)
        plan, stats, _ = core.build_plan(positions, data)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(len(plan), 31)
        self.assertEqual(data, before)
        self.assertEqual(core.statistics_check(plan), [])

    def test_shrink_has_explicit_blocker(self):
        positions, _, _ = self.parse([row(1)])
        _, stats, blockers = core.build_plan(positions, {"Demo": config(2)})
        self.assertEqual(stats["shrink"], 1)
        self.assertTrue(blockers)

    def test_template_has_no_account_rows(self):
        path = next(Path(core.__file__).parent.glob("*.xlsx"))
        rows, _ = core.read_xlsx(str(path))
        self.assertEqual(rows, [HEADER])

    def test_xlsx_round_trip_uses_tempfile(self):
        with tempfile.TemporaryDirectory(prefix="oas-tools-xlsx-") as directory:
            path = Path(directory) / "synthetic.xlsx"
            core.write_xlsx(str(path), HEADER, [row(1)])
            rows, _ = core.read_xlsx(str(path))
            self.assertEqual(rows[1], row(1))

    def test_import_and_backup_are_isolated(self):
        with tempfile.TemporaryDirectory(prefix="oas-tools-excel-") as directory:
            root = Path(directory)
            cfg = root / "oas" / "config"
            cfg.mkdir(parents=True)
            target = cfg / "synthetic.json"
            target.write_text(json.dumps(config(1)), encoding="utf-8")
            before = target.read_bytes()
            positions, errors, _ = self.parse([row(1), row(2)])
            mapping = {"Demo": "synthetic.json"}
            data = core.load_oas_json(str(root / "oas"), mapping)
            plan, _, _ = core.build_plan(positions, data)
            with patch.object(core, "__file__", str(root / "isolated_tool" / "core.py")):
                backup, _, verify_errors = core.apply_plan(data, plan, str(root / "oas"), mapping, errors=errors)
            backup = Path(backup)
            self.assertTrue(backup.is_relative_to(root))
            self.assertEqual((backup / "synthetic.json").read_bytes(), before)
            self.assertEqual(verify_errors, [])
            result = core.load_json(str(target))
            self.assertEqual(result["multi_daily_alt_acc"]["multi_daily_alt_acc_config"]["sup_account_count"], 2)
            self.assertEqual(result["multi_daily_alt_acc"]["sup_account_list_1"]["unrelated_state"], "preserve")
            self.assertEqual(result["unrelated_root"], "preserve")

    def test_failed_atomic_write_keeps_target(self):
        with tempfile.TemporaryDirectory(prefix="oas-tools-failure-") as directory:
            root = Path(directory)
            cfg = root / "oas" / "config"
            cfg.mkdir(parents=True)
            target = cfg / "synthetic.json"
            target.write_text(json.dumps(config(1)), encoding="utf-8")
            before = target.read_bytes()
            positions, errors, _ = self.parse([row(1), row(2)])
            mapping = {"Demo": "synthetic.json"}
            data = core.load_oas_json(str(root / "oas"), mapping)
            plan, _, _ = core.build_plan(positions, data)
            with patch.object(core, "__file__", str(root / "isolated_tool" / "core.py")), patch.object(core, "save_json_atomic", side_effect=OSError("synthetic failure")):
                with self.assertRaises(OSError):
                    core.apply_plan(data, plan, str(root / "oas"), mapping, errors=errors)
            self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
