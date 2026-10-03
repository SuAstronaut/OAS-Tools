#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OAS 多账号 last_complete_time 上号顺序修复工具（纯标准库 CLI）。

只做精确的字符串值替换：不会 json.dump，不会重排 key、缩进或其他字段。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_DIR = TOOL_DIR.parent.parent.parent / "OAS" / "config"
DEFAULT_BACKUP_DIR = TOOL_DIR / "backup"
ACCOUNT_KEY_RE = re.compile(r"^sup_account_list_([1-9]\d*)$")
TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


class ToolError(RuntimeError):
    """面向用户的安全停止提示。"""


class JsonTextError(ToolError):
    """JSON 文本不符合工具的精确替换前提。"""


class StructureError(ToolError):
    """不是可安全处理的多账号配置结构。"""


class SafetyError(ToolError):
    """触发保护规则，拒绝修改。"""


@dataclass
class JsonNode:
    kind: str
    start: int
    end: int
    value: Any = None
    entries: list[tuple[str, "JsonNode", "JsonNode"]] = field(default_factory=list)
    items: list["JsonNode"] = field(default_factory=list)


class JsonTextParser:
    """保留每个 JSON 值字符范围的严格 JSON 解析器。"""

    def __init__(self, text: str):
        self.text = text
        self.i = 0

    def parse(self) -> JsonNode:
        self._skip_ws()
        node = self._value()
        self._skip_ws()
        if self.i != len(self.text):
            raise JsonTextError("JSON 末尾含有无法识别的内容")
        return node

    def _skip_ws(self) -> None:
        while self.i < len(self.text) and self.text[self.i] in " \t\r\n":
            self.i += 1

    def _value(self) -> JsonNode:
        self._skip_ws()
        if self.i >= len(self.text):
            raise JsonTextError("JSON 意外结束")
        ch = self.text[self.i]
        if ch == "{":
            return self._object()
        if ch == "[":
            return self._array()
        if ch == '"':
            return self._string()
        return self._primitive()

    def _string(self) -> JsonNode:
        start = self.i
        self.i += 1
        escaped = False
        while self.i < len(self.text):
            ch = self.text[self.i]
            self.i += 1
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                raw = self.text[start:self.i]
                try:
                    return JsonNode("string", start, self.i, json.loads(raw))
                except json.JSONDecodeError as exc:
                    raise JsonTextError(f"JSON 字符串无效: {exc}") from exc
        raise JsonTextError("JSON 字符串没有结束引号")

    def _primitive(self) -> JsonNode:
        start = self.i
        while self.i < len(self.text) and self.text[self.i] not in " \t\r\n,]}":
            self.i += 1
        raw = self.text[start:self.i]
        if not raw:
            raise JsonTextError("JSON 值无效")
        try:
            return JsonNode("primitive", start, self.i, json.loads(raw))
        except json.JSONDecodeError as exc:
            raise JsonTextError(f"JSON 基础值无效: {exc}") from exc

    def _object(self) -> JsonNode:
        start = self.i
        self.i += 1
        node = JsonNode("object", start, start)
        self._skip_ws()
        if self._peek("}"):
            self.i += 1
            node.end = self.i
            return node
        while True:
            self._skip_ws()
            if self.i >= len(self.text) or self.text[self.i] != '"':
                raise JsonTextError("JSON 对象 key 必须是字符串")
            key_node = self._string()
            self._skip_ws()
            if not self._peek(":"):
                raise JsonTextError("JSON 对象 key 后缺少冒号")
            self.i += 1
            value_node = self._value()
            node.entries.append((key_node.value, key_node, value_node))
            self._skip_ws()
            if self._peek("}"):
                self.i += 1
                node.end = self.i
                return node
            if not self._peek(","):
                raise JsonTextError("JSON 对象成员之间缺少逗号")
            self.i += 1

    def _array(self) -> JsonNode:
        start = self.i
        self.i += 1
        node = JsonNode("array", start, start)
        self._skip_ws()
        if self._peek("]"):
            self.i += 1
            node.end = self.i
            return node
        while True:
            node.items.append(self._value())
            self._skip_ws()
            if self._peek("]"):
                self.i += 1
                node.end = self.i
                return node
            if not self._peek(","):
                raise JsonTextError("JSON 数组成员之间缺少逗号")
            self.i += 1

    def _peek(self, value: str) -> bool:
        return self.text.startswith(value, self.i)


