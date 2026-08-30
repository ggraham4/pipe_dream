"""
Background job management for the "Data & Updates" tab: launching a
subprocess pipeline (stock data pull -> feature rebuild -> retrain, or an
options data update), letting the Streamlit UI poll its status/log without
blocking, and keeping a small on-disk record of the last run of each job so
"is this stale" survives an app restart.

Streamlit reruns the whole script on every interaction, so this deliberately
avoids in-memory background threads (they'd die with the rerun) in favor of
a real detached OS subprocess per job, with its state (pid, log, status)
recorded to files under app/logs/<job_name>/. The UI polls those files.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from . import paths

paths.ensure_dirs()


@dataclass
class JobState:
    job_name: str
    status: str            # "idle" | "running" | "done" | "failed"
    pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    current_step: str | None = None
    total_steps: int | None = None
    return_code: int | None = None


def _job_dir(job_name: str) -> Path:
    d = paths.LOGS_DIR / job_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(job_name: str) -> Path:
    return _job_dir(job_name) / "state.json"


def _log_path(job_name: str) -> Path:
    return _job_dir(job_name) / "run.log"


def _write_state(state: JobState):
    _state_path(state.job_name).write_text(json.dumps(asdict(state), indent=2))


def read_state(job_name: str) -> JobState:
    p = _state_path(job_name)
    if not p.exists():
        return JobState(job_name=job_name, status="idle")
    try:
        return JobState(**json.loads(p.read_text()))
    except Exception:
        return JobState(job_name=job_name, status="idle")


def _pid_alive(pid: int | None) -> bool:
    """True if the job's process is still actually running.

    Streamlit reruns the whole script on every interaction, so nothing here
    holds a live subprocess.Popen handle across reruns -- state is
    reconstructed from disk each time via the pid. That means the finished
    child is never reaped by a `.wait()` call the normal way, so on Linux it
    sits around as a zombie ('Z' state) -- which `os.kill(pid, 0)` alone
    reports as "alive" forever, since a zombie still holds its PID until
    reaped. Fixed by: (1) actually reaping it via a non-blocking waitpid
    (this process IS its parent, via subprocess.Popen, so this is safe and
    correct on both Linux and macOS), and (2), belt-and-suspenders on Linux,
    treating a 'Z' /proc state as not-alive even if something reaped it via
    another path first.
    """
    if not pid:
        return False
    try:
        reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        if reaped_pid == pid:
            return False  # just reaped -- it had already exited
    except ChildProcessError:
        pass  # not (or no longer) our child -- fall through to a liveness check
    except OSError:
        pass

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False

    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        state_field = stat.rsplit(")", 1)[-1].split()[0]
        if state_field == "Z":
            return False
    except (FileNotFoundError, OSError):
        pass  # not on Linux, or already gone -- the os.kill check above is authoritative here

    return True


def tail_log(job_name: str, n_lines: int = 200) -> str:
    p = _log_path(job_name)
    if not p.exists():
        return "(no log yet)"
    lines = p.read_text(errors="replace").splitlines()
    return "\n".join(lines[-n_lines:])


def refresh_status(job_name: str) -> JobState:
    """Reconcile the recorded state against whether the OS process is still
    alive -- catches the case where a subprocess finished (or was killed)
    between polls without updating its own state file."""
    state = read_state(job_name)
    if state.status == "running" and not _pid_alive(state.pid):
        # process exited; look at the log's own sentinel line for the
        # real outcome, written by run_step_sequence() below.
        log = tail_log(job_name, 5)
        state.status = "done" if "PIPELINE_OK" in log else "failed"
        state.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state)
    return state


def run_step_sequence(job_name: str, commands: list[list[str]], step_labels: list[str] | None = None,
                       cwd: Path | None = None):
    """Launch a sequence of commands as ONE detached background process
    (a small wrapper shell loop), so the UI only has to track one pid per
    job even though several scripts run in order. Any failing step aborts
    the sequence; the log makes clear which step failed.
    """
    if step_labels is None:
        step_labels = [" ".join(c) for c in commands]

    log_path = _log_path(job_name)
    wrapper_path = _job_dir(job_name) / "run.sh"

    lines = ["#!/bin/bash", "set -e"]
    for label, cmd in zip(step_labels, commands):
        quoted = " ".join(f'"{c}"' for c in cmd)
        lines.append(f'echo "=== STEP: {label} ==="')
        lines.append(quoted)
    lines.append('echo "PIPELINE_OK"')
    wrapper_path.write_text("\n".join(lines) + "\n")
    wrapper_path.chmod(0o755)

    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            ["/bin/bash", str(wrapper_path)],
            stdout=logf, stderr=subprocess.STDOUT,
            cwd=str(cwd) if cwd else None,
            start_new_session=True,  # detach so it survives the Streamlit process's own lifecycle
        )

    state = JobState(
        job_name=job_name, status="running", pid=proc.pid,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        current_step=step_labels[0] if step_labels else None,
        total_steps=len(commands),
    )
    _write_state(state)
    return state


def cancel_job(job_name: str):
    state = read_state(job_name)
    if state.pid and _pid_alive(state.pid):
        try:
            os.killpg(os.getpgid(state.pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(state.pid, signal.SIGTERM)
            except Exception:
                pass
    state.status = "failed"
    state.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_state(state)
