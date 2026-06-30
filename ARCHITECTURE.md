# JARVIS OS — Architecture

## Three-Tier Overview

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: MacBook (Control Station)                          │
│                                                             │
│  • Claude Code — engineering, coding, refactoring           │
│  • Dashboard access — via Tailscale browser                 │
│  • Git — version control                                    │
│  • SSH — VPS management over Tailscale                      │
│  • Development & local testing                              │
│                                                             │
│  Rule: Never host production services here.                 │
└────────────────────────┬────────────────────────────────────┘
                         │ Tailscale (encrypted)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 2: Linux VPS (JARVIS Brain) — runs 24/7               │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Hermes  │  │   n8n    │  │ Dashboard│  │  Coolify │  │
│  │ :8000    │  │ :5678    │  │  :3000   │  │  :8080   │  │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └──────────┘  │
│       │              │                                      │
│  ┌────▼─────────────▼────────────────────────────────┐     │
│  │  Internal Docker Network (jarvis-net)             │     │
│  ├───────────┬──────────────┬────────────────────────┤     │
│  │ PostgreSQL│    Redis     │  Prometheus + Grafana  │     │
│  │  :5432    │    :6379     │   :9090    :3001       │     │
│  └───────────┴──────────────┴────────────────────────┘     │
│                                                             │
│  Rule: No public ports except 443 (Coolify proxy).          │
│         All internal communication on jarvis-net.           │
└────────────────────────┬────────────────────────────────────┘
                         │ Tailscale (encrypted)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 3: Windows RDP (Browser Workspace)                    │
│                                                             │
│  • Dedicated browser profiles per business                  │
│  • Business applications & reporting                        │
│  • Callotro, CRMs, ad platforms                             │
│                                                             │
│  Rule: Never host backend services here.                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Hermes — Architecture Detail

```
                    ┌─────────────────────────────────┐
                    │           HERMES                 │
                    │      FastAPI on :8000            │
                    │                                  │
        ┌───────────┤   ┌─────────────────────────┐   │
        │  REST API │   │       Core Engine        │   │
        │  /api/v1/ │   │                          │   │
        │           │   │  MemoryEngine            │   │
        │  briefings│   │  Scheduler (APScheduler) │   │
        │  memory   │   │  PlannerAgent            │   │
        │  tasks    │   │  NotificationDispatcher  │   │
        │  health   │   │                          │   │
        └───────────┤   └──────────┬───────────────┘   │
                    │              │                    │
                    │   ┌──────────▼───────────────┐   │
                    │   │      Integrations         │   │
                    │   │                          │   │
                    │   │  AnthropicClient         │   │
                    │   │  (Claude API)            │   │
                    │   │                          │   │
                    │   │  TwilioClient            │   │
                    │   │  N8nClient               │   │
                    │   │  NotionClient            │   │
                    │   └──────────┬───────────────┘   │
                    │              │                    │
                    │   ┌──────────▼───────────────┐   │
                    │   │       Database            │   │
                    │   │                          │   │
                    │   │  SQLAlchemy ORM          │   │
                    │   │  PostgreSQL (primary)    │   │
                    │   │  Redis (cache/queue)     │   │
                    │   └──────────────────────────┘   │
                    └─────────────────────────────────┘
```

### Hermes Database Schema

```sql
-- Memory: long-term context storage
memories (id, type, content, embedding, metadata, created_at, updated_at)

-- Scheduled tasks
scheduled_tasks (id, name, cron_expr, handler, args, enabled, last_run, next_run)

-- Briefings: daily executive summaries
briefings (id, date, content, sources, status, created_at)

-- Events: audit log of all Hermes actions
events (id, type, source, payload, status, created_at)

-- Notifications: outbound alerts
notifications (id, channel, recipient, subject, body, status, sent_at)
```

---

## Dashboard — Architecture Detail

```
Next.js 14 (App Router)
├── /                    → Executive overview
├── /infrastructure      → Docker/VPS status
├── /briefings           → Daily briefings history
├── /memory              → Memory browser
├── /automations         → n8n workflow status
├── /notifications       → Alert history
└── /voice               → Voice interface (Phase 5)

Data flow:
Dashboard → Hermes API (:8000) → PostgreSQL
Dashboard → n8n API (:5678) → workflows
Dashboard → Prometheus (:9090) → metrics
```

---

## Network Architecture

```
Public Internet
     │
     │ HTTPS :443 (only)
     ▼
  Coolify
  (reverse proxy)
     │
     ├── /dashboard → Next.js :3000
     ├── /n8n       → n8n :5678
     └── /hermes    → Hermes :8000  (private only — not in Coolify)

Tailscale Network (100.x.x.x)
  Mac          → VPS  (SSH, dashboard access)
  Mac          → RDP  (remote desktop)
  VPS          → RDP  (automation reach)
```

---

## Tech Stack Decisions

| Component | Technology | Reason |
|-----------|-----------|--------|
| AI Brain | Python 3.12 + FastAPI | Best AI/ML ecosystem, async, fast |
| AI Reasoning | Anthropic Claude API | Best reasoning for planning tasks |
| Database | PostgreSQL 16 | Robust, JSONB for flexible memory |
| Cache/Queue | Redis 7 | Fast, supports pub/sub for events |
| Scheduler | APScheduler | Production-grade cron in Python |
| Dashboard | Next.js 14 + TypeScript | Modern, server components, fast |
| UI Components | Tailwind + shadcn/ui | Clean, customizable, no runtime CSS |
| Automation | n8n (self-hosted) | Visual workflows, 400+ integrations |
| Deployment | Docker Compose | Simple, portable, Coolify-compatible |
| Monitoring | Prometheus + Grafana | Industry standard, self-hosted |
| Network | Tailscale | Zero-config VPN, MagicDNS |
| ORM | SQLAlchemy 2.0 | Typed, async, battle-tested |

---

## Scaling Path

Current (Solo):
```
1 VPS (4 vCPU / 8GB RAM)
All services on one machine
Coolify for deployment
```

Future (Phase 8+):
```
Separate DB server
CDN for dashboard assets
Dedicated AI inference server
Multi-region if needed
```
