#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OAS_account_order_fixer 隔离自测：只读取真实 OAS JSON，不写入它们。"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import main


TOOL_DIR = Path(__file__).resolve().parent
FIXED_NOW = datetime(2026, 8, 26, 9, 42, 0)


def fixture(path: Path, indices: list[int], *, missing_time: int | None = None,
            duplicate_times: bool = False) -> None:
    accounts = []
    for index in indices:
        fields = [
            f'"character": "测试账号{index}"',
            f'"account": "test{index}@example.invalid"',
            '"enable": true',
            '"unrelated_time": "1999-01-01 00:00:00"',
        ]
        if index != missing_time:
            second = 0 if duplicate_times else index
            fields.append(f'"last_complete_time": "2025-01-01 00:0{second}:00"')
        accounts.append(f'    "sup_account_list_{index}": {{' + ", ".join(fields) + "}")
    text = "{\n  \"unchanged_root\": \"keep\",\n  \"multi_daily_alt_acc\": {\n" + ",\n".join(accounts)
    text += "\n  }\n}\n"
    path.write_bytes(text.encode("utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_real_structure_read_only() -> None:
    candidates = main.discover_configs(main.DEFAULT_CONFIG_DIR)
    assert_true(bool(candidates), "未从真实 OAS config 读到可处理的结构")
    assert_true(all(item.slots for item in candidates), "真实候选未识别到账号项")


def test_forward_three(tmp: Path) -> None:
    path = tmp / "three.json"
    fixture(path, [1, 2, 3])
    before = main.inspect_config(path)
    after, plan, backup = main.fix_file(path, "forward", tmp / "backup", FIXED_NOW)
    assert_true(backup.exists(), "未生成备份")
    assert_true(plan.ordered_indices == [1, 2, 3], "3 账号正序错误")
    assert_true([slot.index for slot in main.chronological_order(after.slots, after.time_format)] == [1, 2, 3], "正序验证失败")
    assert_true(plan.values == {
        1: "2026-08-25 09:42:00",
        2: "2026-08-25 09:41:00",
        3: "2026-08-25 09:40:00",
    }, "正序未以昨天作为时间基准")
    assert_true(after.path.read_bytes() == before.bom + plan.expected_text.encode("utf-8"), "出现非目标文本变化")


def test_reverse_seven(tmp: Path) -> None:
    path = tmp / "seven.json"
    fixture(path, list(range(1, 8)))
    after, plan, _backup = main.fix_file(path, "reverse", tmp / "backup", FIXED_NOW)
    assert_true(plan.ordered_indices == [7, 6, 5, 4, 3, 2, 1], "7 账号倒序错误")
    assert_true([slot.index for slot in main.chronological_order(after.slots, after.time_format)] == plan.ordered_indices,
                "倒序验证失败")
    assert_true(plan.values[7] == "2026-08-25 09:42:00" and plan.values[1] == "2026-08-25 09:36:00",
                "倒序未将昨天的最新时间分配给 #7")
    assert_true(all(datetime.strptime(value, "%Y-%m-%d %H:%M:%S") < FIXED_NOW for value in plan.values.values()),
                "生成了今天或未来时间")


def test_cross_month_and_year(tmp: Path) -> None:
    path = tmp / "calendar.json"
    fixture(path, [1, 2, 3])
    inspection = main.inspect_config(path)
    march_plan = main.build_plan(inspection, "forward", datetime(2026, 3, 1, 0, 0, 30))
    year_plan = main.build_plan(inspection, "reverse", datetime(2026, 1, 1, 0, 0, 30))
    assert_true(march_plan.values[1] == "2026-02-28 00:00:30", "跨月未正确落到 2 月最后一天")
    assert_true(year_plan.values[3] == "2025-12-31 00:00:30", "跨年未正确落到上一年")


def test_gap_rejected(tmp: Path) -> None:
    path = tmp / "gap.json"
    fixture(path, [1, 2, 3, 5])
    inspection = main.inspect_config(path)
    assert_true(inspection.gaps == [4], "未识别编号缺口")
    try:
        main.fix_file(path, "forward", tmp / "backup", FIXED_NOW)
    except main.SafetyError:
        return
    raise AssertionError("编号缺口未被拒绝")


def test_missing_time_rejected(tmp: Path) -> None:
    path = tmp / "missing.json"
    fixture(path, [1, 2, 3], missing_time=2)
    try:
        main.inspect_config(path)
    except main.StructureError:
        return
    raise AssertionError("缺少 last_complete_time 未被拒绝")


def test_duplicate_old_time_fixed(tmp: Path) -> None:
    path = tmp / "duplicate.json"
    fixture(path, [1, 2, 3], duplicate_times=True)
    before = main.inspect_config(path)
    assert_true(len({slot.time_text for slot in before.slots}) == 1, "fixture 未构造旧时间重复")
    after, _plan, _backup = main.fix_file(path, "forward", tmp / "backup", FIXED_NOW)
    assert_true(len({slot.time_text for slot in after.slots}) == 3, "未修复为严格不重复时间")


def main_test() -> int:
    temp = Path(tempfile.mkdtemp(prefix="._account_order_fixer_test_", dir=TOOL_DIR))
    tests = [
        ("真实配置只读结构检查", test_real_structure_read_only, False),
        ("3 账号正序", test_forward_three, True),
        ("7 账号倒序", test_reverse_seven, True),
        ("跨月与跨年日期", test_cross_month_and_year, True),
        ("编号缺口拒绝", test_gap_rejected, True),
        ("缺 last_complete_time 拒绝", test_missing_time_rejected, True),
        ("重复旧时间修复", test_duplicate_old_time_fixed, True),
    ]
    passed = 0
    try:
        for name, test, needs_temp in tests:
            try:
                if needs_temp:
                    test(temp)
                else:
                    test()
                print(f"PASS: {name}")
                passed += 1
            except Exception as exc:
                print(f"FAIL: {name}: {exc}")
                return 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    print(f"全部通过：{passed}/{len(tests)}；临时测试文件已清理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
