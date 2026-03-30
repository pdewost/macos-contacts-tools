import os
import signal
import psutil
import logging
import atexit
import weakref

logger = logging.getLogger(__name__)

class ProcessGuardian:
    """
    A safe context manager for tracking and cleaning up subprocesses.
    Unlike 'pkill', this ONLY terminates processes explicitly registered by this instance.
    """
    _instances = set()

    def __init__(self):
        self._tracked_pids = set()
        self._finalizer = weakref.finalize(self, self.cleanup)
        ProcessGuardian._instances.add(self)

    def register(self, pid: int):
        """Register a PID to be cleaned up on exit."""
        if pid:
            self._tracked_pids.add(pid)
            logger.debug(f"[Guardian] Tracking PID: {pid}")

    def cleanup(self):
        """Terminate all tracked processes safely."""
        if not self._tracked_pids:
            return

        logger.info(f"[Guardian] Cleaning up {len(self._tracked_pids)} tracked processes...")
        
        for pid in list(self._tracked_pids):
            try:
                if not psutil.pid_exists(pid):
                    self._tracked_pids.discard(pid)
                    continue

                proc = psutil.Process(pid)
                proc.terminate()
                
                # Give it a moment to die gracefully
                try:
                    proc.wait(timeout=2)
                except psutil.TimeoutExpired:
                    logger.warning(f"[Guardian] PID {pid} stubborn. Force killing.")
                    proc.kill()
                
                logger.info(f"[Guardian] Terminated PID: {pid}")
                self._tracked_pids.discard(pid)
            except (psutil.NoSuchProcess, ProcessLookupError):
                self._tracked_pids.discard(pid)
            except Exception as e:
                logger.error(f"[Guardian] Failed to kill PID {pid}: {e}")

    @classmethod
    def global_cleanup(cls):
        """Cleanup all guardians (useful for signal handlers)."""
        for instance in list(cls._instances):
            instance.cleanup()

# Register global cleanup on interpreter exit
atexit.register(ProcessGuardian.global_cleanup)
