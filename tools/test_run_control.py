#!/usr/bin/env python3
"""Checks that need a running server, because they are about running things.

Everything here is about what happens to real processes, which the static
smoke test cannot see: that Cancel stops work rather than orphaning it, that
running one node on its own really does run one node, and that a command
which stops to ask a question can be answered from the terminal drawer, and
that a node marked "stop here" holds the run up until it is told to carry on.

Just run it. It starts a server of its own on a spare port, uses a throwaway
data directory so your own runs and stored results are left alone, and stops
the server again at the end:

    python3 tools/test_run_control.py

Give it a port number to use one that is already running instead, which is
what you want if you are watching the browser at the same time:

    python3 tools/test_run_control.py 8478
"""
import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    """A port nothing is using, so this never collides with your own server."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server():
    """Bring up a server of our own, on its own data directory.

    Its own directory because these tests run things: they would otherwise
    leave two dozen run folders in yours, and put their results in the store
    of finished work that your real graphs read from.
    """
    port = free_port()
    home = tempfile.mkdtemp(prefix="comfygmx-test-")
    log = open(os.path.join(home, "server.log"), "w")
    process = subprocess.Popen(
        [sys.executable, "-m", "comfygmx", "--data-dir", home,
         "serve", "--port", str(port), "--no-browser"],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)

    def stop():
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        shutil.rmtree(home, ignore_errors=True)

    atexit.register(stop)
    return port, process, home


def wait_for(port, process=None, seconds=30.0):
    """Wait until the server answers, and say so plainly if it never does."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            sys.exit("the server stopped before it was ready -- run it by hand to "
                     "see why:\n    %s -m comfygmx serve --port %d --no-browser"
                     % (sys.executable, port))
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/info" % port, timeout=2) as answer:
                answer.read()
                return
        except OSError:
            time.sleep(0.3)
    sys.exit("nothing answered on port %d after %.0f seconds. Is a server running "
             "there?" % (port, seconds))


OWN_SERVER = None
if len(sys.argv) > 1:
    PORT = int(sys.argv[1])
    print("using the server already running on port %d" % PORT)
    wait_for(PORT)
else:
    PORT, OWN_SERVER, HOME = start_server()
    print("started a server on port %d, data in %s" % (PORT, HOME))
    wait_for(PORT, OWN_SERVER)

def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode() or "{}")

def wait_settled(run_id, limit=40):
    for _ in range(int(limit / 0.5)):
        d = call(f"/api/runs/{run_id}")
        if d.get("status") in ("done", "error", "cancelled"):
            return d
        time.sleep(0.5)
    return call(f"/api/runs/{run_id}")

def alive(pattern):
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [p for p in out.stdout.split() if p]

fails = []
def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)

# ---------------------------------------------------------------- 1. stubborn
print("\n--- a script that ignores the polite stop ---")
graph = {"nodes": [{"id": "n1", "type": "util.shell", "params": {
    "script": "trap '' TERM INT; echo MARKER_STUBBORN; while true; do sleep 1; done",
    "output": "out.txt"}}], "links": []}
started = call("/api/run", {"graph": graph, "force": ["n1"], "label": "stub"})
run_id = started["run"]
time.sleep(3)
before = alive("MARKER_STUBBORN")
t0 = time.time()
first = call(f"/api/runs/{run_id}/cancel", {})
check("cancel replies at once", time.time() - t0 < 1.5, f"{time.time()-t0:.2f}s")
check("cancel says it worked", first.get("cancelled") is True, str(first))
check("first press is the polite one", first.get("hard") is False, str(first))
time.sleep(1.0)
second = call(f"/api/runs/{run_id}/cancel", {})
check("second press escalates", second.get("hard") is True, str(second))
detail = wait_settled(run_id, 30)
check("run ends up cancelled", detail.get("status") == "cancelled", detail.get("status"))
time.sleep(1.0)
after = alive("MARKER_STUBBORN")
check("nothing left running", not after, f"before={before} after={after}")

# ------------------------------------------------------- 2. run just this node
print("\n--- run just one node ---")
# A different script every time, so an earlier test run's stored answer
# cannot make the "never finished" case pass by accident.
NONCE = str(int(time.time()))
chain = {"nodes": [
    {"id": "a", "type": "util.shell", "params": {"script": f"# {NONCE}\necho FIRST > out.txt; sleep 2", "output": "out.txt"}},
    {"id": "b", "type": "util.shell", "params": {"script": "cat $IN1 > merged.txt; echo SECOND >> merged.txt", "output": "merged.txt"}},
], "links": [{"from_node": "a", "from_port": "out", "to_node": "b", "to_port": "in1"}]}

lonely = call("/api/run", {"graph": chain, "only": ["b"], "isolate": True})
check("isolated run refuses when the input was never made",
      "error" in lonely and "never finished" in lonely["error"], str(lonely)[:200])

full = call("/api/run", {"graph": chain, "label": "chain"})
d = wait_settled(full["run"])
check("the chain runs", d.get("status") == "done", d.get("status"))

