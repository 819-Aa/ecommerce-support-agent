"""Run the actual PowerShell charge guard with uv replaced by a harmless recorder."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows entrypoint")
@pytest.mark.parametrize(
    ("file_mode", "process_mode", "should_run_batch"),
    [
        ('CUSTOMER_SUPPORT_MODE="compatible"', None, False),
        ("CUSTOMER_SUPPORT_MODE=mock", "compatible", False),
        ("CUSTOMER_SUPPORT_MODE=compatible", "mock", True),
        ("CUSTOMER_SUPPORT_MODE='mock'", None, True),
        ("", None, False),
    ],
)
def test_http_batch_requires_explicit_effective_mock_mode(
    tmp_path: Path,
    file_mode: str,
    process_mode: str | None,
    should_run_batch: bool,
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(Path("scripts/run_tests.ps1"), scripts / "run_tests.ps1")
    (tmp_path / ".env").write_text(file_mode, encoding="utf-8")
    # Deliberately do not pass credentials or application env vars to the child.
    child_env = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATH"}
    }
    if process_mode:
        child_env["CUSTOMER_SUPPORT_MODE"] = process_mode
    command = """
function uv {
    Add-Content -LiteralPath 'uv-invocations.txt' -Value ($args -join ' ')
    $global:LASTEXITCODE = 0
}
& ./scripts/run_tests.ps1
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    invoked = (tmp_path / "uv-invocations.txt").read_text(encoding="utf-8-sig")
    assert ("scripts/demo_check.py" in invoked) is should_run_batch
