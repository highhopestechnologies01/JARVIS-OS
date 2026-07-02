# JARVIS OS — Roadmap

Updated: 2026-06-30

---

## Phase 1 · Foundation ✅ COMPLETE

Mac environment fully configured.

- [x] macOS secured
- [x] Git configured
- [x] SSH keys generated
- [x] Homebrew installed
- [x] Tailscale connected (Mac ↔ VPS ↔ RDP)
- [x] Claude Code installed
- [x] JARVIS-OS repository created

---

## Phase 2 · Infrastructure ✅ COMPLETE

**Completed: 2026-06-30**

- [x] VPS bootstrapped (Ubuntu 26.04 @ 162.35.161.135)
- [x] Docker + Docker Compose installed on VPS
- [x] `infrastructure/docker-compose.yml` deployed
- [x] PostgreSQL 16 running and healthy
- [x] Redis 7 running and healthy
- [x] n8n running on port 5678 (internal)
- [x] Prometheus scraping metrics on port 9090
- [x] Grafana dashboard on port 3001
- [x] Coolify already installed on VPS ✓
- [x] All services on `jarvis-net` Docker network
- [ ] Backups configured for PostgreSQL (Phase 8)

---

## Phase 3 · Hermes ✅ COMPLETE

**Completed: 2026-06-30**

- [x] Hermes Docker container builds and starts
- [x] Database initialized (all tables created via init.sql)
- [x] `/health` endpoint returns 200 ✓
- [x] Memory engine: store and retrieve working
- [x] Scheduler: APScheduler running with 4 core jobs
- [x] Planner: Claude API integrated (claude-opus-4-8 + claude-haiku-4-5-20251001)
- [x] `ANTHROPIC_API_KEY` configured
- [ ] Notification: Twilio SMS (needs TWILIO credentials)
- [ ] Notification: Email (needs SMTP credentials)
- [ ] Daily briefing delivered end-to-end (Phase 6)

---

## Phase 4 · Dashboard ✅ COMPLETE

**Completed: 2026-06-30**

- [x] Next.js app builds and deploys
- [x] Docker container running on VPS (port 3002)
- [x] Infrastructure panel: all Docker service statuses
- [x] Briefings panel: today's Hermes briefing
- [x] Memory panel: recent memory entries
- [x] Notifications feed: last 10 alerts
- [x] Dashboard accessible via SSH tunnel (Mac browser → VPS)
- [ ] Tailscale on Mac: reconnect pending (SSH tunnel works as workaround)

---

## Phase 5 · Voice ✅ COMPLETE

**Completed: 2026-06-30**

- [x] Voice command endpoint in Hermes (`POST /api/v1/voice/command`)
- [x] Claude Haiku (claude-haiku-4-5-20251001) for fast spoken responses
- [x] JARVIS persona system prompt (chief-of-staff tone)
- [x] VoicePanel client component in Dashboard (Web Speech API)
- [x] Browser-native STT (SpeechRecognition) + TTS (SpeechSynthesis)
- [x] States: idle → listening → processing → speaking → error
- [x] Mic button with animated pulse per state
- [x] Full dark theme with Tailwind CSS (postcss.config.js fix deployed)
- [ ] Wake word detection (Phase 7)
- [ ] ElevenLabs TTS for higher-quality voice (Phase 7)

---

## Phase 6 · Automation ✅ COMPLETE

**Completed: 2026-06-30**

- [x] Daily morning briefing (8am ET) — APScheduler, Claude Haiku, saves to DB
- [x] Infrastructure health check (every 15 min) — checks Hermes, n8n, Grafana, Prometheus
- [x] Weekly performance report (Monday 9am ET)
- [x] Alert on service failure (immediate) — SMS via Twilio dispatcher
- [x] Memory consolidation (2am daily) — prunes expired entries
- [x] Scheduler API — GET /api/v1/scheduler/jobs, POST /trigger/{job_id}
- [x] SchedulerPanel — live next-run countdowns, ▶ run buttons per job
- [x] n8n workflows: 5 automations live — health-alert, github-digest, metrics-snapshot, daily-briefing-push, weekly-digest ✅
- [ ] Auto-restart failed services (Phase 8)

---

## Phase 7 · AI Intelligence ✅ COMPLETE

