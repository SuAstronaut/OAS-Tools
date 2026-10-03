"""Bounded candidate discovery. Samples are clues, never a session index."""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

from models import EvidenceFile, Line, Reference
from parser import HEADER, parse_file
from reader import FIXTURE_ROOT, OAS_ROOT, LOG_NAME, PACKAGE_NAME, allowed, no_links, output_path, parse_time


def fact(value="unknown", status="unknown", evidence=None):
    return {"status": status, "value": value, "evidence": evidence or []}


class Budget:
    def __init__(self, total, per_file):
        self.limit, self.per_file, self.used = total, per_file, 0
        self.files = {}

    def read(self, handle, offset, length):
        key = str(handle.name)
        count = min(length, self.limit - self.used, self.per_file - self.files.get(key, 0))
        if count <= 0:
            return b""
        handle.seek(max(0, offset))
        data = handle.read(count)
        self.used += len(data)
        self.files[key] = self.files.get(key, 0) + len(data)
        return data


def sample_lines(data, offset, rel):
    # Discard partial first/last lines; original offsets survive every sample.
    if offset:
        skip = data.find(b"\n") + 1
        if not skip:
            return []
        data, offset = data[skip:], offset + skip
    result = []
    for raw in data.splitlines(keepends=True):
        if raw.endswith(b"\n"):
            try:
                result.append(Line(raw.decode("utf-8").rstrip("\r\n").lstrip("\ufeff"),
                                   Reference(rel, offset, offset + len(raw))))
            except UnicodeDecodeError:
                pass
        offset += len(raw)
    return result


