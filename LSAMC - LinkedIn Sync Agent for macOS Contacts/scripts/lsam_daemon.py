"""
lsam_daemon.py — LSAM Supervisor Daemon Wrapper
================================================
Forks a fully detached supervisor process:
  1. Calls os.setsid() to create a new OS session (new SID + new PGID).
     The child is now immune to signals sent to the parent's process group,
     including the SIGHUP/SIGKILL that Claude Code issues on context compaction.
  2. Redirects child stdout/stderr to logs/supervisor_stdout.log.
  3. Writes child PID to logs/supervisor.pid.
  4. Parent exits immediately (shell launch_supervisor.sh gets back control).

Usage (called by launch_supervisor.sh):
    python3 scripts/lsam_daemon.py /path/to/project/root

macOS note: `setsid` binary is Linux-only. os.setsid() is the correct primitive
on macOS and is always available in Python's stdlib.
"""

import os
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: lsam_daemon.py <project_root>", file=sys.stderr)
        sys.exit(1)

    project_root = sys.argv[1]
    log_file     = os.path.join(project_root, "logs", "supervisor_stdout.log")
    pid_file     = os.path.join(project_root, "logs", "supervisor.pid")

    # ── Fork child ──────────────────────────────────────────────────────────
    child_pid = os.fork()

    if child_pid > 0:
        # Parent: write PID file and exit so the shell gets back control.
        with open(pid_file, "w") as f:
            f.write(str(child_pid))
        sys.exit(0)

    # ── Child: detach and exec supervisor ───────────────────────────────────

    # Create a new OS session — new SID and new PGID.
    # From this point the child is NOT in the caller's process group.
    os.setsid()

    # Change to project root (supervisor.py uses relative paths everywhere)
    os.chdir(project_root)

    # Redirect stdout/stderr to the log file (append)
    log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, sys.stdout.fileno())
    os.dup2(log_fd, sys.stderr.fileno())
    os.close(log_fd)

    # Build environment
    env = os.environ.copy()
    env["LSAMC_ENGINE"] = "PRO"

    # Replace this process image with supervisor.py — no Python wrapper overhead
    os.execve(
        sys.executable,
        [sys.executable, "supervisor.py", "--live"],
        env,
    )
    # os.execve never returns on success


if __name__ == "__main__":
    main()
