#!/usr/bin/env python3
"""
JARVIS OS Doctor — connects to VPS via SSH and fixes/verifies all services.
Run with: python3 scripts/jarvis-doctor.py
"""

import subprocess, sys, time

HOST = "162.35.161.135"
USER = "root"
PASS = "Apple258@in"
SECRET_KEY = "hrjwWZ0Nn5n9rGzYUI3DO5LnTCr2zqdvcXRwyX0vyZk"

def ssh(cmd, timeout=60):
    """Run a command on the VPS via SSH."""
    result = subprocess.run(
        ["sshpass", "-p", PASS, "ssh",
         "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10",
         f"{USER}@{HOST}", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip()

def step(msg):
    print(f"\n{'='*50}")
    print(f"  {msg}")
    print('='*50)

def check_sshpass():
    r = subprocess.run(["which", "sshpass"], capture_output=True, text=True)
    if r.returncode != 0:
        print("Installing sshpass...")
        subprocess.run(["brew", "install", "hudochenkov/sshpass/sshpass"], check=True)

# ── Main ───────────────────────────────────────────────────────
check_sshpass()

step("1/5 — Checking .env file on VPS")
out, _ = ssh("grep -c 'SECRET_KEY=' /opt/jarvis-os/.env")
count = int(out) if out.isdigit() else 0
print(f"  SECRET_KEY lines found: {count}")

if count == 0:
    print("  ⚡ Adding SECRET_KEY...")
    out, err = ssh(f'echo "SECRET_KEY={SECRET_KEY}" >> /opt/jarvis-os/.env && echo "ENV=production" >> /opt/jarvis-os/.env && echo "LOG_LEVEL=INFO" >> /opt/jarvis-os/.env')
else:
    # Check if the correct one (without HERMES_ prefix) exists
    out2, _ = ssh("grep '^SECRET_KEY=' /opt/jarvis-os/.env | head -1")
    if not out2:
        print("  ⚡ Only HERMES_SECRET_KEY found — adding correct SECRET_KEY...")
        out, err = ssh(f'echo "SECRET_KEY={SECRET_KEY}" >> /opt/jarvis-os/.env')

out, _ = ssh("grep '^SECRET_KEY=' /opt/jarvis-os/.env")
print(f"  ✓ {out}")

step("2/5 — Restarting Hermes with correct env")
out, err = ssh(
    "docker rm -f jarvis-hermes 2>/dev/null; "
    "docker run -d --name jarvis-hermes --restart unless-stopped "
    "--network jarvis-net --env-file /opt/jarvis-os/.env "
    "-p 0.0.0.0:8001:8000 jarvis-hermes"
)
print(f"  Container ID: {out[:12] if out else 'ERROR'}")
if err and 'Error' in err:
    print(f"  ⚠ {err}")

print("  Waiting 10s for startup...")
time.sleep(10)

step("3/5 — Verifying Hermes health")
out, err = ssh("curl -s http://localhost:8001/health")
if '"status": "ok"' in out or '"status":"ok"' in out:
    print(f"  ✓ Hermes HEALTHY: {out}")
else:
    print(f"  ✗ Hermes unhealthy. Logs:")
    out2, _ = ssh("docker logs jarvis-hermes --tail 15")
    print(out2)

step("4/5 — Checking all containers")
out, _ = ssh('docker ps --format "{{.Names}}\\t{{.Status}}" | sort')
for line in out.splitlines():
    icon = "✓" if "healthy" in line or "Up" in line else "✗"
    print(f"  {icon} {line}")

step("5/5 — Dashboard connectivity check")
out, _ = ssh("curl -s -o /dev/null -w '%{http_code}' http://localhost:3002")
print(f"  Dashboard HTTP status: {out}")
out2, _ = ssh("docker exec jarvis-dashboard curl -s http://jarvis-hermes:8000/health 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[\"status\"])' 2>/dev/null || echo 'unreachable'")
print(f"  Dashboard → Hermes: {out2}")

print("\n" + "="*50)
print("  JARVIS OS DOCTOR COMPLETE")
print("  Open http://localhost:3002 in your browser")
print("="*50 + "\n")
