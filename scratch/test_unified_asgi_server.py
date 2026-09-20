import os
import sys
import time
import subprocess
import requests
from pathlib import Path

# Ensure UTF-8 output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from core.models import TenantApiKey

TEST_PORT = 8006
TEST_HOST = "127.0.0.1"

print(f"==================================================")
print(f"🚀 TESTING UNIFIED ASGI SERVER (DJANGO + FASTMCP)")
print(f"==================================================")

valid_key_obj = TenantApiKey.objects.filter(is_active=True).first()
if not valid_key_obj:
    print("Error: No active TenantApiKey found!")
    sys.exit(1)

valid_key = valid_key_obj.key
print(f"Tenant: {valid_key_obj.tenant.name} | Key: {valid_key[:16]}...")

# 1. Start unified ASGI server on test port 8006
cmd = [
    sys.executable,
    str(BASE_DIR / "manage.py"),
    "run_asgi",
    "--host", TEST_HOST,
    "--port", str(TEST_PORT),
]

print(f"Starting ASGI server on http://{TEST_HOST}:{TEST_PORT}...")
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    cwd=str(BASE_DIR),
)

time.sleep(3)

try:
    base_url = f"http://{TEST_HOST}:{TEST_PORT}"

    # --- Test 1: Django Web Route (Landing) ---
    print("\n--- 1. Testing Django Web Route ---")
    resp_landing = requests.get(f"{base_url}/", timeout=5)
    print(f"GET / -> Status {resp_landing.status_code}")
    assert resp_landing.status_code == 200, f"Expected 200, got {resp_landing.status_code}"
    assert "ضيافة" in resp_landing.text or "مطاعم" in resp_landing.text or "SaaS" in resp_landing.text or "<html" in resp_landing.text
    print("✓ Django web application is serving correctly on the unified ASGI port!")

    # --- Test 2: Django Login Route ---
    print("\n--- 2. Testing Django Login Route ---")
    resp_login = requests.get(f"{base_url}/login/", timeout=5)
    print(f"GET /login/ -> Status {resp_login.status_code}")
    assert resp_login.status_code == 200
    print("✓ Django login page is accessible!")

    # --- Test 3: FastMCP SSE without key (Security) ---
    print("\n--- 3. Testing FastMCP SSE Security (Missing Key) ---")
    resp_mcp_nokey = requests.get(f"{base_url}/sse", timeout=5)
    print(f"GET /sse (no key) -> Status {resp_mcp_nokey.status_code} | Body: {resp_mcp_nokey.text.strip()}")
    assert resp_mcp_nokey.status_code == 401
    print("✓ Correctly blocked unauthenticated request with 401!")

    # --- Test 4: FastMCP SSE with invalid key ---
    print("\n--- 4. Testing FastMCP SSE Security (Invalid Key) ---")
    resp_mcp_badkey = requests.get(f"{base_url}/sse?access_key=ak_live_FAKE_BAD_KEY", timeout=5)
    print(f"GET /sse (bad key) -> Status {resp_mcp_badkey.status_code}")
    assert resp_mcp_badkey.status_code == 401
    print("✓ Correctly blocked invalid key with 401!")

    # --- Test 5: FastMCP SSE with valid key (Stream Connection) ---
    print("\n--- 5. Testing FastMCP SSE with Valid Key ---")
    sse_url = f"{base_url}/sse?access_key={valid_key}"
    print(f"Connecting to: {sse_url[:40]}...")

    with requests.get(sse_url, stream=True, timeout=5) as sse_stream:
        print(f"SSE Connection Status: {sse_stream.status_code}")
        assert sse_stream.status_code == 200
        content_type = sse_stream.headers.get("content-type", "")
        print(f"Content-Type: {content_type}")
        assert "text/event-stream" in content_type

        # Read the first event (endpoint event)
        endpoint_line = None
        for line in sse_stream.iter_lines(decode_unicode=True):
            if line:
                print(f"   [SSE Stream]: {line}")
                if "endpoint" in line or "/messages" in line:
                    endpoint_line = line
                    break

        assert endpoint_line is not None, "Did not receive endpoint event!"
        print("✓ FastMCP SSE stream opened successfully and sent message endpoint event!")

    print(f"\n==================================================")
    print(f"🎉 UNIFIED ASGI SERVER TESTS PASSED 100%!")
    print(f"==================================================")

finally:
    print("\nStopping test ASGI server...")
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
    print("Test server stopped.")
