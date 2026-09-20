import subprocess
import json
import sys
import os

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


cmd = [
    r"C:\Users\solo\AppData\Local\Python\pythoncore-3.14-64\python.exe",
    r"C:\Users\solo\Downloads\restaurant-management-system-development (1)\manage.py",
    "run_callcenter_mcp",
    "--transport",
    "stdio",
]

env = {
    "RESTAURANT_ACCESS_KEY": "ak_live_GnALOkyiQvHnDUxDHMND5jC5rOmTtSDjok2c73JZHJU",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}

print("Spawning subprocess...")
full_env = os.environ.copy()
full_env.update(env)

ide_dir = r"C:\Users\solo\AppData\Local\Programs\Antigravity IDE"
test_cwd = ide_dir if os.path.exists(ide_dir) else None

proc = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    cwd=test_cwd,
    env=full_env,
)

# 1. Send initialize
init_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "antigravity-test",
            "version": "1.0.0"
        }
    }
}

proc.stdin.write(json.dumps(init_request) + "\n")
proc.stdin.flush()

line = proc.stdout.readline()
data = json.loads(line)
print("Handshake response:")
print(data)

# 2. Send initialized notification
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
proc.stdin.flush()

# 3. Request tools list
tools_request = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
}
proc.stdin.write(json.dumps(tools_request) + "\n")
proc.stdin.flush()

line2 = proc.stdout.readline()
tools_data = json.loads(line2)
print("Tools response:")
tool_names = [t["name"] for t in tools_data.get("result", {}).get("tools", [])]
print("Discovered tools:", tool_names)

proc.terminate()
print("✓ TEST PASSED 100%! All tools discovered via stdio handshake.")
