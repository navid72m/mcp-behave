"""End-to-end tests against the bundled leaky/honest fixtures.

These are the highest-value regression tests in the repo: they catch any change
that would either (a) miss a known-bad server or (b) false-positive on a known-good
one. Both failure modes would break the project's whole credibility."""
import asyncio, json, os, sys
from pathlib import Path

import pytest

from mcp_behave import probe, report
from tests.conftest import requires_strace

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS   = REPO_ROOT / "targets"


def _seed_canaries(home: Path) -> None:
    """Plant the same canary files the real sandbox_home/ has, so the leaky
    server's ~/.ssh/id_rsa read hits something."""
    (home / ".ssh").mkdir(parents=True, exist_ok=True)
    (home / ".ssh" / "id_rsa").write_text("CANARY-SSH-PRIVATE-KEY\n")
    (home / ".env").write_text("CANARY_SECRET=canary\n")


def _run(server_script: str, tmp_path: Path, monkeypatch) -> list:
    """Probe one fixture server end-to-end; return findings."""
    out_dir = tmp_path / "out"
    state_dir = tmp_path / "state"
    home = tmp_path / "home"
    home.mkdir()
    _seed_canaries(home)

    # Isolate from the developer's environment: dedicated $HOME for canaries,
    # dedicated state dir so rug-pull check doesn't see prior runs.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("OUT_DIR", str(out_dir))
    monkeypatch.setenv("MCP_BEHAVE_STATE_DIR", str(state_dir))
    # Reload the module-level OUT_DIR constants that read os.environ at import time.
    probe.OUT_DIR    = str(out_dir)
    probe.TRACE_FILE = str(out_dir / "trace.log")
    probe.MANIFEST   = str(out_dir / "manifest.json")

    cmd = [sys.executable, str(TARGETS / server_script)]
    asyncio.run(probe.run(cmd, call_timeout=10))
    # resolve_dns=False keeps the test offline-deterministic.
    return report.report(str(out_dir), resolve_dns=False)


@requires_strace
def test_honest_server_produces_zero_findings(tmp_path, monkeypatch):
    findings = _run("honest_server.py", tmp_path, monkeypatch)
    high = [f for f in findings if f[0] == "HIGH"]
    assert high == [], f"honest server tripped HIGH findings: {high}"


@requires_strace
def test_leaky_server_trips_sensitive_read_and_network(tmp_path, monkeypatch):
    findings = _run("leaky_server.py", tmp_path, monkeypatch)
    messages = [m for _, m in findings]
    high = [(s, m) for s, m in findings if s == "HIGH"]
    assert any("id_rsa" in m for m in messages), \
        f"leaky server's ~/.ssh/id_rsa read was not detected. findings: {findings}"
    assert any("network egress" in m for m in messages), \
        f"leaky server's network egress was not detected. findings: {findings}"
    assert len(high) >= 2, f"expected >=2 HIGH findings, got {high}"


@requires_strace
def test_manifest_hash_is_stable_across_runs(tmp_path, monkeypatch):
    """The same server with the same advertised tools must produce the same
    sha256, otherwise rug-pull detection is just noise."""
    _run("honest_server.py", tmp_path, monkeypatch)
    h1 = json.loads(Path(tmp_path / "out" / "manifest.json").read_text())["manifest_sha256"]
    # Second run, fresh out_dir.
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    _run("honest_server.py", tmp2, monkeypatch)
    h2 = json.loads((tmp2 / "out" / "manifest.json").read_text())["manifest_sha256"]
    assert h1 == h2
