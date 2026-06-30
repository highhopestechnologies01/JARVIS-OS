# JARVIS OS — Runbook

Operational playbook for common failure scenarios. Keep this up to date.

**VPS:** 162.35.161.135  
**Code:** `/opt/jarvis-repo`  
**SSH:** `ssh -i ~/.ssh/jarvis_vps root@162.35.161.135`  
**Tunnel:** `nohup ssh -i ~/.ssh/jarvis_vps -o ServerAliveInterval=30 -L 3002:127.0.0.1:3002 -L 8001:127.0.0.1:8001 -N root@162.35.161.135 > /tmp/jarvis-tunnel.log 2>&1 &`

---

## 1. Dashboard not loading (localhost:3002)

**Symptoms:** Browser shows connection refused or blank page.

**Steps:**
```bash
# Check tunnel is running
curl -o /dev/null -w "%{http_code}" http://localhost:3002

# Restart tunnel if needed
pkill -f "ssh.*162.35.161.135"
nohup ssh -i ~/.ssh/jarvis_vps -o ServerAliveInterval=30 \
  -L 3002:127.0.0.1:3002 -L 8001:127.0.0.1:8001 \
  -N root@162.35.161.135 > /tmp/jarvis-tunnel.log 2>&1 &

# Check dashboard container on VPS
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 'docker ps | grep jarvis-dashboard'
docker restart jarvis-dashboard
```

---

## 2. Hermes not responding

**Symptoms:** Dashboard shows all panels as "offline". Scheduler panel shows "stopped".

**Steps:**
```bash
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  docker logs jarvis-hermes --tail 50
  docker restart jarvis-hermes
  sleep 5
  curl -s http://localhost:8001/api/v1/health/ready
'
```

**Common causes:**
- Database connection failed → check `jarvis-postgres` is healthy
- Import error in new code → check `docker logs jarvis-hermes` for tracebacks
- Memory limit → `docker stats jarvis-hermes`

---

## 3. Scheduler jobs not running

**Symptoms:** Health checks stopped, no briefings generated, Scheduler panel shows all jobs paused.

**Steps:**
```bash
# Check scheduler status
curl -s http://localhost:8001/api/v1/scheduler/jobs | python3 -m json.tool

# If jobs missing: restart Hermes (re-registers all jobs on startup)
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 'docker restart jarvis-hermes'

# Manually trigger a job
curl -X POST http://localhost:8001/api/v1/scheduler/trigger/health_check
```

---

## 4. PostgreSQL database issues

**Symptoms:** Hermes logs show SQLAlchemy errors. Memory/briefing panels show errors.

**Steps:**
```bash
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  # Check postgres status
  docker ps | grep jarvis-postgres
  docker exec jarvis-postgres pg_isready -U jarvis

  # Restart if needed
  docker restart jarvis-postgres
  sleep 5
  docker restart jarvis-hermes  # Hermes must reconnect after DB restart
'
```

**Restore from backup:**
```bash
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  # List available backups
  ls -lh /opt/backups/postgres/

  # Restore (replace BACKUP_FILE with actual filename)
  BACKUP_FILE="/opt/backups/postgres/jarvis_YYYY-MM-DD_HH-MM-SS.sql.gz"
  gunzip -c "$BACKUP_FILE" | docker exec -i jarvis-postgres psql -U jarvis jarvis
'
```

---

## 5. n8n automation workflows failing

**Symptoms:** AI Intelligence panel reports n8n failures. Automations not triggering.

**Steps:**
```bash
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  docker ps | grep jarvis-n8n
  docker logs jarvis-n8n --tail 30
  docker restart jarvis-n8n

  # Ensure n8n is on jarvis-net (required for Hermes health checks)
  docker network connect jarvis-net jarvis-n8n 2>/dev/null || echo "already connected"
'
```

---

## 6. GitHub Actions CI/CD failing

**Symptoms:** Push to main does not auto-deploy. GitHub Actions shows red X.

**Check:**
1. Go to `github.com/highhopestechnologies01/JARVIS-OS/actions`
2. Read the failed step output
3. Common causes:
   - `VPS_SSH_KEY` secret expired or missing → update in repo Settings → Secrets
   - VPS unreachable → check VPS is powered on
   - Docker build failure → check `docker logs` on VPS

**Manual fallback deploy:**
```bash
# Hermes hot-patch
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  cd /opt/jarvis-repo && git pull origin main
  find hermes/src -name "*.py" | while read f; do
    docker cp "$f" "jarvis-hermes:/app/${f#hermes/}"
  done
  docker restart jarvis-hermes
'

# Dashboard rebuild
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  cd /opt/jarvis-repo
  docker build -t jarvis-dashboard ./dashboard
  docker stop jarvis-dashboard && docker rm jarvis-dashboard
  docker run -d --name jarvis-dashboard --restart unless-stopped \
    --network jarvis-net \
    -e NEXT_PUBLIC_HERMES_URL=http://jarvis-hermes:8000 \
    -e NODE_ENV=production \
    -p 0.0.0.0:3002:3000 jarvis-dashboard
'
```

---

## 7. Daily briefing not generating

**Symptoms:** Briefing panel shows old date or "No briefing today".

**Steps:**
```bash
# Manually trigger briefing
curl -X POST http://localhost:8001/api/v1/scheduler/trigger/daily_briefing

# Check logs for errors
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 \
  'docker logs jarvis-hermes 2>&1 | grep -i "briefing\|planner\|error" | tail -20'
```

**Common causes:**
- ANTHROPIC_API_KEY missing/expired → check `.env` on VPS at `/opt/jarvis-repo/hermes/.env`
- Database full → check `docker exec jarvis-postgres df -h`

---

## 8. Full system restart sequence

Use after VPS reboot or major failure:

```bash
ssh -i ~/.ssh/jarvis_vps root@162.35.161.135 '
  cd /opt/jarvis-repo

  # Start infrastructure
  docker start jarvis-postgres jarvis-redis
  sleep 5

  # Start monitoring
  docker start jarvis-prometheus jarvis-grafana jarvis-node-exporter
  sleep 3

  # Start services
  docker start jarvis-hermes jarvis-dashboard jarvis-n8n
  sleep 5

  # Connect n8n to jarvis-net
  docker network connect jarvis-net jarvis-n8n 2>/dev/null || true

  # Verify
  docker ps --format "{{.Names}}: {{.Status}}" | grep jarvis
  curl -s http://localhost:8001/api/v1/health/ready
  curl -s -o /dev/null -w "Dashboard: %{http_code}\n" http://localhost:3002
'
```

---

## Key Locations

| Resource | Location |
|----------|----------|
| VPS code | `/opt/jarvis-repo` |
| DB backups | `/opt/backups/postgres/` |
| Backup log | `/opt/backups/postgres/backup.log` |
| Hermes env | `/opt/jarvis-repo/hermes/.env` |
| Hermes logs | `docker logs jarvis-hermes` |
| Tunnel log | `/tmp/jarvis-tunnel.log` |
| GitHub Actions | `github.com/highhopestechnologies01/JARVIS-OS/actions` |

---

## GitHub Actions Secrets Required

| Secret | Value |
|--------|-------|
| `VPS_SSH_KEY` | Contents of `~/.ssh/jarvis_vps` (private key) |
| `VPS_HOST` | `162.35.161.135` |
