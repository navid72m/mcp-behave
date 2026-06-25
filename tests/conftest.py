"""Shared pytest config: skip strace-based tests on non-Linux hosts."""
import shutil, sys, pytest

requires_strace = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("strace") is None,
    reason="strace is Linux-only; install strace or run tests in Docker",
)
