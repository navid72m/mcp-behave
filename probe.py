"""Phase 0 probe: run a stdio MCP server under strace, exercise every tool with
synthesized inputs, and record (a) the server's self-declared manifest and
(b) the raw syscall trace of what it actually did.

This answers the only Phase 0 question: can we get accurate behavioral ground
truth out of an MCP server at all? It makes NO judgements -- see report.py."""
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT_DIR   = os.environ.get("OUT_DIR", "/tmp/probe_out")
TRACE_FILE = os.path.join(OUT_DIR, "trace.log")
MANIFEST   = os.path.join(OUT_DIR, "manifest.json")
SYSCALLS   = "openat,connect,execve,sendto"

def synth_args(schema: dict) -> dict:
    """Dumb input synthesis from a JSON schema. Good enough for the spike;
    Phase 1 replaces this with hypothesis-jsonschema."""
    out = {}
    for key, spec in (schema or {}).get("properties", {}).items():
        out[key] = {"string": "canary-input", "integer": 1, "number": 1.0,
                    "boolean": True, "array": [], "object": {}}.get(
                    spec.get("type", "string"), "canary-input")
    return out

async def run(server_cmd: list[str]):
    os.makedirs(OUT_DIR, exist_ok=True)
    # Wrap the real server in strace. The MCP SDK speaks stdio to strace, which
    # passes it through transparently while logging syscalls to TRACE_FILE.
    strace_cmd = ["strace", "-f", "-qq", "-e", f"trace={SYSCALLS}",
                  "-o", TRACE_FILE, *server_cmd]
    params = StdioServerParameters(command=strace_cmd[0], args=strace_cmd[1:],
                                   env={**os.environ})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            manifest = [{"name": t.name, "description": t.description,
                         "inputSchema": t.inputSchema} for t in tools]
            with open(MANIFEST, "w") as f:
                json.dump(manifest, f, indent=2)
            print(f"[probe] discovered {len(tools)} tool(s): "
                  f"{', '.join(t.name for t in tools)}")
            for t in tools:
                args = synth_args(t.inputSchema)
                print(f"[probe] calling {t.name}({json.dumps(args)})")
                try:
                    await session.call_tool(t.name, args)
                except Exception as e:
                    print(f"[probe]   call raised: {e}")
    print(f"[probe] manifest -> {MANIFEST}")
    print(f"[probe] trace    -> {TRACE_FILE}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: probe.py <server-command> [args...]"); sys.exit(2)
    asyncio.run(run(sys.argv[1:]))
