"""The typing alias accepts real schemas without silencing invalid arguments."""

import subprocess
from typing import TYPE_CHECKING

import check_types
import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("invalid", [False, True])
def test_schema_types_follow_home_assistant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, invalid: bool
) -> None:
    source = tmp_path / "schema_check.py"
    schema = '"not a schema"' if invalid else 'vol.Schema({"host": str})'
    source.write_text(
        "import voluptuous as vol\n"
        "from homeassistant.config_entries import ConfigFlow\n"
        "def show(flow: ConfigFlow) -> None:\n"
        f"    flow.async_show_form(step_id='user', data_schema={schema})\n",
        encoding="utf-8",
    )
    run = subprocess.run

    def check_sample(
        command: list[str], *, env: dict[str, str], check: bool
    ) -> subprocess.CompletedProcess[str]:
        result = run(
            [*command[:3], str(source)],
            env=env,
            check=check,
            capture_output=True,
            text=True,
        )
        if invalid:
            assert "[arg-type]" in result.stdout
        else:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    monkeypatch.setattr(subprocess, "run", check_sample)
    assert check_types.check_types() == int(invalid)