def scan(path, root, budget, keyword=None, start=None, end=None):
    rel = path.relative_to(root).as_posix()
    size = path.stat().st_size
    match = LOG_NAME.fullmatch(path.name)
    entry = {"path": rel, "instance": fact(match[2], "inferred", ["filename: " + path.name]),
             "filename_instance": fact(match[2], "confirmed", ["filename: " + path.name]),
             "size_bytes": size, "task_clues": [], "start_clues": [], "failure_markers": [],
             "reasons": ["filename/metadata within requested selection"], "warnings": []}
    samples = []
    reliable_text = True
    with path.open("rb", buffering=0) as handle:
        before = os.fstat(handle.fileno())
        if before.st_nlink > 1:
            raise ValueError("Hard-linked input is forbidden")
        def read(offset, count):
            nonlocal reliable_text
            data = budget.read(handle, offset, count)
            if offset == 0 and len(data) == size:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    reliable_text = False
                if data and not data.endswith(b"\n"):
                    reliable_text = False
            lines = sample_lines(data, offset, rel)
            samples.append(lines)
            return lines
        capacity = min(budget.per_file, budget.limit - budget.used)
        if size <= capacity:
            read(0, size)
            complete = True
        else:
            complete = False
            unit = min(4096, max(1, capacity // 8))
            read(0, unit)
            read(max(0, size - unit), unit)
            if start:
                # Only a locator hint: chronology is not verified across unread bytes.
                low, high = 0, size
                for _ in range(12):
                    if high - low < 2048 or budget.files.get(str(path), 0) + 2048 > budget.per_file // 2:
                        break
                    mid = (low + high) // 2
                    lines = read(mid, 2048)
                    headers = [(line, HEADER.match(line.text)) for line in lines]
                    first = next(((line, h) for line, h in headers if h), None)
                    if not first:
                        break
                    try:
                        stamp = datetime.strptime(first[1]["ts"], "%Y-%m-%d %H:%M:%S.%f")
                    except ValueError:
                        break
                    if stamp < start:
                        low = mid
                    else:
                        high = mid
                read(low, min(32768, max(0, budget.per_file - budget.files.get(str(path), 0))))
                entry["warnings"].append("Time locator assumes chronological headers; absent evidence cannot exclude this file")
            else:
                # Deterministic spaced sampling; no linear whole-history search.
                remaining = min(budget.per_file - budget.files.get(str(path), 0), budget.limit - budget.used)
                for index in range(1, 9):
                    read(size * index // 9, remaining // 8)
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        complete = False
        entry["warnings"].append("File changed during read; snapshot incomplete")
    entry["read_bytes"] = budget.files.get(str(path), 0)
    entry["complete_body"] = complete
    if not reliable_text:
        entry["warnings"].append("Invalid UTF-8 or truncated final line; negative keyword/failure conclusions unknown")
    timestamps, hits, seen = [], [], set()
    timestamp_refs = {}
    time_hits = []
    for lines in samples:
        # Parse samples separately so missing gaps cannot synthesize folded JSON/traceback.
        item = EvidenceFile(rel, match[2], None, size, 0, 0, lines=lines)
        for line in lines:
            header = HEADER.match(line.text)
            if not header:
                continue
            try:
                stamp = datetime.strptime(header["ts"], "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                continue
            timestamps.append(stamp)
            timestamp_refs[stamp] = line.ref.label()
            if start and not start <= stamp <= end:
                continue
            time_hits.append(line.ref.label())
            if keyword and keyword.casefold() in header["body"].casefold():
                hits.append(line.ref.label())
            task = re.fullmatch(r"Current tasks: ([\w .\-\u4e00-\u9fff]{1,128})", header["body"].strip())
            if task and header["source"] == "battle.py" and line.ref.start not in seen:
                entry["task_clues"].append(fact({"kind": "current_tasks_label", "task": task[1], "time": stamp.isoformat()}, "confirmed", [line.ref.label()]))
                seen.add(line.ref.start)
        parse_file(item, start, end, 1440)
        for event in item.events:
            key = (event.ref.start, event.kind)
            if key in seen:
                continue
            seen.add(key)
            ref = [event.ref.label()]
            if event.kind in {"task_start", "task_end", "module"} or (event.kind == "stat" and event.fields.get("task")):
                entry["task_clues"].append(fact({"kind": event.kind, "fields": event.fields, "time": str(event.ts)}, event.status, ref))
            if event.kind == "start_block":
                entry["start_clues"].append(fact("START block; process/session boundary unknown", event.status, ref))
            if event.kind in {"exception", "timeout", "failure_condition", "error_signal", "traceback"} or (event.kind == "stat" and (event.fields["ev"] == "error" or event.fields.get("ok") is False)):
                entry["failure_markers"].append(fact(event.kind, event.status, ref))
    entry["visible_time_range"] = fact([min(timestamps).isoformat(), max(timestamps).isoformat()], "confirmed",
                                       [timestamp_refs[min(timestamps)], timestamp_refs[max(timestamps)]]) if timestamps else fact()
    entry["actual_run_range"] = fact()  # filename/date and START do not establish a run
    entry["keyword"] = fact(True, "confirmed", sorted(set(hits))) if hits else fact(False, "confirmed") if complete and reliable_text and keyword else fact()
    entry["time_overlap"] = fact(True, "confirmed", time_hits[:2]) if time_hits else fact(False, "confirmed") if complete and reliable_text and start else fact()
    entry["failure_marker_count"] = fact(len(entry["failure_markers"]), "confirmed", [ref for marker in entry["failure_markers"] for ref in marker["evidence"]])
    entry["failure_presence"] = fact(True, "confirmed", entry["failure_marker_count"]["evidence"]) if entry["failure_markers"] else fact(False, "confirmed") if complete and reliable_text else fact()
    entry["warnings"].append("Failure count covers sampled markers only, not independent incidents or whole-file totals")
    if hits:
        entry["reasons"].append("requested keyword observed in sampled header message")
    elif keyword:
        entry["reasons"].append("keyword not observed; " + ("complete file checked" if complete else "unread regions remain unknown"))
    if not complete:
        entry["warnings"].append("Partial sample; missing task/START/failure evidence is unknown")
    return entry


def discover(log_root, root=OAS_ROOT, date_from=None, date_to=None, instance=None, keyword=None,
             start=None, end=None, max_candidates=16, per_file=65536, total=262144, include_errors=False):
    root = Path(root).resolve(strict=True)
    directory = Path(log_root).absolute()
    no_links(directory)
    if directory.resolve(strict=True) != root / "log":
        raise ValueError("log-root must be the permitted OAS/log directory")
    if not 1 <= max_candidates <= 64 or not 1 <= per_file <= 262144 or not 1 <= total <= 4194304:
        raise ValueError("Catalog limits: candidates 1..64; per-file 1..262144; total 1..4194304")
    if (start is None) != (end is None) or (start and (end < start or (end-start).total_seconds() > 86400)):
        raise ValueError("Supply ordered start/end with window <=24h")
    if date_from and date_to and date_to < date_from:
        raise ValueError("Reversed date range")
    if keyword and (len(keyword) > 128 or any(ord(c) < 32 for c in keyword)):
        raise ValueError("Keyword must be <=128 printable characters")
    paths, enumeration_limited = [], False
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= 4096:
                enumeration_limited = True
                break
            match = LOG_NAME.fullmatch(entry.name)
            if not match:
                continue
            day = date.fromisoformat(match[1])
            if date_from and day < date_from or date_to and day > date_to or instance and match[2] != instance:
                continue
            paths.append(allowed(directory / entry.name, root))
    paths.sort(key=lambda p: p.name, reverse=True)
    budget = Budget(total, per_file)
    logs = [scan(path, root, budget, keyword, start, end) for path in paths[:max_candidates]]
    logs.sort(key=lambda item: item["keyword"]["value"] is True, reverse=True)
    packages = []
    if include_errors and len(logs) < max_candidates and (directory / "error").exists():
        no_links(directory / "error")
        with os.scandir(directory / "error") as entries:
            for index, entry in enumerate(entries):
                if index >= 4096 or len(logs) + len(packages) >= max_candidates:
                    break
                if PACKAGE_NAME.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False):
                    path = allowed(directory / "error" / entry.name, root, package=True)
                    packages.append({"path": path.relative_to(root).as_posix(), "instance": fact(),
                                     "possible_related_log": fact(), "reason": "package name metadata only; no time-based attribution"})
    return {"scope": "Candidate catalog, not complete history/session/task diagnosis",
            "limits": {"max_candidates": max_candidates, "per_file_bytes": per_file, "total_bytes": total},
            "read_bytes": budget.used, "selected_metadata_count": len(paths),
            "omitted_candidates": max(0, len(paths)-max_candidates), "enumeration_limited": enumeration_limited,
            "warnings": ["Date filters select filename dates; cross-day sessions remain unknown", "Task labels prove log messages, not task success", "Unknown keyword candidates are retained, not classified as matching tasks"],
            "logs": logs, "error_packages": packages}


def main(argv=None):
    cli = argparse.ArgumentParser(description="Read-only bounded OAS log candidate catalog")
    cli.add_argument("--log-root", default=str(OAS_ROOT / "log"))
    cli.add_argument("--fixtures", action="store_true")
    cli.add_argument("--date")
    cli.add_argument("--date-from")
    cli.add_argument("--date-to")
    cli.add_argument("--instance")
    cli.add_argument("--keyword")
    cli.add_argument("--start")
    cli.add_argument("--end")
    cli.add_argument("--max-candidates", type=int, default=16)
    cli.add_argument("--per-file-bytes", type=int, default=65536)
    cli.add_argument("--total-bytes", type=int, default=262144)
    cli.add_argument("--include-errors", action="store_true", help="Metadata only; instance always unknown")
    cli.add_argument("--output", help="NEW .json under tool/reports; otherwise stdout")
    args = cli.parse_args(argv)
    try:
        root = FIXTURE_ROOT if args.fixtures else OAS_ROOT
        if args.date and (args.date_from or args.date_to):
            raise ValueError("Use date OR date-from/date-to")
        first = date.fromisoformat(args.date or args.date_from) if args.date or args.date_from else None
        last = date.fromisoformat(args.date or args.date_to) if args.date or args.date_to else None
        destination = output_path(args.output) if args.output else None
        if destination and destination.suffix != ".json":
            raise ValueError("Catalog output must be .json")
        data = discover(args.log_root, root, first, last, args.instance, args.keyword,
                        parse_time(args.start), parse_time(args.end), args.max_candidates,
                        args.per_file_bytes, args.total_bytes, args.include_errors)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as handle:
                handle.write(text + "\n")
            print(f"Catalog saved: {destination}")
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print(text)
        return 0
    except (ValueError, OSError) as exc:
        print(f"Catalog rejected: {exc}", file=sys.stderr)
        return 2
