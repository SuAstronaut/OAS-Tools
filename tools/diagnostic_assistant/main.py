"""Standalone, standard-library-only offline CLI. Never imports OAS."""
import argparse
import json
import sys

from parser import parse_file
from reader import FIXTURE_ROOT, OAS_ROOT, collect, output_path, parse_time, validate_limits
from report import build_report, markdown


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "catalog":
        from catalog import main as catalog_main
        return catalog_main(arguments[1:])
    cli = argparse.ArgumentParser(description="OAS D1 offline read-only diagnostic evidence report")
    cli.add_argument("--log", action="append", default=[], help="Explicit log/YYYY-MM-DD_<exact-name>.txt; may repeat")
    cli.add_argument("--error-package", help="Explicit log/error/<timestamp or name_timestamp> directory")
    cli.add_argument("--start", help="OAS local time, e.g. 2026-10-02T09:00:00")
    cli.add_argument("--end", help="Inclusive local time; supply together with --start")
    cli.add_argument("--max-files", type=int, default=4)
    cli.add_argument("--max-bytes", type=int, default=2097152, help="Actual total text read budget, equally allocated to selected files")
    cli.add_argument("--max-window-minutes", type=float, default=30)
    cli.add_argument("--fixtures", action="store_true", help="Use ONLY bundled synthetic sample_oas root instead of fixed production OAS root")
    cli.add_argument("--format", choices=("markdown", "json"), default="markdown")
    cli.add_argument("--output", help="NEW .md/.json under tool/reports; default stdout, no file writes")
    args = cli.parse_args(argv)
    try:
        start, end = parse_time(args.start), parse_time(args.end)
        validate_limits(args.max_files, args.max_bytes, args.max_window_minutes, start, end)
        destination = output_path(args.output) if args.output else None
        if destination and destination.suffix.lower() != (".json" if args.format == "json" else ".md"):
            raise ValueError("Output suffix must match --format")
        root = FIXTURE_ROOT if args.fixtures else OAS_ROOT
        files = collect(args.log, args.error_package, root, args.max_files, args.max_bytes)
        windows = [parse_file(f, start, end, args.max_window_minutes) for f in files]
        data = build_report(files, windows, {"max_files": args.max_files, "max_bytes": args.max_bytes,
                                           "max_window_minutes": args.max_window_minutes}, str(root))
        content = json.dumps(data, ensure_ascii=False, indent=2) if args.format == "json" else markdown(data)
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents accidental overwrite even if it appeared meanwhile.
            with destination.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content + ("\n" if not content.endswith("\n") else ""))
            print(f"Report saved: {destination}")
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print(content)
        return 0
    except (ValueError, OSError) as exc:
        print(f"Diagnostic input/output rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