@dataclass
class AccountSlot:
    index: int
    node: JsonNode
    name: str
    time_node: JsonNode
    time_text: str


@dataclass
class Inspection:
    path: Path
    original_bytes: bytes
    bom: bytes
    text: str
    root: JsonNode
    slots: list[AccountSlot]
    time_format: str
    gaps: list[int]


@dataclass
class FixPlan:
    direction: str
    ordered_indices: list[int]
    values: dict[int, str]
    expected_text: str
    changed_count: int


def read_utf8(path: Path) -> tuple[bytes, bytes, str]:
    raw = path.read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    try:
        return raw, bom, raw[len(bom):].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JsonTextError(f"文件不是 UTF-8 JSON，停止修改: {path.name}") from exc


def direct_entry(node: JsonNode, key: str) -> JsonNode | None:
    if node.kind != "object":
        return None
    matches = [value for name, _key_node, value in node.entries if name == key]
    if len(matches) > 1:
        raise StructureError(f"对象中存在重复 key：{key}")
    return matches[0] if matches else None


def walk_objects(node: JsonNode) -> Iterable[JsonNode]:
    if node.kind == "object":
        yield node
        for _name, _key_node, value in node.entries:
            yield from walk_objects(value)
    elif node.kind == "array":
        for value in node.items:
            yield from walk_objects(value)


def account_group(node: JsonNode) -> list[tuple[int, JsonNode]]:
    found: list[list[tuple[int, JsonNode]]] = []
    preferred = direct_entry(node, "multi_daily_alt_acc")
    search_nodes = [preferred] if preferred is not None and preferred.kind == "object" else list(walk_objects(node))
    for obj in search_nodes:
        if obj.kind != "object":
            continue
        group: list[tuple[int, JsonNode]] = []
        for key, _key_node, value in obj.entries:
            match = ACCOUNT_KEY_RE.fullmatch(key)
            if match:
                group.append((int(match.group(1)), value))
        if group:
            found.append(group)
    if not found:
        raise StructureError("未找到 sup_account_list_N 账号项")
    if len(found) != 1:
        raise StructureError("发现多个 sup_account_list_N 账号组，无法安全判断目标")
    slots = sorted(found[0], key=lambda item: item[0])
    indices = [index for index, _node in slots]
    if len(set(indices)) != len(indices):
        raise StructureError("发现重复的 sup_account_list_N 编号")
    return slots


def identify_time_format(values: list[str]) -> str:
    for fmt in TIME_FORMATS:
        try:
            for value in values:
                datetime.strptime(value, fmt)
            return fmt
        except ValueError:
            continue
    raise StructureError("last_complete_time 格式无法可靠识别，停止修改")


def inspect_config(path: Path) -> Inspection:
    raw, bom, text = read_utf8(path)
    root = JsonTextParser(text).parse()
    if root.kind != "object":
        raise StructureError("JSON 根节点必须是对象")
    slots: list[AccountSlot] = []
    for index, node in account_group(root):
        if node.kind != "object":
            raise StructureError(f"sup_account_list_{index} 不是对象")
        time_node = direct_entry(node, "last_complete_time")
        if time_node is None or time_node.kind != "string":
            raise StructureError(f"sup_account_list_{index} 缺少字符串 last_complete_time")
        name_node = direct_entry(node, "character")
        name = name_node.value if name_node is not None and name_node.kind == "string" and name_node.value else "（未命名）"
        slots.append(AccountSlot(index, node, str(name), time_node, str(time_node.value)))
    time_format = identify_time_format([slot.time_text for slot in slots])
    present = {slot.index for slot in slots}
    gaps = [index for index in range(1, max(present) + 1) if index not in present]
    return Inspection(path, raw, bom, text, root, slots, time_format, gaps)


def discover_configs(config_dir: Path) -> list[Inspection]:
    if not config_dir.is_dir():
        raise ToolError(f"配置目录不存在: {config_dir}")
    candidates: list[Inspection] = []
    for path in sorted(config_dir.glob("*.json"), key=lambda item: item.name.casefold()):
        if path.name.casefold().startswith("template"):
            continue
        try:
            candidates.append(inspect_config(path))
        except ToolError:
            continue
    return candidates


