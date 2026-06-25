"""Run an MCP server under strace, exercise every capability (tools, resources,
prompts) with synthesized inputs, and record both the server's self-declared
manifest and the raw syscall trace of what it actually did.

No judgements here -- that's report.py."""
import asyncio, hashlib, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT_DIR    = os.environ.get("OUT_DIR", "/tmp/mcp_behave_out")
TRACE_FILE = os.path.join(OUT_DIR, "trace.log")
MANIFEST   = os.path.join(OUT_DIR, "manifest.json")
# openat: file reads. connect: outbound network. execve: subprocesses.
# (sendto was traced before but never parsed -- removed to keep the log lean.)
SYSCALLS   = "openat,connect,execve"
# Per-call timeout. A hanging tool used to hang the whole probe.
DEFAULT_CALL_TIMEOUT = float(os.environ.get("MCP_BEHAVE_CALL_TIMEOUT", "15"))


def synth_args(schema: dict) -> dict:
    """Synthesize ONE plausible-and-valid input per field from a JSON schema.

    Strategy (first match wins, per property):
      1. JSON Schema `format` (uri, email, ipv4, date-time, ...) -- standards-based.
      2. Key-name heuristics (url, path, query, ...) -- pragmatic; many MCP tools
         don't set `format` but name fields obviously.
      3. Type-based default -- safety net.

    Goal is NOT coverage or fuzzing -- just inputs realistic enough that the tool
    actually runs (e.g. a `url` field gets a real URL) so we can observe behavior.
    A constrained `enum` is honored when present (first value).
    """
    # RFC 2606 / 5737 / 3849 reserved ranges -- keeps the probe's own traffic honest.
    FORMAT_VALUES = {
        "uri": "http://example.com/",
        "url": "http://example.com/",
        "iri": "http://example.com/",
        "email": "probe@example.com",
        "idn-email": "probe@example.com",
        "hostname": "example.com",
        "ipv4": "192.0.2.1",
        "ipv6": "2001:db8::1",
        "date-time": "2026-01-01T00:00:00Z",
        "date": "2026-01-01",
        "time": "00:00:00Z",
        "uuid": "00000000-0000-0000-0000-000000000000",
    }
    KEYNAME_HINTS = (
        ("url", "http://example.com/"),
        ("uri", "http://example.com/"),
        ("link", "http://example.com/"),
        ("href", "http://example.com/"),
        ("endpoint", "http://example.com/"),
        ("path", "/tmp/probe-canary.txt"),
        ("file", "/tmp/probe-canary.txt"),
        ("dir", "/tmp"),
        ("email", "probe@example.com"),
        ("host", "example.com"),
        ("query", "probe-canary"),
        ("search", "probe-canary"),
        ("text", "probe-canary"),
        ("name", "probe-canary"),
    )
    TYPE_DEFAULTS = {"string": "canary-input", "integer": 1, "number": 1.0,
                     "boolean": True, "array": [], "object": {}}

    def synth_one(key: str, spec: dict):
        spec = spec or {}
        if isinstance(spec.get("enum"), list) and spec["enum"]:
            return spec["enum"][0]
        fmt = spec.get("format")
        if fmt in FORMAT_VALUES:
            return FORMAT_VALUES[fmt]
        if spec.get("type", "string") == "string":
            k = key.lower()
            for needle, value in KEYNAME_HINTS:
                if needle in k:
                    return value
        return TYPE_DEFAULTS.get(spec.get("type", "string"), "canary-input")

    return {key: synth_one(key, spec)
            for key, spec in (schema or {}).get("properties", {}).items()}


async def _list_safely(coro, label: str):
    """Some servers don't implement resources/ or prompts/. Tolerate that."""
    try:
        return await coro
    except Exception as exc:
        print(f"[probe]   {label} not supported: {exc}")
        return None


async def _call_with_timeout(coro, label: str, timeout: float):
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return True
    except asyncio.TimeoutError:
        print(f"[probe]   {label} timed out after {timeout}s")
        return False
    except Exception as exc:
        print(f"[probe]   {label} raised: {exc}")
        return False


