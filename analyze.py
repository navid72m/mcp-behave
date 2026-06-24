"""Phase 0 analyzer: parse the strace log into a structured behavioral profile.
Pure observation -- lists what the server touched. No allowlist, no verdict yet."""
import re, sys, json, os

OPENAT = re.compile(r'openat\([^,]+,\s*"([^"]+)"')
# matches both: sin_addr=inet_addr("1.2.3.4")  and  sin6_addr=inet_pton(AF_INET6, "::1", ...)
CONNECT = re.compile(r'connect\(\d+,\s*\{sa_family=AF_INET6?,\s*'
                     r'sin6?_port=htons\((\d+)\),\s*sin6?_addr=inet_'
                     r'(?:addr|pton)\((?:[^,]+,\s*)?"([^"]+)"')
EXECVE = re.compile(r'execve\("([^"]+)"')

# Substrings that mark a path as runtime/library noise, not behaviorally interesting.
NOISE_SUBSTR = ("/site-packages/", "/__pycache__/", "/.venv/", "/usr/", "/lib/",
                "/lib64/", "/proc/", "/sys/", "/dev/", "/etc/ld.so", "dist-info",
                "pyvenv.cfg", "/tmp/probe_trace")
NOISE_SUFFIX = (".pyc", ".so", ".py._pth")
# Unix sockets / non-routable destinations we don't care about in the spike.
NET_NOISE = ("127.0.0.1", "::1", "0.0.0.0")

def interesting_file(path: str) -> bool:
    if any(s in path for s in NOISE_SUBSTR): return False
    if path.endswith(NOISE_SUFFIX): return False
    return True

def interesting_net(ip: str) -> bool:
    return not any(ip.startswith(n) for n in NET_NOISE)

def analyze(path: str) -> dict:
    files, nets, execs = set(), set(), set()
    with open(path, errors="replace") as f:
        for line in f:
            if (m := OPENAT.search(line)) and interesting_file(m.group(1)):
                files.add(m.group(1))
            if (m := CONNECT.search(line)) and interesting_net(m.group(2)):
                nets.add(f"{m.group(2)}:{m.group(1)}")
            if (m := EXECVE.search(line)):
                execs.add(m.group(1))
    return {"files_opened": sorted(files),
            "network_connects": sorted(nets),
            "subprocesses": sorted(execs)}

if __name__ == "__main__":
    tf = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRACE_FILE", "/tmp/probe_trace.log")
    print(json.dumps(analyze(tf), indent=2))
