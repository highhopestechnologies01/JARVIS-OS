# JARVIS OS — Roadmap

Updated: 2026-06-29

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

## Phase 2 · Infrastructure 🔨 ACTIVE

**Goal:** VPS running all core services via Docker Compose.
**Exit criteria:** `./scripts/health-check.sh` returns all green.

- [ ] VPS bootstrapped (`./scripts/bootstrap-vps.sh`)
- [ ] Docker + Docker Compose installed on VPS
- [ ] `infrastructure/docker-compose.yml` deployed
- [ ] PostgreSQL running and accepting connections
- [ ] Redis running
- [ ] n8n running and accessible via Tailscale
- [ ] Prometheus scraping metrics
- [ ] Grafana dashboard accessible
- [ ] Coolify installed (optional — for GUI deployments)
- [ ] All services on `jarvis-net` Docker network
- [ ] Backups configured for PostgreSQL

**Credentials needed from Thomas:**
- [ ] VPS SSH address and Tailscale IP
- [ ] Domain name (for Coolify reverse proxy)

---

## Phase 3 · Hermes 🔨 SCAFFOLDED

**Goal:** Hermes API running, memory working, daily briefing delivered.
**Exit criteria:** Morning briefing arrives via notification at 8am.

- [ ] Hermes Docker container builds and starts
- [ ] Database migrations run (all tables created)
- [ ] `/health` endpoint returns 200
- [ ] Memory: store and retrieve working
- [ ] Scheduler: APScheduler running with daily briefing job
- [ ] Planner: Claude API integration working
- [ ] Notification: at least one channel working (email or Twilio)
- [ ] Daily briefing generated and delivered
- [ ] Hermes accessible from Dashboard via internal network

**Credentials needed:**
- [ ] `ANTHROPIC_API_KEY`
- [ ] `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` (for SMS)
- [ ] SMTP credentials (for email notifications)

---

## Phase 4 · Dashboard ⏳ SCAFFOLDED

**Goal:** Executive dashboard live, accessible via Tailscale browser.
**Exit criteria:** One screen shows infrastructure, briefing, and memory.

- [ ] Next.js app builds
- [ ] Infrastructure panel: all Docker service statuses
- [ ] Briefings panel: today's Hermes briefing
- [ ] Memory panel: recent memory entries
- [ ] Notifications feed: last 10 alerts
- [ ] Dashboard accessible via Tailscale (Mac browser → VPS)

---

## Phase 5 · Voice ⏳ PLANNED

**Goal:** Speak a command → Hermes acts → hears the response.

- [ ] Speech-to-text pipeline (Whisper or Deepgram)
- [ ] Voice command router in Hermes
- [ ] Text-to-speech response (ElevenLabs or OpenAI TTS)
- [ ] Voice panel in Dashboard
- [ ] Wake word detection (optional)

---

## Phase 6 · Automation ⏳ PLANNED

**Goal:** Hermes runs autonomously with zero daily maintenance.

- [ ] Daily morning briefing (8am)
- [ ] Infrastructure health check (every 15 min)
- [ ] Weekly performance report (Monday 9am)
- [ ] Alert on service failure (immediate)
- [ ] n8n workflows: at least 5 automations live
- [ ] Auto-restart failed services

---

## Phase 7 · AI Intelligence ⏳ PLANNED

**Goal:** Hermes learns, predicts, and acts without being asked.

- [ ] Long-term memory with semantic search (pgvector)
- [ ] Pattern recognition (usage, performance trends)
- [ ] Predictive monitoring (anomaly detection)
- [ ] Autonomous task planning (weekly)
- [ ] Context-aware briefings (personalized)

---

## Phase 8 · Production ⏳ PLANNED

**Goal:** Ship-it quality. Handles failure gracefully. Zero downtime.

- [ ] GitHub Actions CI/CD pipeline
- [ ] Automated PostgreSQL backups (daily, off-site)
- [ ] Centralized logging (Loki or Papertrail)
- [ ] Full monitoring coverage
- [ ] Security audit completed
- [ ] Runbook written for all failure scenarios
- [ ] Production release

---

## Session Log

### 2026-06-29
- Created repository from scratch
- Improved ChatGPT architecture into concrete tech stack
- Scaffolded: README, CLAUDE.md, ARCHITECTURE.md, ROADMAP.md
- Built: Docker Compose infrastructure layer
- Scaffolded: Hermes (Python/FastAPI)
- Scaffolded: Dashboard (Next.js)
- Written: bootstrap and deployment scripts
- **Next:** Thomas to run `bootstrap-vps.sh` on VPS and provide API credentials