iso = call("/api/run", {"graph": chain, "only": ["b"], "force": ["b"], "isolate": True})
check("isolated run lists only that node", iso.get("order") == ["b"], str(iso.get("order")))
d = wait_settled(iso["run"])
check("isolated run finishes", d.get("status") == "done", d.get("status"))
node_b = d["nodes"]["b"]
out = os.path.join(node_b["workdir"], "merged.txt")
text = open(out).read() if os.path.exists(out) else "(missing)"
check("it really used the earlier node's file", "FIRST" in text and "SECOND" in text, repr(text))

# --------------------------------------------------------------- 3. answering
print("\n--- answering a command that asks a question ---")
ask = {"nodes": [{"id": "q", "type": "util.shell", "params": {
    "script": "echo 'what is your name?'; read NAME; echo \"hello $NAME\" > out.txt; cat out.txt",
    "output": "out.txt"}}], "links": []}
started = call("/api/run", {"graph": ask, "force": ["q"], "label": "ask"})
run_id = started["run"]
waited = False
for _ in range(20):
    time.sleep(0.5)
    d = call(f"/api/runs/{run_id}?log=1")
    log = "\n".join(d["nodes"]["q"].get("log") or [])
    if "waiting for an answer" in log:
        waited = True
        break
check("it notices the command is waiting", waited)
sent = call(f"/api/runs/{run_id}/input", {"node": "q", "text": "Can"})
check("the answer is delivered", sent.get("sent") is True, str(sent))
d = wait_settled(run_id, 20)
check("the run then finishes", d.get("status") == "done", d.get("status"))
out = os.path.join(d["nodes"]["q"]["workdir"], "out.txt")
text = open(out).read().strip() if os.path.exists(out) else "(missing)"
check("the command got what was typed", text == "hello Can", repr(text))


print("\n--- stopping at a node and carrying on ---")
nonce = str(int(time.time())) + "-pause"
graph = {"nodes": [
    {"id": "a", "type": "util.shell",
     "params": {"script": f"# {nonce}\necho FIRST > out.txt", "output": "out.txt"}},
    {"id": "b", "type": "util.shell", "pause": True,
     "params": {"script": "echo ORIGINAL > answer.txt", "output": "answer.txt"}},
], "links": [{"from_node": "a", "from_port": "out", "to_node": "b", "to_port": "in1"}]}

started = call("/api/run", {"graph": graph, "label": "pause"})
run_id = started["run"]
held = None
for _ in range(40):
    time.sleep(0.25)
    d = call(f"/api/runs/{run_id}")
    if d["nodes"]["b"]["status"] == "paused":
        held = d
        break
check("the run stops at the marked node", held is not None)
check("everything before it finished",
      held and held["nodes"]["a"]["status"] in ("done", "cached"),
      held["nodes"]["a"]["status"] if held else "")
check("the run has not finished", held and held["status"] == "running",
      held["status"] if held else "")

# change what the held node does, exactly as the editor would
changed = json.loads(json.dumps(graph))
changed["nodes"][1]["params"]["script"] = "echo CHANGED > answer.txt"
out = call(f"/api/runs/{run_id}/resume", {"graph": changed})
check("it carries on when told", out.get("resumed") is True, str(out))
check("it picked up the new settings", "current settings" in (out.get("note") or ""),
      str(out.get("note")))

final = None
for _ in range(40):
    time.sleep(0.25)
    d = call(f"/api/runs/{run_id}")
    if d["status"] in ("done", "error", "cancelled"):
        final = d
        break
check("the run then finishes", final and final["status"] == "done",
      final["status"] if final else "")
if final:
    import os
    text = ""
    p = os.path.join(final["nodes"]["b"]["workdir"], "answer.txt")
    if os.path.exists(p):
        text = open(p).read().strip()
    check("it used the value changed while it waited", text == "CHANGED", repr(text))

# and a rewired graph is refused rather than used
started = call("/api/run", {"graph": graph, "force": ["a", "b"], "label": "pause2"})
run_id = started["run"]
for _ in range(40):
    time.sleep(0.25)
    if call(f"/api/runs/{run_id}")["nodes"]["b"]["status"] == "paused":
        break
rewired = json.loads(json.dumps(graph))
rewired["nodes"].append({"id": "c", "type": "util.shell",
                         "params": {"script": "true", "output": "o.txt"}})
out = call(f"/api/runs/{run_id}/resume", {"graph": rewired})
check("a rewired graph is refused, and it carries on with the old one",
      out.get("resumed") is True and "changed shape" in (out.get("note") or ""),
      str(out.get("note"))[:70])
for _ in range(40):
    time.sleep(0.25)
    if call(f"/api/runs/{run_id}")["status"] in ("done", "error", "cancelled"):
        break

# cancelling a held run must not leave it stuck
started = call("/api/run", {"graph": graph, "force": ["a", "b"], "label": "pause3"})
run_id = started["run"]
for _ in range(40):
    time.sleep(0.25)
    if call(f"/api/runs/{run_id}")["nodes"]["b"]["status"] == "paused":
        break
call(f"/api/runs/{run_id}/cancel", {})
settled = None
for _ in range(40):
    time.sleep(0.25)
    d = call(f"/api/runs/{run_id}")
    if d["status"] in ("done", "error", "cancelled"):
        settled = d
        break
check("Cancel releases a held run", settled and settled["status"] == "cancelled",
      settled["status"] if settled else "stuck")

print("\n" + ("ALL PASSED" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