def chronological_order(slots: list[AccountSlot], time_format: str) -> list[AccountSlot]:
    return sorted(slots, key=lambda slot: (datetime.strptime(slot.time_text, time_format), -slot.index), reverse=True)


def label(slot: AccountSlot) -> str:
    return f"#{slot.index} {slot.name}"


def replace_text(text: str, replacements: list[tuple[int, int, str]]) -> str:
    out = text
    previous_start = len(text) + 1
    for start, end, value in sorted(replacements, reverse=True):
        if start >= end or end > len(text) or end > previous_start:
            raise SafetyError("目标字段字符范围异常，停止修改")
        out = out[:start] + value + out[end:]
        previous_start = start
    return out


def build_plan(inspection: Inspection, direction: str, now: datetime | None = None) -> FixPlan:
    if inspection.gaps:
        missing = ", ".join(map(str, inspection.gaps))
        raise SafetyError(f"账号编号存在缺口（缺少: {missing}），为保护数据拒绝直接修改")
    if direction not in {"forward", "reverse"}:
        raise ToolError("方向必须是 forward 或 reverse")
    ordered = list(inspection.slots if direction == "forward" else reversed(inspection.slots))
    # 使用昨天作为最新时间，避免当天任务被误判为已完成。
    base = (now or datetime.now()).replace(microsecond=0) - timedelta(days=1)
    values = {
        slot.index: (base - timedelta(minutes=position)).strftime(inspection.time_format)
        for position, slot in enumerate(ordered)
    }
    replacements = [
        (slot.time_node.start, slot.time_node.end, json.dumps(values[slot.index], ensure_ascii=False))
        for slot in inspection.slots
    ]
    expected_text = replace_text(inspection.text, replacements)
    changed_count = sum(slot.time_text != values[slot.index] for slot in inspection.slots)
    return FixPlan(direction, [slot.index for slot in ordered], values, expected_text, changed_count)


