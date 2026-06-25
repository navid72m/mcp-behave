# Roadmap

Current state (v0.1.x): strace-based stdio probing, manifest hashing for
rug-pull detection, basic remote transports (manifest-only).

## Near-term (next minor)

- **Schema-coverage input synthesis** — drop in `hypothesis-jsonschema` and
  call each tool N times with diverse inputs, not once with a canary value.
  Catches servers that misbehave only on specific input shapes.
- **AF_UNIX egress detection** — currently a server exfiltrating over a unix
  domain socket slips past `analyze.py`. Add the matching socket family.
- **Allowlist mode** — let users declare expected files/hosts in a config
  file; only deviations from the allowlist surface as findings. Turns
  `mcp-behave` from "spike" into "policy enforcement gate."

## Mid-term (the moat)

- **eBPF/seccomp backend** — the strace dependency is the project's biggest
  limitation: Linux-only, requires `SYS_PTRACE`, single-host. An eBPF-based
  syscall capture (e.g. via `bcc`, `bpftrace`, or a Rust agent using `aya`)
  would: (a) run on macOS via Lima/Colima or a kernel-mode equivalent,
  (b) capture more accurately at higher concurrency, (c) eventually let us
  attach to *already-running* MCP servers rather than spawning them. This is
  weeks of work and a separate binary, not a flag — but it's what turns this
  from a developer toy into something a CI pipeline at a real company runs
  on every PR.
- **Full HTTP/SSE behavior verification** — for remote servers we currently
  only collect the declared surface. With an eBPF agent running on the host
  *where the server lives*, behavioral verification becomes possible.
- **Per-tool taxonomy & policy** — instead of one global allowlist, classify
  tools by purpose (read-local, fetch-remote, mutate-fs, exec-process) and
  apply per-class expectations.

## Why these, in this order

The Phase 0 spike (now shipped as 0.1.0) proved the technical premise: you
*can* get accurate behavioral ground truth from an MCP server. The roadmap
above ranks improvements by leverage:

1. **Input synthesis** is the cheapest way to find more bugs in the same servers.
2. **AF_UNIX** closes a real evasion gap.
3. **Allowlist mode** is what makes this a product, not a one-off audit.
4. **eBPF** is the platform bet — expensive, but it's the only path to
   "watches MCP servers everywhere your agent runs them."

eBPF is intentionally not v0.x scope. Shipping a half-baked eBPF probe would
poison the project's reputation faster than not having one.
