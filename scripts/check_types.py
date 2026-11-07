"""Run strict mypy with the validation library Home Assistant actually uses.

Since 2026.9, Home Assistant aliases voluptuous to Probatio at startup. Mypy
cannot see sys.modules aliases, so a temporary stub mirrors that re-export.
The floor still uses voluptuous and needs no stub. Neither path silences
schema errors or changes the integration's runtime imports.
"""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import homeassistant  # noqa: F401  # Install Home Assistant's runtime aliases first.
import voluptuous as vol


def check_types() -> int:
    """Check all sources, mirroring the installed Home Assistant's alias."""
    with TemporaryDirectory(prefix="heatit-mypy-") as directory:
        env = os.environ.copy()
        if vol.Schema.__module__.split(".")[0] == "probatio":
            Path(directory, "voluptuous.pyi").write_text(
                "from probatio import *\n", encoding="utf-8"
            )
            env["MYPYPATH"] = os.pathsep.join(
                filter(None, (directory, env.get("MYPYPATH")))
            )
        return subprocess.run(
            [sys.executable, "-m", "mypy", "custom_components", "scripts", "tests"],
            env=env,
            check=False,
        ).returncode


if __name__ == "__main__":
    sys.exit(check_types())
