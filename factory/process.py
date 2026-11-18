"""Bounded POSIX process groups. Never invokes a shell: argv lists only."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    argv: list
    returncode: int
    timed_out: bool
    duration_s: float
    log: str
    launch_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _stop(process: subprocess.Popen) -> None:
    """Kill the whole process group (children included), TERM then KILL."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    process.wait()


def run_process(argv: list[str], cwd: Path | str, timeout_s: float, log: Path | str,
                stdin_text: str = "", env: dict | None = None) -> ProcessResult:
    """Run argv in its own session; stdout+stderr go to `log`; stdin comes from a file.

    The process group is always killed afterwards so background descendants cannot keep
    mutating the candidate.
    """
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    stdin_path = log.with_name(log.name + ".stdin")
    with log.open("wb") as out:
        if stdin_text:
            stdin_path.write_text(stdin_text)
            inp = stdin_path.open("rb")
        else:
            inp = open(os.devnull, "rb")
        with inp:
            try:
                process = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), env=env, stdin=inp,
                                           stdout=out, stderr=subprocess.STDOUT,
                                           start_new_session=True)
            except OSError as e:
                out.write(f"launch failed: {e}\n".encode())
                return ProcessResult(list(argv), 127, False, time.monotonic() - started,
                                     str(log), str(e))
            try:
                process.wait(timeout=max(0.001, timeout_s))
            except subprocess.TimeoutExpired:
                timed_out = True
            except BaseException:
                _stop(process)
                raise
            finally:
                _stop(process)
    rc = 124 if timed_out else process.returncode
    return ProcessResult(list(argv), rc, timed_out, time.monotonic() - started, str(log))
