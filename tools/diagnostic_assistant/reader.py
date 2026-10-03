"""Strict allowlist and bounded tail snapshots; never scans log history."""
import os
import re
import stat
from collections import deque
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from models import EvidenceFile, Issue, Line, Reference

TOOL_ROOT = Path(__file__).resolve().parent
OAS_ROOT = Path(r"D:\Entertainment\Tool\OAS")
FIXTURE_ROOT = TOOL_ROOT / "fixtures" / "sample_oas"
LOG_NAME = re.compile(r'(\d{4}-\d{2}-\d{2})_([^<>:"/\\|?*\x00-\x1f]+)\.txt\Z')
PACKAGE_NAME = re.compile(r'(?:[^<>:"/\\|?*\x00-\x1f]+_)?\d{10,}\Z')


def no_links(path: Path):
    # Check lexical ancestors too: resolve alone would hide junction/symlink aliases.
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Symlink/reparse paths are forbidden")
    if path.is_file() and path.stat().st_nlink > 1:
        raise ValueError("Hard-linked inputs/outputs are forbidden")


def allowed(path, root, package=False):
    root = Path(root).absolute()
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    path = path.absolute()
    no_links(root)
    no_links(path)
    resolved = path.resolve(strict=True)
    try:
        parts = resolved.relative_to(root.resolve(strict=True)).parts
    except ValueError as exc:
        raise ValueError("Input outside permitted OAS root") from exc
    if package:
        if len(parts) != 3 or parts[:2] != ("log", "error") or not PACKAGE_NAME.fullmatch(parts[2]):
            raise ValueError("Only an explicit log/error/<timestamp or name_timestamp> package is permitted")
        if not resolved.is_dir():
            raise ValueError("Error package must be a directory")
    else:
        match = LOG_NAME.fullmatch(parts[-1]) if len(parts) == 2 and parts[0] == "log" else None
        if not match or not resolved.is_file():
            raise ValueError("Only a direct log/YYYY-MM-DD_<exact-name>.txt file is permitted")
        date.fromisoformat(match[1])
    return resolved


def parse_time(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError("Use timezone-free OAS local timestamps (no offset/Z)")
    return result


def validate_limits(max_files, max_bytes, max_window_minutes, start=None, end=None):
    if not 1 <= max_files <= 16 or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise ValueError("Limits: max-files 1..16; max-bytes 1..16777216")
    if not 0 < max_window_minutes <= 1440:
        raise ValueError("max-window-minutes must be >0 and <=1440")
    if (start is None) != (end is None):
        raise ValueError("--start and --end must be supplied together")
    if start is not None and (end < start or end - start > timedelta(minutes=max_window_minutes)):
        raise ValueError("Time window reversed or exceeds maximum")


def collect(logs, package, root, max_files=4, max_bytes=2 * 1024 * 1024):
    paths = []
    for value in logs:
        path = allowed(value, root)
        if path in [item[0] for item in paths]:
            raise ValueError("Duplicate log input")
        paths.append((path, None, LOG_NAME.fullmatch(path.name)[2], []))
    if package:
        directory = allowed(package, root, package=True)
        image_refs = []
        # Only the explicitly selected package, metadata only, bounded enumeration.
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= 256:
                    raise ValueError("Error package has more than 256 directory entries")
                if entry.name.lower().endswith(".png") and entry.is_file(follow_symlinks=False):
                    image_refs.append((directory / entry.name).relative_to(root).as_posix())
        path = directory / "log.txt"
        no_links(path)
        if path.exists() and (not path.is_file() or path.resolve().parent != directory):
            raise ValueError("Invalid error package log.txt")
        paths.append((path, directory.name, None, sorted(image_refs)))
    if not paths:
        raise ValueError("Specify --log and/or --error-package; no automatic history scan")
    if len(paths) > max_files:
        raise ValueError("Selected text file count exceeds max-files (including package log.txt)")
    files = []
    budget = max_bytes // len(paths)
    for path, package_name, candidate, images in paths:
        rel = path.relative_to(root.resolve()).as_posix()
        item = EvidenceFile(rel, candidate, package_name, 0, 0, 0, image_refs=images)
        files.append(item)
        if not path.exists():
            item.issues.append(Issue("missing_text", "错误包没有 log.txt；正文 unknown"))
            continue
        no_links(path)
        with path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            if before.st_nlink > 1:
                raise ValueError("Hard-linked input is forbidden")
            item.size = before.st_size
            item.read_start = max(0, item.size - budget)
            handle.seek(item.read_start)
            data = handle.read(min(item.size, budget))
            item.read_bytes = len(data)
            after = os.fstat(handle.fileno())
        whole_ref = Reference(rel, item.read_start, item.read_start + len(data))
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            item.issues.append(Issue("changed_during_read", "读取期间文件变化；仅为局部快照", whole_ref))
        if item.read_start:
            item.issues.append(Issue("byte_limit", "只读取文件尾部；较早证据未读，行号 unknown，使用 byte offset", whole_ref))
            skip = data.find(b"\n") + 1
            if not skip:
                skip = len(data)
            data = data[skip:]
            offset = item.read_start + skip
            line_no = None
        else:
            offset, line_no = 0, 1
        if data and not data.endswith(b"\n"):
            item.issues.append(Issue("partial_tail", "末尾未换行/可能截断；半行不作为可靠事件", whole_ref))
        retained = deque(maxlen=20000)
        physical_count = 0
        for raw in BytesIO(data):
            physical_count += 1
            ref = Reference(rel, offset, offset + len(raw), line_no, line_no)
            offset += len(raw)
            if line_no is not None:
                line_no += 1
            if not raw.endswith(b"\n"):
                continue
            if len(raw) > 65536:
                retained.append(Line("", ref))
                item.issues.append(Issue("line_limit", "单行超过64KiB；只保留位置，不解释", ref))
                continue
            try:
                text = raw.decode("utf-8").rstrip("\r\n")
                if ref.start == 0:
                    text = text.lstrip("\ufeff")
                retained.append(Line(text, ref))
            except UnicodeDecodeError:
                retained.append(Line("", ref))
                item.issues.append(Issue("bad_utf8", "该行 UTF-8 损坏，未解释内容", ref))
        item.lines = list(retained)
        if physical_count > 20000:
            item.issues.append(Issue("line_count_limit", "已读片段物理行数超过20000，只解释最后20000行；更早上下文 unknown", whole_ref))
    return files


def output_path(value):
    path = Path(value).absolute()
    no_links(path)
    try:
        path.resolve().relative_to((TOOL_ROOT / "reports").resolve())
    except ValueError as exc:
        raise ValueError("Output must be a NEW .md/.json file under this tool's reports directory") from exc
    if path.suffix.lower() not in {".md", ".json"} or path.exists():
        raise ValueError("Output must be a NEW .md/.json file (never overwrite)")
    return path
