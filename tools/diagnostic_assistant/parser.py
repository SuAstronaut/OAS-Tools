"""Small source-aware parser. Unrecognized text is evidence, never a guessed fact."""
import json
import re
from datetime import datetime, timedelta

from models import Event, Issue, Reference

HEADER = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s*\|"
    r"\s*(?P<source>[^|\s]{1,128}):(?P<line>\d{1,9})\s*\|\s*(?P<level>[A-Z]{1,16})\s*\| ?(?P<body>.*)$"
)
DATE_START = re.compile(r"^\d{4}-\d{2}-\d{2} ")
TITLE = re.compile(r"^─{10,}\s*(.*?)\s*─{10,}\s*$")
EQ = re.compile(r"^═{15,}\s*$")
ID = r"[A-Za-z0-9_.-]{1,128}"
KNOWN_EXCEPTIONS = {
    "CampaignEnd", "MapDetectionError", "MapWalkError", "MapEnemyMoved", "CampaignNameError",
    "ScriptError", "ScriptEnd", "GameStuckError", "GameBugError", "GameTooManyClickError",
    "EmulatorNotRunningError", "GameNotRunningError", "GamePageUnknownError",
    "RequestHumanTakeover", "TaskEnd",
}
EXCEPTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)|RequestHumanTakeover|TaskEnd|ScriptEnd|CampaignEnd|MapEnemyMoved)(?::|$)")
WAIT_SOURCES = {"script.py", "base_task.py", "device.py", "game_ui.py"}


def span(first, last):
    return Reference(first.path, first.start, last.end, first.first_line, last.last_line)


def identifier(value):
    return value if isinstance(value, str) and re.fullmatch(ID, value) else None


def exception_fields(name, message):
    fields = {"exception": name, "known_oas_type": name in KNOWN_EXCEPTIONS}
    # Only known condition phrases, not arbitrary exception messages/locals.
    if name == "GameStuckError" and message.strip() == "Wait too long":
        fields["trigger"] = "stuck_wait_too_long"
    elif name == "GameTooManyClickError" and message.startswith("Too many click for a button:"):
        fields["trigger"] = "repeated_button_click_guard"
    elif name == "GameNotRunningError" and message.strip() in {"Game not running", "Game died"}:
        fields["trigger"] = "game_not_running_check"
    return fields