async def _exercise(session: ClientSession, call_timeout: float):
    """Shared logic: discover + exercise tools, resources, prompts on a live session."""
    tools_meta, resources_meta, prompts_meta = [], [], []
    stats = {"tools": {"called": 0, "ok": 0}, "resources": {"called": 0, "ok": 0},
             "prompts": {"called": 0, "ok": 0}}

    await session.initialize()

    tools_result = await _list_safely(session.list_tools(), "tools/list")
    tools = getattr(tools_result, "tools", []) if tools_result else []
    tools_meta = [{"name": t.name, "description": t.description,
                   "inputSchema": t.inputSchema} for t in tools]
    print(f"[probe] discovered {len(tools)} tool(s)")
    for t in tools:
        args = synth_args(t.inputSchema)
        print(f"[probe] calling tool {t.name}({json.dumps(args)})")
        stats["tools"]["called"] += 1
        if await _call_with_timeout(
            session.call_tool(t.name, args), f"tool {t.name}", call_timeout):
            stats["tools"]["ok"] += 1

    res_result = await _list_safely(session.list_resources(), "resources/list")
    resources = getattr(res_result, "resources", []) if res_result else []
    resources_meta = [{"uri": str(r.uri), "name": r.name,
                       "description": r.description,
                       "mimeType": r.mimeType} for r in resources]
    print(f"[probe] discovered {len(resources)} resource(s)")
    for r in resources:
        print(f"[probe] reading resource {r.uri}")
        stats["resources"]["called"] += 1
        if await _call_with_timeout(
            session.read_resource(r.uri), f"resource {r.uri}", call_timeout):
            stats["resources"]["ok"] += 1

    pr_result = await _list_safely(session.list_prompts(), "prompts/list")
    prompts = getattr(pr_result, "prompts", []) if pr_result else []
    prompts_meta = [{"name": p.name, "description": p.description,
                     "arguments": [{"name": a.name, "required": a.required}
                                   for a in (p.arguments or [])]}
                    for p in prompts]
    print(f"[probe] discovered {len(prompts)} prompt(s)")
    for p in prompts:
        args = {a.name: "canary-input" for a in (p.arguments or [])
                if a.required}
        print(f"[probe] getting prompt {p.name}({json.dumps(args)})")
        stats["prompts"]["called"] += 1
        if await _call_with_timeout(
            session.get_prompt(p.name, args), f"prompt {p.name}", call_timeout):
            stats["prompts"]["ok"] += 1

    return tools_meta, resources_meta, prompts_meta, stats


def _write_manifest(server_cmd, tools_meta, resources_meta, prompts_meta, stats,
                    *, transport: str, syscalls_available: bool):
    manifest = {
        "server_cmd": list(server_cmd) if server_cmd else None,
        "transport": transport,
        "syscalls_available": syscalls_available,
        "tools": tools_meta,
        "resources": resources_meta,
        "prompts": prompts_meta,
        "manifest_sha256": hashlib.sha256(
            json.dumps({"tools": tools_meta, "resources": resources_meta,
                        "prompts": prompts_meta}, sort_keys=True).encode()
        ).hexdigest(),
        "_stats": stats,
    }
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[probe] manifest -> {MANIFEST}")
    if syscalls_available:
        print(f"[probe] trace    -> {TRACE_FILE}")


async def run(server_cmd: list[str], call_timeout: float = DEFAULT_CALL_TIMEOUT):
    """Stdio transport: wrap the server in strace and connect via stdio."""
    os.makedirs(OUT_DIR, exist_ok=True)
    strace_cmd = ["strace", "-f", "-qq", "-e", f"trace={SYSCALLS}",
                  "-o", TRACE_FILE, *server_cmd]
    params = StdioServerParameters(command=strace_cmd[0], args=strace_cmd[1:],
                                   env={**os.environ})

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            tools_meta, resources_meta, prompts_meta, stats = await _exercise(
                session, call_timeout)
    _write_manifest(server_cmd, tools_meta, resources_meta, prompts_meta, stats,
                    transport="stdio", syscalls_available=True)


async def run_remote(url: str, *, transport: str,
                     call_timeout: float = DEFAULT_CALL_TIMEOUT):
    """Remote transport (sse/streamable-http): connect to an already-running
    server. Syscall ground-truth is NOT available -- we can only verify the
    declared surface and detect rug-pulls. analyze.py is a no-op in this mode."""
    os.makedirs(OUT_DIR, exist_ok=True)
    # Write an empty trace so analyze() doesn't crash.
    open(TRACE_FILE, "w").close()

    if transport == "sse":
        from mcp.client.sse import sse_client
        ctx = sse_client(url)
    elif transport == "streamable-http":
        from mcp.client.streamable_http import streamablehttp_client
        ctx = streamablehttp_client(url)
    else:
        raise ValueError(f"unknown remote transport: {transport}")

    async with ctx as conn:
        # streamable_http returns (read, write, _); sse returns (read, write)
        read, write = conn[0], conn[1]
        async with ClientSession(read, write) as session:
            tools_meta, resources_meta, prompts_meta, stats = await _exercise(
                session, call_timeout)
    _write_manifest([url], tools_meta, resources_meta, prompts_meta, stats,
                    transport=transport, syscalls_available=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: probe.py <server-command> [args...]"); sys.exit(2)
    asyncio.run(run(sys.argv[1:]))