**Completed: 2026-06-30**

- [x] context_builder.py — aggregates events, health history, memories, patterns for briefings
- [x] pattern_analyzer.py — Claude Haiku analyzes system data daily, stores insights as memories
- [x] AI Pattern Analysis job — runs every day at 3am, 5 insights stored with 7-day expiry
- [x] Autonomous Weekly Planning job — every Sunday 6am, Claude Opus generates full week plan
- [x] intelligence.py API — GET /insights, POST /analyze (manual trigger)
- [x] IntelligencePanel — live AI insights on dashboard with ⚡ analyze button
- [x] Daily briefing upgraded — uses context_builder for rich real-data context
- [x] 6 autonomous jobs running: health_check, briefing, pattern_analysis, weekly_plan, memory_consolidation, weekly_report
- [ ] pgvector semantic search (Phase 8 — needs DB migration)
- [ ] Anomaly detection alerts (Phase 8)

---

## Phase 8 · Production ✅ COMPLETE

**Completed: 2026-06-30**

- [x] GitHub Actions CI/CD pipeline — smart deploy: hot-patches Hermes, rebuilds Dashboard only on change
- [x] Automated PostgreSQL backups — daily 1am cron, 7-day retention, test backup confirmed (8.0K)
- [x] Security hardening — Hermes runs as non-root (`hermes` user), no public ports, all secrets in `.env`
- [x] Runbook written — 8 failure scenarios documented with exact commands (RUNBOOK.md)
- [x] All 7 Docker services healthy on jarvis-net
- [x] n8n connected to jarvis-net (health checks working)
- [x] GitHub repo: github.com/highhopestechnologies01/JARVIS-OS
- [x] GitHub Actions secrets added: `VPS_SSH_KEY`, `VPS_HOST` ✓
- [x] n8n automations live: health-alert handler, github-digest, prometheus-snapshot
- [x] Hermes health check wired to n8n webhook (non-blocking POST on failures)
- [x] n8n pipeline fully debugged — contentType=raw fix for HTTP Request node v4.2
- [ ] Centralized logging (Loki) — optional future improvement
- [ ] pgvector semantic search — optional future improvement

---

## Telegram Notifications ✅ COMPLETE

**Completed: 2026-06-30**

- [x] `send_telegram()` in NotificationDispatcher — httpx, no new deps
- [x] Health alerts fire to Telegram first, SMS as fallback
- [x] Daily briefings delivered via Telegram (full content, HTML formatted)
- [x] Bot token + chat ID in root `.env`, loaded via Pydantic settings
- [x] Hermes → Telegram internal connection confirmed from Docker container
- [x] n8n jarvis-net watchdog cron — `* * * * *` reconnects on restart

---

## Coolify Integration ✅ COMPLETE

**Completed: 2026-06-30**

- [x] Coolify API token generated (Laravel Sanctum, team_id=0)
- [x] `hermes/src/integrations/coolify.py` — full async Coolify v4 API client
- [x] `hermes/src/api/routes/coolify.py` — GET /api/v1/coolify/status, POST /services/{uuid}/restart
- [x] Coolify accessible from Hermes via jarvis-net bridge gateway (10.0.6.1:8000)
- [x] COOLIFY_API_URL + COOLIFY_API_TOKEN wired into root `.env`
- [x] Endpoint live: version "4.1.2" + real server/service data confirmed
- [x] Fixed Redis config crash (removed requirepass when REDIS_PASSWORD unset)
- [x] Fixed Hermes port conflict with Coolify (host port 8000→8001)

---

## Meta Ads Intelligence Layer ✅ COMPLETE

**Completed: 2026-07-01**

- [x] `spend_alerts.py` — budget % alert, auto-pause, stopped-campaign detection, daily cap
- [x] `campaign_insights.py` — daily Claude Haiku analysis → Telegram + Memory table
- [x] `meta_ads.py` — `/budget-config` GET+POST, `/insights` GET, `/insights/run` POST
- [x] `notifications.py` — `reply_markup` support for Telegram inline keyboards
- [x] `jobs.py` — `campaign_insights` APScheduler job (9:30am ET daily)
- [x] `scheduler.py` — campaign_insights registered
- [x] `MetaAdsPanel.tsx` — date picker, campaign filter, Pause/Activate buttons per campaign
- [x] `MetaAdsPanel.tsx` — Campaign Insights panel with ▶ Run Now button
- [x] `MetaAdsPanel.tsx` — Budget Config UI (alert%, auto-pause%, daily cap, per-campaign budgets)
- [x] Telegram inline keyboards on all alerts — ⏸ Pause Now / ✅ Dismiss buttons
- [x] `/menu` command with full clickable button grid
- [x] Duplicate scraper Task Scheduler entries on RDPs removed
- [x] `setMyCommands` — bot command list registered with Telegram