def inside_string(value):
    quoted, escaped = False, False
    for character in value:
        if escaped:
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
    return quoted


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def stat_payload(text):
    try:
        payload = json.loads(text, object_pairs_hook=object_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
        if not isinstance(payload, dict) or not identifier(payload.get("ev")):
            return None
        result = {"ev": payload["ev"]}
        for key in ("task", "etype"):
            if key in payload:
                result[key] = identifier(payload[key])
        if result.get("etype") and isinstance(payload.get("emsg"), str):
            condition = exception_fields(result["etype"], payload["emsg"]).get("trigger")
            if condition:
                result["trigger"] = condition
        if "ok" in payload:
            result["ok"] = payload["ok"] if type(payload["ok"]) is bool else None
        if type(payload.get("dur")) in (int, float) and 0 <= payload["dur"] < 10**9:
            result["dur"] = payload["dur"]
        # Identity presence only. Never export account/character/server values or emsg/locals.
        result["identity_present"] = all(isinstance(payload.get(k), str) and bool(payload[k]) for k in ("acc", "char", "svr"))
        return result
    except (ValueError, RecursionError, OverflowError):
        return None


def classify(body, source, level):
    """Returns only whitelisted fields; doesn't reproduce raw log content."""
    body = body.strip()
    if source == "script.py":
        match = re.fullmatch(rf"Scheduler: (Start|End) task `({ID})`", body)
        if match:
            return "task_start" if match[1] == "Start" else "task_end", {"task": match[2], "layer": "scheduler"}
        match = re.fullmatch(rf"TaskEnd final task name: ({ID})", body)
        if match:
            return "control_end", {"task": match[1], "exception": "TaskEnd"}
        match = re.search(rf"^module_path: .*[/\\]tasks[/\\]({ID})[/\\]script_task\.py, module_name: script_task$", body)
        if match:
            return "module", {"task": match[1]}
        if body.startswith("Log file rolled over:"):
            return "rollover", {}
        if re.fullmatch(r"Game page unknown \(\d+/3\)", body) and level == "CRITICAL":
            return "failure_condition", {"trigger": "page_unrecognized_record"}
        if body == "Request human takeover" and level == "CRITICAL":
            return "failure_condition", {"trigger": "human_takeover_requested", "reason": "unknown"}
    if source == "logger.py" and body.startswith("Log file rolled over:"):
        return "rollover", {}
    if source in {"game_ui.py", "logger.py"}:
        match = re.fullmatch(rf"\[UI\] ({ID})", body)
        if match:
            return "page", {"page": match[1], "observation": "recognized"}
    if source == "game_ui.py":
        for pattern in (rf"Current page: ({ID})\. Following shortest path:",
                        rf"(?:\[\d+(?:\.\d+)?s\])?Page arrived ({ID})"):
            match = re.fullmatch(pattern, body)
            if match:
                return "page", {"page": match[1], "observation": "arrived" if "Page arrived" in body else "recognized"}
        match = re.fullmatch(rf"Page switch: ({ID}) -> ({ID})", body)
        if match:
            return "page_plan", {"from": match[1], "to": match[2]}
        if body.startswith("Following shortest path:"):
            return "navigation_plan", {}
        if body == "Unknown ui page":
            return "page_unknown", {}
    if source == "control.py":
        match = re.fullmatch(rf"Click (\(\s*-?\d+\s*,\s*-?\d+\s*\)) @ ({ID})(?: (\d+(?:\.\d+)?))?", body)
        if match:
            return "action", {"kind": "long_click" if match[3] else "click", "resource": match[2], "xy": match[1], "execution": "unknown", "response": "unknown"}
        match = re.fullmatch(r"(?:minitouch )?(Swipe|Drag) (\(\s*-?\d+\s*,\s*-?\d+\s*\)) -> (\(\s*-?\d+\s*,\s*-?\d+\s*\))(?:, \d+(?:\.\d+)?)?", body, re.I)
        if match:
            return "action", {"kind": match[1].lower(), "from": match[2], "to": match[3], "execution": "unknown", "response": "unknown"}
    if source in WAIT_SOURCES:
        match = re.fullmatch(rf"Wait until (\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}(?:\.\d+)?) for task `({ID})`", body)
        if match:
            return "wait", {"reason": "scheduler_due", "target": match[2], "due": match[1]}
        match = re.fullmatch(rf"Waiting for ({ID})", body)
        if match:
            return "wait", {"reason": "page_or_target", "target": match[1]}
        match = re.fullmatch(rf"Wait appear and operate ({ID}) on ({ID})", body)
        if match:
            return "wait", {"reason": "target_appear_then_operate", "target": match[1]}
        match = re.fullmatch(rf"Wait until ({ID}) position stable", body)
        if match:
            return "wait", {"reason": "position_stable", "target": match[1]}
        # Sets / arbitrary resource repr are not reconstructed as ordered waits.
        if body.startswith("Waiting for {"):
            return "wait", {"reason": "detect_record_set", "target": "unknown"}
        if body.startswith("Wait too long"):
            return "timeout", {"trigger": "stuck_wait_too_long"}
        match = re.fullmatch(rf"Cannot goto page\[({ID})\], timeout\[(\d+(?:\.\d+)?)s\] reached", body)
        if match:
            return "timeout", {"trigger": "navigation_timeout", "target": match[1], "budget_s": match[2]}
        match = re.fullmatch(rf"Wait until appear ({ID}) timeout", body)
        if match:
            return "timeout", {"trigger": "target_appear_timeout", "target": match[1]}
        if "timeout" in body.lower() and re.match(r"^(Wait[_ ]|Wait until|ui_click|Cannot goto page\[)", body):
            return "timeout", {"trigger": "wait_or_navigation_timeout"}
    match = EXCEPTION.match(body)
    if match and (level in {"ERROR", "CRITICAL", "WARNING"}):
        return "control_end" if match[1] == "TaskEnd" else "exception", exception_fields(match[1], body.partition(":")[2].strip())
    if level in {"ERROR", "CRITICAL"}:
        return "error_signal", {"trigger": "error_level_message", "condition": "unknown"}
    return "unknown", {}


def parse_file(item, start=None, end=None, max_window_minutes=30):
    lines = item.lines
    events = []
    index = 0
    previous_ts = None
    while index < len(lines):
        line = lines[index]
        title = TITLE.fullmatch(line.text.strip())
        if EQ.fullmatch(line.text.strip()) and index + 2 < len(lines):
            middle = TITLE.fullmatch(lines[index + 1].text.strip())
            if middle and EQ.fullmatch(lines[index + 2].text.strip()):
                events.append(Event("start_block" if middle[1].upper() == "START" else "title_block", None,
                                    span(line.ref, lines[index + 2].ref), {"title": identifier(middle[1]) or "unknown"}))
                index += 3
                continue
        header = HEADER.match(line.text)
        if not header:
            events.append(Event("unknown", None, line.ref))
            index += 1
            continue
        try:
            ts = datetime.strptime(header["ts"], "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            item.issues.append(Issue("bad_timestamp", "时间戳无效；该记录未解释", line.ref))
            index += 1
            continue
        if previous_ts is not None and ts < previous_ts:
            item.issues.append(Issue("time_conflict", "文件内时间倒退；保留物理顺序，不推断因果顺序", line.ref))
        previous_ts = ts
        source, level = header["source"], header["level"]
        body = header["body"].rstrip()
        last = index
        status = "confirmed"
        if body.startswith("[STAT]"):
            candidate = body[len("[STAT]"):].strip()
            payload = stat_payload(candidate)
            string_fold = False
            while payload is None and last + 1 < min(len(lines), index + 9):
                following = lines[last + 1]
                if not following.text.strip() or DATE_START.match(following.text) or EQ.match(following.text.strip()) or TITLE.match(following.text.strip()):
                    break
                if inside_string(candidate):
                    string_fold = True
                    break
                candidate += following.text.strip()
                last += 1
                payload = stat_payload(candidate)
            if payload is None:
                kind, fields = "invalid_stat", {}
                item.issues.append(Issue("string_fold" if string_fold else "bad_stat", "STAT 无法可靠恢复（坏 JSON/半条/字段非法/字符串折行）；不补造事件", span(line.ref, lines[last].ref)))
            else:
                kind, fields = "stat", payload
                if last > index:
                    status = "inferred"
                    item.issues.append(Issue("folded_stat", "历史 STAT 折行拼接，字段按推断处理；身份未用于归属", span(line.ref, lines[last].ref)))
        else:
            # Plain/Rich traceback is indexed as a block, no locals are copied out.
            traceback_index = None
            cursor = index + 1
            while cursor < min(len(lines), index + 513):
                text = lines[cursor].text
                if DATE_START.match(text) or EQ.match(text.strip()) or TITLE.match(text.strip()):
                    break
                if "Traceback (most recent call last)" in text:
                    traceback_index = cursor
                cursor += 1
            if traceback_index is not None:
                events.append(Event("traceback", ts, span(line.ref, lines[cursor - 1].ref), {}, "confirmed", source, int(header["line"]), level))
                for tail in lines[traceback_index:cursor]:
                    # Rich's terminal exception is outside the frame, at column zero.
                    # Boxed/indented text may be source code or locals, never a trigger.
                    match = EXCEPTION.match(tail.text)
                    if match:
                        events.append(Event("control_end" if match[1] == "TaskEnd" else "exception", ts, span(line.ref, tail.ref),
                                            exception_fields(match[1], tail.text.partition(":")[2].strip()), "confirmed", source, int(header["line"]), level))
                last = cursor - 1
            else:
                while last + 1 < min(len(lines), index + 9):
                    text = lines[last + 1].text
                    if not text.startswith("    ") or not text.strip() or DATE_START.match(text.lstrip()) or TITLE.match(text.strip()) or EQ.match(text.strip()):
                        break
                    body += " " + text.strip()
                    last += 1
                if last > index:
                    status = "inferred"
                    item.issues.append(Issue("rich_fold", "普通 Rich 折行按推断恢复，不保证原始空格", span(line.ref, lines[last].ref)))
            kind, fields = classify(body, source, level)
        events.append(Event(kind, ts, span(line.ref, lines[last].ref), fields, status, source, int(header["line"]), level))
        index = last + 1
    timestamps = [event.ts for event in events if event.ts is not None]
    effective_end = end if end is not None else max(timestamps, default=None)
    effective_start = start if start is not None else (effective_end - timedelta(minutes=max_window_minutes) if effective_end else None)
    # Boundary times are unknown. Anchor to the NEXT timestamp only for inclusion;
    # still leave their timestamp null, never claim a new process/session.
    next_ts = None
    selected = []
    for event in reversed(events):
        if event.ts is not None:
            next_ts = event.ts
        anchor = event.ts or next_ts
        if anchor is None:
            if effective_start is None:
                selected.append(event)
            else:
                item.issues.append(Issue("unplaced_event", "无可定位时间的行不纳入时间窗口结论", event.ref))
        elif effective_start <= anchor <= effective_end:
            selected.append(event)
    item.events = list(reversed(selected))
    if len(item.events) < len(events):
        item.issues.append(Issue("time_filter", "部分已读行在时间窗口外或时间 unknown；未用于五问"))
    unknown = [e for e in item.events if e.kind == "unknown"]
    if unknown:
        item.issues.append(Issue("unknown_lines", f"窗口内 {len(unknown)} 条未知记录；仅保留位置，不猜测内容", unknown[0].ref))
    item.lines = []  # raw text is not part of report/index serialization
    return effective_start, effective_end
