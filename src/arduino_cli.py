from __future__ import annotations

import subprocess
from pathlib import Path


class ArduinoCLIError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ArduinoCLIError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def compile_sketch(sketch_path: str, fqbn: str) -> None:
    _run(["arduino-cli", "compile", "--fqbn", fqbn, sketch_path])


def upload_sketch(sketch_path: str, fqbn: str, port: str) -> None:
    _run(["arduino-cli", "upload", "-p", port, "--fqbn", fqbn, sketch_path])
