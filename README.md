# mcp-behavioral-probe (Phase 0 spike)

A throwaway-quality spike that answers one question: **can we get accurate
behavioral ground truth out of a sandboxed MCP server?** If yes, the real tool
(behavioral auditing of MCP servers — "watch what it *does*, not what it
*says*") is worth building. If running this was miserable, it wasn't.

This is intentionally ~200 lines. It is not the product. It is the go/no-go gate.

## The idea in one contrast

`targets/leaky_server.py` and `targets/honest_server.py` expose a tool with the
**identical** name, description, and schema:

> `format_note` — "Formats a markdown note. Purely local text formatting."

A static scanner that reads tool descriptions sees two identical, harmless tools.
Run them under this probe and the difference is obvious:

| Target          | network egress      | sensitive file read        | findings |
|-----------------|---------------------|----------------------------|----------|
| `honest_server` | none                | none                       | **0**    |
| `leaky_server`  | `93.184.216.34:80`  | `~/.ssh/id_rsa` (a canary) | **2 HIGH** |

The honest server producing **zero** findings matters as much as the leaky one
tripping two — false positives are what would kill credibility.

## How it works

Three steps, one syscall tracer:

1. **observe** (`probe/probe.py`) — launches the MCP server wrapped in
   `strace -f`, does the MCP handshake over stdio, lists tools, and calls each
   with synthesized inputs. `strace` records `openat` / `connect` / `execve` /
   `sendto` to a log while passing stdio through transparently.
2. **profile** (`probe/analyze.py`) — parses the trace into a structured
   behavioral profile (files opened, network connects, subprocesses), filtering
   out library/runtime noise. Pure observation, no judgement.
3. **diff** (`probe/report.py`) — a *deliberately crude* declared-vs-observed
   comparison (a teaser of the real Phase 2 engine). Two rules only: network
   egress when a tool claims to be local, and reads of sensitive paths. Findings
   are framed as observations ("does X, undeclared"), never accusations.

Canaries (a fake `~/.ssh/id_rsa` and `~/.env`) are planted in `sandbox_home/`
and exposed as `$HOME`, so a server that reaches for secrets reveals itself.

## Run it

Docker (works on macOS too — `strace` is Linux-only):

```bash
docker build -t mcp-probe .
docker run --rm mcp-probe                          # default: the leaky target
docker run --rm mcp-probe python targets/honest_server.py   # the control
```

Locally on Linux:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./run.sh                              # leaky target (default)
./run.sh python targets/honest_server.py
```

Point it at a real server (anything that speaks MCP over stdio), e.g.:

```bash
./run.sh python -m mcp_server_fetch
```

## Known limits (deliberately out of scope for Phase 0)

- **Linux-only** ground truth via `strace`. eBPF/seccomp is the Phase 1+ upgrade.
- **No DNS resolution** — connects are reported as IP:port, not domains.
- **stdio transport only.** HTTP/SSE servers come in Phase 1.
- **Input synthesis is dumb** (one canary value per field). Phase 1 swaps in
  `hypothesis-jsonschema` for real coverage.
- **The diff is a toy.** The real declared-scope model (allowlists, taxonomy,
  rug-pull manifest hashing) is Phase 2.
- A server that only misbehaves on specific inputs, or after N calls, may not be
  triggered by a single synthesized call. Exercising state is later work.

## If the gate passed

Next is Phase 1: generalize `analyze.py` into a reusable profiler, add the HTTP
transport, and swap in schema-based input synthesis — then run it against ~5 real
servers and confirm the profiles are accurate.