def create_backup(source: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{source.stem}_{stamp}"
    destination = backup_dir / f"{base}.json"
    sequence = 1
    while destination.exists():
        destination = backup_dir / f"{base}_{sequence}.json"
        sequence += 1
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise ToolError(f"备份失败，已停止修改: {exc}") from exc
    if destination.read_bytes() != source.read_bytes():
        raise ToolError("备份校验失败，已停止修改")
    return destination


def atomic_write(path: Path, content: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        raise ToolError(f"写入失败: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()


def verify_fix(path: Path, before: Inspection, plan: FixPlan) -> Inspection:
    after_bytes, _bom, _text = read_utf8(path)
    expected_bytes = before.bom + plan.expected_text.encode("utf-8")
    if after_bytes != expected_bytes:
        raise ToolError("验证失败：文件内容不等于预期的最小 last_complete_time 替换结果")
    after = inspect_config(path)
    if [slot.index for slot in after.slots] != [slot.index for slot in before.slots]:
        raise ToolError("验证失败：账号编号或账号数量发生变化")
    if [slot.name for slot in after.slots] != [slot.name for slot in before.slots]:
        raise ToolError("验证失败：账号名称发生变化")
    actual_values = {slot.index: slot.time_text for slot in after.slots}
    if actual_values != plan.values:
        raise ToolError("验证失败：last_complete_time 未按预期写入")
    if len(set(actual_values.values())) != len(actual_values):
        raise ToolError("验证失败：生成的 last_complete_time 出现重复")
    actual_order = [slot.index for slot in chronological_order(after.slots, after.time_format)]
    if actual_order != plan.ordered_indices:
        raise ToolError("验证失败：按 last_complete_time 推导的上号顺序不符合选择方向")
    return after


def fix_file(path: Path, direction: str, backup_dir: Path = DEFAULT_BACKUP_DIR,
             now: datetime | None = None) -> tuple[Inspection, FixPlan, Path]:
    before = inspect_config(path)
    plan = build_plan(before, direction, now)
    if path.read_bytes() != before.original_bytes:
        raise SafetyError("预览后目标文件已变化，已停止修改；请重新启动工具")
    backup = create_backup(path, backup_dir)
    atomic_write(path, before.bom + plan.expected_text.encode("utf-8"))
    after = verify_fix(path, before, plan)
    return after, plan, backup


def print_current(inspection: Inspection) -> None:
    print(f"\n文件：{inspection.path.name}")
    print(f"账号数：{len(inspection.slots)}")
    print("当前账号与 last_complete_time：")
    for slot in inspection.slots:
        print(f"  {label(slot)} | {slot.time_text}")
    order = " → ".join(label(slot) for slot in chronological_order(inspection.slots, inspection.time_format))
    print("当前按 OAS 规则推导的上号顺序（时间越晚越早）：")
    print(f"  {order}")


def choose_candidate(candidates: list[Inspection]) -> Inspection:
    print("可处理配置：")
    for number, inspection in enumerate(candidates, start=1):
        suffix = ""
        if inspection.gaps:
            suffix = "  [编号缺口：" + ", ".join(map(str, inspection.gaps)) + "；默认拒绝修改]"
        print(f"{number}. {inspection.path.name}（{len(inspection.slots)} 个账号）{suffix}")
    while True:
        value = input("请选择编号（输入 q 退出）：").strip()
        if value.lower() == "q":
            raise ToolError("用户取消")
        try:
            choice = int(value)
            return candidates[choice - 1]
        except (ValueError, IndexError):
            print("请输入列表中的有效编号。")


def choose_direction() -> str:
    print("\n请选择目标下一轮上号顺序：")
    print("1. 正序上号：#1 → #2 → ... → #N（#1 写最新时间）")
    print("2. 倒序上号：#N → ... → #2 → #1（#N 写最新时间）")
    while True:
        value = input("请选择 1 或 2：").strip()
        if value == "1":
            return "forward"
        if value == "2":
            return "reverse"
        print("请输入 1 或 2。")


def run_interactive(config_dir: Path) -> int:
    candidates = discover_configs(config_dir)
    if not candidates:
        print(f"未在 {config_dir} 找到同时包含 sup_account_list_N 与有效 last_complete_time 的配置。")
        return 1
    selected = choose_candidate(candidates)
    inspection = inspect_config(selected.path)  # 用户选择后重新读取，避免使用扫描时的旧快照。
    print_current(inspection)
    if inspection.gaps:
        print("\n检测到账号编号缺口。为避免错误对应账号，本工具默认拒绝直接修改。")
        return 1
    direction = choose_direction()
    plan = build_plan(inspection, direction)
    target_slots = [next(slot for slot in inspection.slots if slot.index == index) for index in plan.ordered_indices]
    direction_name = "正序" if direction == "forward" else "倒序"
    print(f"\n目标方向：{direction_name}")
    print("预计上号顺序：")
    print("  " + " → ".join(label(slot) for slot in target_slots))
    print(f"预计修改字段：{plan.changed_count} / {len(inspection.slots)} 个 last_complete_time")
    if input("确认执行请输入 YES（其他任何输入都会取消）：").strip() != "YES":
        print("已取消，未创建备份，未修改文件。")
        return 0
    try:
        after, applied_plan, backup = fix_file(selected.path, direction)
    except ToolError as exc:
        print(f"修复失败：{exc}")
        return 1
    final_slots = [next(slot for slot in after.slots if slot.index == index) for index in applied_plan.ordered_indices]
    print("\n修复成功")
    print(f"文件：{after.path.name}")
    print(f"账号数：{len(after.slots)}")
    print(f"目标方向：{direction_name}")
    print("预计上号：")
    print("  " + " → ".join(slot.name for slot in final_slots))
    print(f"修改字段：{applied_plan.changed_count}")
    print("其他字段变化：0（已按精确文本替换结果校验）")
    print(f"备份：{backup}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 OAS MultiDailyAltAcc 的 last_complete_time 上号顺序")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR,
                        help="OAS config 目录；默认根据本工具所在 Tool 目录推导")
    args = parser.parse_args()
    try:
        return run_interactive(args.config_dir)
    except ToolError as exc:
        print(f"已停止：{exc}")
        return 1
    except KeyboardInterrupt:
        print("\n已取消，未修改文件。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
