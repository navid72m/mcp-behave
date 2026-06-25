"""Declared-vs-observed reporter. Compares the manifest the server advertises
against the syscalls it actually issued, plus the manifest it advertised on
previous runs (rug-pull detection).

Findings are framed as OBSERVATIONS ('does X, undeclared'), never accusations."""
import hashlib, json, os, socket, sys
from pathlib import Path
from .analyze import analyze

SENSITIVE = (".ssh", "id_rsa", "id_ed25519", ".env", ".aws", "credentials",
             ".netrc", "/etc/shadow", ".kube", ".docker/config")

# Where per-server manifest hashes are persisted across runs for rug-pull
# detection. Honors XDG; falls back to ~/.local/share. Override with $MCP_BEHAVE_STATE_DIR.
def _state_dir() -> Path:
    override = os.environ.get("MCP_BEHAVE_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "mcp-behave" / "manifests"


def _server_fingerprint(server_cmd: list[str]) -> str:
    """Stable per-server key for the rug-pull store. Uses the command tokens
    verbatim -- two invocations with identical commands are treated as the same
    server. Differing flags (e.g. different filesystem roots) produce different
    fingerprints, which is the correct behavior."""
    return hashlib.sha256(json.dumps(server_cmd or []).encode()).hexdigest()[:16]


def _resolve(ip: str, timeout: float = 0.5) -> str | None:
    """Reverse-DNS, best-effort. Network failures or PTR-less IPs return None."""
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        host, _, _ = socket.gethostbyaddr(ip.split(":")[0])
        return host
    except (socket.herror, socket.gaierror, OSError):
        return None
    finally:
        socket.setdefaulttimeout(old)


def load(out_dir):
    with open(os.path.join(out_dir, "manifest.json")) as f:
        manifest = json.load(f)
    profile = analyze(os.path.join(out_dir, "trace.log"))
    return manifest, profile


def _all_descriptions(manifest: dict) -> str:
    """Flatten descriptions across tools, resources, and prompts for keyword scan."""
    parts = []
    for item in manifest.get("tools", []):
        parts.append(item.get("description") or "")
    for item in manifest.get("resources", []):
        parts.append(item.get("description") or "")
    for item in manifest.get("prompts", []):
        parts.append(item.get("description") or "")
    return " ".join(parts).lower()


def _rugpull_check(manifest: dict) -> tuple[str, str] | None:
    """Compare this run's manifest hash against the stored one for this server.
    Returns a finding tuple if changed, None otherwise. Updates the store either way."""
    cmd = manifest.get("server_cmd") or []
    current = manifest.get("manifest_sha256")
    if not current:
        return None
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    record = state / f"{_server_fingerprint(cmd)}.json"
    finding = None
    if record.exists():
        try:
            prev = json.loads(record.read_text()).get("manifest_sha256")
        except (json.JSONDecodeError, OSError):
            prev = None
        if prev and prev != current:
            finding = ("HIGH",
                       f"declared surface changed since last run "
                       f"(was {prev[:12]}, now {current[:12]}) -- "
                       f"possible rug-pull")
    record.write_text(json.dumps({"server_cmd": cmd,
                                   "manifest_sha256": current}, indent=2))
    return finding


def build_findings(manifest: dict, profile: dict, resolve_dns: bool = True) -> list:
    """Returns list of (severity, message) tuples. Pure function -- no I/O
    except optional reverse-DNS lookups."""
    descs = _all_descriptions(manifest)
    claims_local = any(w in descs for w in ("local", "offline", "no network"))
    findings = []

    for ipport in profile["network_connects"]:
        host = _resolve(ipport) if resolve_dns else None
        where = f"{ipport} ({host})" if host else ipport
        sev = "HIGH" if claims_local else "INFO"
        note = " -- but a description claims local/offline operation" if claims_local else ""
        findings.append((sev, f"network egress to {where}{note}"))

    for path in profile["files_opened"]:
        if any(s in path for s in SENSITIVE):
            findings.append(("HIGH", f"read a sensitive path: {path}"))

    rug = _rugpull_check(manifest)
    if rug:
        findings.append(rug)

    return findings


def _tool_names(manifest: dict) -> str:
    return ", ".join(t["name"] for t in manifest.get("tools", [])) or "(none)"


def report(out_dir, *, resolve_dns: bool = True) -> list:
    """Text reporter. Prints a human-readable summary; returns findings."""
    manifest, profile = load(out_dir)
    findings = build_findings(manifest, profile, resolve_dns=resolve_dns)
    descs = _all_descriptions(manifest)
    claims_local = any(w in descs for w in ("local", "offline", "no network"))

    print(f"\n  target tools: {_tool_names(manifest)}")
    print(f"  resources:    {len(manifest.get('resources', []))}, "
          f"prompts: {len(manifest.get('prompts', []))}")
    print(f"  declared scope hints: {'mentions local/offline' if claims_local else 'none'}")
    print("  " + "-" * 56)
    if not findings:
        print("  no declared-vs-observed deviations detected")
    for sev, msg in sorted(findings, key=lambda x: x[0]):
        icon = "[!]" if sev == "HIGH" else "[i]"
        print(f"  {icon} {sev:4} {msg}")
    print()
    return findings


def report_json(out_dir, *, resolve_dns: bool = True) -> dict:
    """JSON reporter. Returns a serializable dict for CI/CD consumption."""
    manifest, profile = load(out_dir)
    findings = build_findings(manifest, profile, resolve_dns=resolve_dns)
    return {
        "server_cmd": manifest.get("server_cmd"),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "declared": {
            "tools": [t["name"] for t in manifest.get("tools", [])],
            "resources": [r["uri"] for r in manifest.get("resources", [])],
            "prompts": [p["name"] for p in manifest.get("prompts", [])],
        },
        "observed": profile,
        "findings": [{"severity": s, "message": m} for s, m in findings],
        "stats": manifest.get("_stats", {}),
    }


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OUT_DIR", "/tmp/mcp_behave_out")
    report(out)
