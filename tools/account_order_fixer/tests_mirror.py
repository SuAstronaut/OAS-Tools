"""Synthetic mirror validation; never reads or writes production OAS config."""
from contextlib import redirect_stdout
from functools import partial
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import main
import tests as original_tests


def run():
    with TemporaryDirectory(prefix="oas-tools-order-") as directory:
        root = Path(directory)
        config = root / "config"
        config.mkdir()
        target = config / "synthetic.json"
        original_tests.fixture(target, [1, 2, 3])
        work = root / "test-work"
        work.mkdir()
        # Keep the original seven tests intact, but route their one default-root
        # read and all temporary files to synthetic data outside both tool trees.
        with patch.object(main, "DEFAULT_CONFIG_DIR", config), patch.object(original_tests, "TOOL_DIR", work):
            assert original_tests.main_test() == 0

        before = target.read_bytes()
        with patch("builtins.input", side_effect=["1", "1", "NO"]), patch.object(main, "fix_file") as writer:
            output = StringIO()
            with redirect_stdout(output):
                assert main.run_interactive(config) == 0
            writer.assert_not_called()
        assert target.read_bytes() == before
        assert "预计上号顺序" in output.getvalue()
        assert not (root / "backup").exists()
        print("PASS: preview and cancellation do not write")

        safe_writer = partial(main.fix_file, backup_dir=root / "backup", now=original_tests.FIXED_NOW)
        with patch("builtins.input", side_effect=["1", "2", "YES"]), patch.object(main, "fix_file", safe_writer):
            with redirect_stdout(StringIO()):
                assert main.run_interactive(config) == 0
        backups = list((root / "backup").glob("*.json"))
        assert len(backups) == 1 and backups[0].read_bytes() == before
        after = main.inspect_config(target)
        assert [slot.index for slot in main.chronological_order(after.slots, after.time_format)] == [3, 2, 1]
        assert not list(config.glob("*.tmp"))
        print("PASS: YES, backup, atomic write, and post-write verification")
    print("PASS: 7 original tests + 2 interactive mirror checks; synthetic data only")


if __name__ == "__main__":
    run()
