# JARVIS OS

A production-grade AI Operating System. Personal executive assistant infrastructure built for real autonomy.

```
MacBook (Control)  →  Linux VPS (Brain)  →  Windows RDP (Workspace)
     Claude Code        Hermes + Docker         Browser Profiles
     Dashboard          n8n + PostgreSQL         Business Apps
     Git + SSH          Monitoring               Reporting
```

## What This Is

Three machines. One private network. One AI brain running 24/7.

- **Hermes** — Python/FastAPI AI agent. Memory, scheduling, briefings, notifications.
- **Dashboard** — Next.js executive interface. Everything visible in one screen.
- **n8n** — Automation engine. Workflows, webhooks, integrations.
- **Infrastructure** — Docker Compose. PostgreSQL, Redis, Prometheus, Grafana.

All communication over Tailscale. No public ports.

## Phases

| Phase | Status | What |
|-------|--------|------|
| 1 · Foundation | ✅ Done | Mac setup, Git, SSH, Tailscale, Claude Code |
| 2 · Infrastructure | 🔨 Active | Docker, PostgreSQL, Redis, Monitoring |
| 3 · Hermes | ⏳ Next | AI brain, memory, scheduler, notifications |
| 4 · Dashboard | ⏳ Next | Executive UI, infrastructure view |
| 5 · Voice | ⏳ Planned | STT → Hermes → TTS pipeline |
| 6 · Automation | ⏳ Planned | Daily briefings, health monitoring, deployments |
| 7 · AI Intelligence | ⏳ Planned | Long-term memory, predictions, autonomous planning |
| 8 · Production | ⏳ Planned | CI/CD, backups, security audit, launch |

## Quick Start

```bash
# On Mac — one-time setup
./scripts/bootstrap-mac.sh

# On VPS — one-time setup
./scripts/bootstrap-vps.sh

# Deploy infrastructure to VPS
./scripts/deploy.sh

# Health check all services
./scripts/health-check.sh
```

## Structure

```
JARVIS-OS/
├── hermes/          # AI brain service (Python/FastAPI)
├── dashboard/       # Executive UI (Next.js/TypeScript)
├── infrastructure/  # Docker Compose, PostgreSQL, monitoring
├── n8n/             # Workflow definitions
├── scripts/         # Bootstrap, deploy, health check
└── docs/            # Architecture, security, API docs
```

## Key Docs

- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Security](docs/SECURITY.md)
- [API Reference](docs/API.md)
- [Deployment](docs/DEPLOYMENT.md)