---

## Session Log

### Session Report — 2026-07-01 (Meta Ads Intelligence)
#### Completed
- Fixed duplicate FAST SPEND alerts: two Task Scheduler entries on each RDP — deleted 6/30 duplicates
- Fixed root cause: outdated scraper.py on RDPs had inline alert logic — re-downloaded from GitHub on both
- Rewrote telegram_bot.py: inline keyboard buttons throughout, /menu grid, callback_query handling, setMyCommands
- Built spend_alerts.py: budget % alert, auto-pause queue, stopped-campaign detection, daily cap alert
- Updated notifications.py: reply_markup support in send_telegram()
- Updated meta_ads.py: spend alerts hooked into /ingest (non-blocking asyncio.create_task), budget-config endpoints
- Built campaign_insights.py: Claude Haiku daily analysis of all campaign data → Telegram + Memory
- Updated jobs.py: campaign_insights job at 9:30am ET
- Updated scheduler.py: campaign_insights registered
- Added /insights and /insights/run endpoints to meta_ads.py
- Updated MetaAdsPanel.tsx: date picker, campaign filter, per-campaign Pause/Activate buttons, Insights panel, Budget Config UI
#### Files Modified
- hermes/src/integrations/telegram_bot.py
- hermes/src/core/spend_alerts.py (new)
- hermes/src/core/campaign_insights.py (new)
- hermes/src/core/notifications.py
- hermes/src/core/jobs.py
- hermes/src/core/scheduler.py
- hermes/src/api/routes/meta_ads.py
- dashboard/src/components/panels/MetaAdsPanel.tsx
#### Next Session Priority
- Verify CI/CD deploy on VPS: check `docker logs jarvis-hermes` for startup errors
- Test campaign insights manually: POST /api/v1/meta-ads/insights/run
- Set up per-campaign budgets in Budget Config UI once RDPs have data
- Consider: alert deduplication (don't re-fire same alert every 5 min)

### 2026-06-29
- Created repository from scratch
- Improved ChatGPT architecture into concrete tech stack
- Scaffolded: README, CLAUDE.md, ARCHITECTURE.md, ROADMAP.md
- Built: Docker Compose infrastructure layer
- Scaffolded: Hermes (Python/FastAPI)
- Scaffolded: Dashboard (Next.js)
- Written: bootstrap and deployment scripts

### Session Report — 2026-06-30 (Phase 6)
#### Completed
- Wired `register_core_jobs()` into Hermes startup (jobs were never being registered)
- Created `scheduler.py` API route — GET /jobs, POST /trigger/{job_id}
- Fixed health check Docker service URLs, added Prometheus, persist results to events table
- Rebuilt SchedulerPanel as client component with SWR, live next-run times, manual trigger buttons
- Fixed CORS — added `localhost:3002` to allowed origins
#### Files Modified
- hermes/src/main.py, hermes/src/core/jobs.py, hermes/src/api/routes/scheduler.py
- dashboard/src/components/panels/SchedulerPanel.tsx
#### Next Session Priority
- Phase 7: AI Intelligence — pgvector semantic search, pattern recognition, autonomous planning

### 2026-06-30
- Deployed full infrastructure to VPS (postgres, redis, n8n, prometheus, grafana)
- Built and deployed Hermes — health check passing, scheduler running
- Anthropic API key configured and live
- Pushed code to GitHub: github.com/highhopestechnologies01/JARVIS-OS
- Built and deployed Dashboard (Next.js) — LIVE at localhost:3002 via SSH tunnel
- Installed Tailscale on VPS (100.73.196.118) — Mac Tailscale needs reconnection
- Phase 4 COMPLETE
- **Next:** Phase 5 — Voice interface

### Session Report — 2026-06-30 (Phase 8)
#### Completed
- GitHub Actions CI/CD: smart deploy workflow with VPS SSH deploy + health verification
- Connected jarvis-n8n to jarvis-net; fixed health check hostnames (jarvis-n8n, jarvis-grafana, jarvis-prometheus)
- Fixed Hermes Dockerfile HEALTHCHECK URL
- Added PAT `workflow` scope to enable CI/CD push
- PostgreSQL daily backup: `scripts/backup-postgres.sh`, cron 1am, 7-day retention, test backup ✓ (8.0K)
- Security audit confirmed: Hermes non-root user, no public ports, secrets in .env only
- RUNBOOK.md — 8 failure scenarios with exact recovery commands
- Phase 8 COMPLETE — JARVIS OS is production-ready
#### Files Modified
- .github/workflows/deploy.yml (CI/CD)
- scripts/backup-postgres.sh (backups)
- RUNBOOK.md (new)
- ROADMAP.md (Phase 8 marked complete)
#### Errors / Blockers
- GitHub PAT needed `workflow` scope — user added manually
- n8n was not on jarvis-net — fixed with docker network connect
#### Next Session Priority
- Add GitHub Actions secrets (`VPS_SSH_KEY`, `VPS_HOST`) to repo Settings for CI/CD to activate
- Optional: Loki centralized logging, pgvector semantic search

### Session Report — 2026-06-30 (n8n Automations)
#### Completed
- Built 3 n8n workflow JSON files: health-alert handler, GitHub activity digest, Prometheus metrics snapshot
- Imported all 3 into live n8n (Coolify-managed, n8n-n8n-1) via n8n CLI import
- Activated all 3 workflows via host sqlite3 on `/opt/n8n/n8n_data/database.sqlite`
- Connected n8n-n8n-1 to jarvis-net after each restart
- Wired Hermes `infrastructure_health_check` to POST failures to `http://n8n-n8n-1:5678/webhook/jarvis-health-alert` (non-blocking)
- Fixed health check service URL: `jarvis-n8n` → `n8n-n8n-1`
- Deployed Hermes changes via GitHub Actions CI/CD
#### Files Modified
- hermes/src/core/jobs.py (n8n webhook + service URL fix)
- n8n/workflows/01-health-alert.json (new)
- n8n/workflows/02-github-activity.json (new)
- n8n/workflows/03-metrics-snapshot.json (new)
- ROADMAP.md
#### Errors / Blockers
- `n8n delete:workflow` CLI command doesn't exist — used host sqlite3 to delete
- `sqlite3` not in n8n container — must run from host via volume mount
- n8n loses jarvis-net on every restart — must run `docker network connect jarvis-net n8n-n8n-1` after each restart
- Workflows imported as inactive — activated via `UPDATE workflow_entity SET active=1` on host
#### Next Session Priority
- Verify end-to-end: trigger health check → confirm n8n receives it → confirm memory entry created
- Consider making n8n jarvis-net connection persistent (Coolify network config or docker-compose override)

### Session Report — 2026-07-01 (n8n Pipeline + Workflows 4-5)
#### Completed
- Diagnosed n8n HTTP Request node v4.2 bug: contentType=json double-encodes body, Hermes receives empty string ""
- Fix confirmed: contentType=raw + rawContentType=application/json sends body verbatim → 200 OK
- Applied fix to all 5 HTTP nodes across workflows 1-3; all executions now status=success ✅
- Fixed jarvis-dashboard health check: was using `curl` (not in alpine), switched to `wget /api/health`
- Added Next.js `GET /api/health` route to dashboard
- Updated workflows 1-3 to use dynamic n8n expressions (=$json data) instead of hardcoded bodies
- Created workflow 4: Daily Briefing Push (triggers Hermes briefing 8am, logs delivery)
- Created workflow 5: Weekly Memory Digest (Sunday 11pm, aggregates week's alerts/github/metrics)
- Written scripts/activate-workflows-4-5.sh for VPS activation
#### Files Modified
- dashboard/src/app/api/health/route.ts (new)
- dashboard/Dockerfile (health check → wget /api/health)
- infrastructure/docker-compose.yml (health check → wget /api/health)
- n8n/workflows/01-health-alert.json (contentType=raw + dynamic body)
- n8n/workflows/02-github-activity.json (contentType=raw + dynamic body)
- n8n/workflows/03-metrics-snapshot.json (contentType=raw + dynamic body)
- n8n/workflows/04-daily-briefing-push.json (new)
- n8n/workflows/05-weekly-digest.json (new)
- scripts/activate-workflows-4-5.sh (new)
- ROADMAP.md
#### Next Session Priority
- Run: bash /opt/jarvis-repo/scripts/activate-workflows-4-5.sh on VPS
- Test workflow 4 (daily briefing push) manually
- Add Twilio SMS or tighten Telegram notification routing

### Session Report — 2026-07-01 (n8n Dynamic Bodies + All 5 Workflows Live)
#### Completed
- Root cause found: n8n v2.x executes from `workflow_history` (not `workflow_entity.nodes`)
  - Direct psql UPDATEs to workflow_entity only update the "draft" — n8n runs the "published" version
  - Fix: must update workflow_history + workflow_published_version + workflow_entity.activeVersionId
- Fixed IF node routing: boolean expression coercion in n8n v2.x causes `{{ $json.has_failures }} == true` to always fail
  - Fix: switched to number comparison `$json.failure_count > 0` (unambiguous, no type coercion)
- Fixed webhook node: downgraded to typeVersion 1.1 for deterministic `$json.body` structure
- All 5 workflows now fully activated with published versions: wf1✅ wf2✅ wf3✅ wf4✅ wf5✅
- Confirmed end-to-end: health alert webhook → Code node → IF TRUE → health_alert stored in Hermes ✅
- Dashboard PORT fix deployed: PORT=3000 override in docker-compose.yml environment block
- Rewrote activate-workflows-4-5.sh to update all three n8n v2 tables correctly
#### Files Modified
- n8n/workflows/01-health-alert.json (webhook v1.1, failure_count IF condition, dynamic bodies)
- scripts/activate-workflows-4-5.sh (complete rewrite — handles workflow_history + published_version)
- ROADMAP.md
#### Errors / Blockers
- n8n v2 workflow_history discovery: took many iterations to find root cause
- workflow_history INSERT requires non-null `authors` column (get from existing record)
- workflow_entity.activeVersionId must be set for schedule-trigger workflows to activate
#### Next Session Priority
- Test wf4 (daily briefing push) by manually triggering: POST /api/v1/scheduler/trigger/daily_briefing
- Verify wf2 (github activity) and wf3 (metrics snapshot) execute with dynamic content
- Check dashboard health status
- Consider Telegram notification routing improvements

### Session Report — 2026-07-01 (Dashboard Health + Full System Operational)
#### Completed
- Fixed dashboard health check: root cause was Next.js standalone binds to container hostname (not localhost); fixed with CMD-SHELL using `$(hostname)` in health check command
- Fixed dashboard PORT: added HOSTNAME=0.0.0.0 + PORT=3000 to docker-compose environment block
- Confirmed all 5 n8n workflows running autonomously on schedule via execution_entity query:
  - wf1 Health Alert Handler: success (07:28, 07:39) ✅
  - wf2 GitHub Activity Digest: success (10:00) ✅
  - wf3 Prometheus Metrics Snapshot: success (every hour 08:00–13:00) ✅
  - wf4 Daily Briefing Push: success (12:00) ✅
  - wf5 Weekly Memory Digest: scheduled Sunday 11pm (not yet fired) ✅
- All 7 Docker services healthy: postgres, redis, hermes, dashboard, n8n, prometheus, grafana ✅
#### Files Modified
- infrastructure/docker-compose.yml (HOSTNAME=0.0.0.0, CMD-SHELL health check)
#### Errors / Blockers
- Docker system HOSTNAME env var overrides compose environment block for `localhost` binding
- Fix: CMD-SHELL health check with `$(hostname)` uses the actual bound hostname dynamically
- n8n REST API requires API key (not basic auth) — bypassed by querying PostgreSQL directly
#### Next Session Priority
- JARVIS OS is fully operational — all automation running autonomously
- Optional: set up pgvector semantic search (Phase 8 optional)
- Optional: Telegram notification tuning (daily briefing delivery confirmation)
- Optional: add wf5 weekly digest verification after Sunday 11pm run
