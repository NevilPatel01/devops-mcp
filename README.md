# DevOps AI Agent

An autonomous **DevOps AI agent** that monitors real VPS infrastructure over SSH, reasons about anomalies with Claude, proposes remediations, and executes fixes behind a **human-in-the-loop approval gate**. Built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io), with a real-time React dashboard and Claude Desktop as a fallback approval channel.

> **Status:** Phases 0–8 complete (Terraform, compliance, false-positive learning, **runbook engine**). Phase 9 (demo mode) planned — see `docs/PHASES_5_9_PLAN.md`.  
> **Spec:** [Project.md](Project.md) (build phases in §11).

<!-- Record a screen capture (container crash → approval → live output → resolved) and save as docs/assets/demo.gif, then uncomment: -->
<!-- ![Demo](docs/assets/demo.gif) -->

---

## What this is

Most monitoring tools alert on thresholds. This project closes the loop: Claude **correlates** signals (e.g. container crash + recent GitHub Actions deploy), **proposes** a single remediation with risk tier and rollback plan, waits for **your approval** (web UI or Claude Desktop), then **executes** over SSH and **verifies** health—with full audit logs and **learned rules** from past rejections.

---

## How it works (agent loop)

1. **Observe** — Poller SSHes each VPS every 30s; metrics and container state go to SQLite; baselines updated.
2. **Detect** — Thresholds and baseline deviation raise an anomaly.
3. **Analyse** — Agent loads feedback rules, runs `correlate_incident` (snapshots, CI/CD, history).
4. **Plan** — Claude returns one structured `ProposedAction` (action, rationale, risk, rollback).
5. **Gate** — Pending action on dashboard; LOW-risk safe fixes auto-execute; after 60s, MCP + reminder if still pending (HIGH requires dashboard `CONFIRM`).
6. **Execute** — Approved actions run through risk-gated executor with live log streaming.
7. **Verify** — Post-action health check; auto-rollback on failure; postmortem when resolved.

---

## High-level architecture

Single process on **`127.0.0.1:8080`** — `python server.py` runs FastAPI, WebSocket, MCP (SSE), the 30s poller, and serves the React build. No agent on VPS; all remote access is SSH + GitHub API.

### Deployment topology

```mermaid
flowchart TB
  subgraph Clients["Operator channels"]
    Browser["React dashboard<br/>HTTP + WebSocket /ws"]
    ClaudeDesktop["Claude Desktop<br/>MCP SSE /mcp"]
  end

  subgraph Host["Local host · python server.py"]
    direction TB
    Entry["server.py<br/>FastAPI · static dashboard/dist"]

    subgraph Core["Core runtime"]
      direction LR
      Poller["poller.py<br/>30s health loop"]
      Agent["agent.py<br/>Claude one-shot plan"]
      Executor["executor.py<br/>risk-gated SSH"]
    end

    Hub["ws_hub.py<br/>WebSocket broadcast"]
    Store[("db/store.py<br/>SQLite")]

    Entry --> Hub
    Entry --> Poller
    Entry --> Agent
    Entry --> Executor
    Poller --> Store
    Agent --> Store
    Executor --> Store
    Hub --> Browser
  end

  subgraph Remote["External systems"]
    VPS["VPS fleet (1–3)<br/>Ubuntu 22.04 · Docker Compose"]
    GitHub["GitHub Actions<br/>workflows & logs"]
    Anthropic["Anthropic API<br/>claude-sonnet-4-5"]
  end

  Browser <-->|"live state · approvals"| Hub
  ClaudeDesktop <-->|"fallback approve/reject"| Entry
  Poller -->|"SSH read"| VPS
  Executor -->|"SSH write"| VPS
  Agent -->|"correlate CI/CD"| GitHub
  Agent -->|"plan JSON"| Anthropic
```

### System context

```mermaid
flowchart LR
  subgraph Operator
    UI["Browser :8080"]
    CD["Claude Desktop"]
  end

  subgraph AgentRuntime["devops-agent"]
    S["server.py"]
    P["poller.py"]
    A["agent.py"]
    E["executor.py"]
    DB[("SQLite")]
  end

  subgraph MCPTools["tools/"]
    Infra["infrastructure<br/>read SSH"]
    Inc["incident<br/>correlate · memory"]
    CI["cicd<br/>GitHub API"]
    ExT["executor<br/>write SSH"]
  end

  subgraph Infra["Managed infrastructure"]
    VPS["VPS × 1–3"]
    GHA["GitHub Actions"]
  end

  LLM["Anthropic API"]

  UI <-->|WebSocket| S
  CD <-->|MCP SSE| S
  S --> P & A & E
  P & A & E --> DB
  S --> MCPTools
  P --> Infra
  A --> Inc & CI
  E --> ExT
  Infra & ExT -->|paramiko| VPS
  CI --> GHA
  A --> LLM
```

---

## System design

### Layered architecture

```mermaid
flowchart TB
  subgraph Presentation["Presentation"]
    Dash["dashboard/<br/>React · Vite · Tailwind"]
    WSClient["ws.js<br/>WebSocket singleton"]
    Dash --> WSClient
  end

  subgraph Application["Application · server.py"]
    API["REST /api/health"]
    WS["WebSocket /ws"]
    MCP["MCP SSE /mcp"]
    Static["StaticFiles dashboard/dist"]
  end

  subgraph Domain["Domain services"]
    Poll["poller.py<br/>observe · detect"]
    Agt["agent.py<br/>analyse · plan · gate"]
    Exec["executor.py<br/>execute · verify · rollback"]
  end

  subgraph ToolsLayer["MCP tool layer · tools/"]
    direction LR
    T1["infrastructure.py"]
    T2["incident.py"]
    T3["cicd.py"]
    T4["executor.py"]
  end

  subgraph Persistence["Persistence · db/store.py only"]
    SQL[("SQLite<br/>incidents · actions · rules · snapshots")]
  end

  subgraph External["External"]
    SSH["VPS via SSH"]
    GH["GitHub REST"]
    AI["Anthropic HTTPS"]
  end

  WSClient <-->|events| WS
  WS --> Domain
  MCP --> ToolsLayer
  Poll --> T1 --> SSH
  Agt --> T2 & T3
  Agt --> AI
  T3 --> GH
  Exec --> T4 --> SSH
  Domain --> SQL
  ToolsLayer --> SQL
```

### Design constraints

```mermaid
mindmap
  root((Design))
    Runtime
      Single process
      python server.py
      Bind 127.0.0.1:8080
    Safety
      Human-in-the-loop
      Risk enforced in executor
      Max 1 pending action per server
      protected_services block writes
    Remote ops
      SSH only paramiko
      No daemon on VPS
      10s timeout pooled connections
    Data
      SQLite via store.py only
      UTC in DB local in UI
      Snapshots pruned after 7d
    MCP contract
      Return success and error
      Never raise to caller
      Claude Desktop via SSE
    Learning
      Rejections to feedback_rules
      Claude respects on replan
```

### Component map

```mermaid
flowchart LR
  subgraph Entry
    server["server.py<br/>lifespan · routes · mount static"]
  end

  subgraph Observe
    poller["poller.py<br/>metrics · baselines · anomalies"]
    metrics["health_metrics.py"]
    ssh["ssh_client.py<br/>pooled paramiko"]
    poller --> metrics & ssh
  end

  subgraph Reason
    agent["agent.py<br/>context gather · Claude JSON"]
  end

  subgraph Act
    executor["executor.py<br/>risk check · snapshot · health"]
  end

  subgraph Realtime
    hub["ws_hub.py<br/>broadcast to dashboards"]
  end

  subgraph UI
    react["dashboard/src<br/>ServerGrid · ApprovalCard · IncidentFeed"]
  end

  subgraph Data
    store["db/store.py"]
    schema["db/schema.sql"]
    store --> schema
  end

  server --> poller & agent & executor & hub
  hub <--> react
  poller & agent & executor --> store
```

### Data model

```mermaid
erDiagram
  servers ||--o{ snapshots : captures
  servers ||--o| baselines : tracks
  servers ||--o{ incidents : reports
  incidents ||--o{ proposed_actions : triggers
  proposed_actions ||--o{ action_logs : streams

  servers {
    text id PK
    text label
    text host
    timestamp last_seen_at
    text status
  }

  snapshots {
    int id PK
    text server_id FK
    timestamp captured_at
    real cpu_percent
    real memory_percent
    json container_statuses
  }

  baselines {
    text server_id PK
    real cpu_p95
    real memory_p95
  }

  incidents {
    text id PK
    text server_id FK
    text title
    text status
    text severity
    timestamp created_at
  }

  proposed_actions {
    text id PK
    text incident_id FK
    text action_type
    text risk_tier
    text status
  }

  action_logs {
    int id PK
    text action_id FK
    text line
    timestamp logged_at
  }

  feedback_rules {
    int id PK
    text rule_text
    timestamp created_at
  }
```

Full schema: [`db/schema.sql`](db/schema.sql).

### End-to-end data flow

```mermaid
flowchart LR
  subgraph Ingest
    VPS["VPS SSH"]
    Poller["poller.py"]
    Snap[("snapshots")]
    Base[("baselines")]
    VPS --> Poller
    Poller --> Snap & Base
  end

  subgraph DetectPlan
    Anomaly["anomaly event"]
    Agent["agent.py"]
    Claude["Anthropic API"]
    Inc[("incidents")]
    Act[("proposed_actions")]
    Poller --> Anomaly --> Agent
    Agent --> Claude
    Agent --> Inc & Act
  end

  subgraph Gate
    WS["WebSocket"]
    UI["Dashboard"]
    MCP["Claude Desktop"]
    Act --> WS --> UI
    Act --> MCP
    UI & MCP -->|"approve / reject"| Agent
  end

  subgraph Execute
    Exec["executor.py"]
    Logs[("action_logs")]
    VPS2["VPS SSH"]
    Agent --> Exec
    Exec --> Logs
    Exec --> VPS2
    Exec -->|"health OK"| Inc
  end
```

### Approval & risk flow

```mermaid
sequenceDiagram
  participant P as poller.py
  participant A as agent.py
  participant DB as SQLite
  participant WS as WebSocket
  participant Op as Operator
  participant E as executor.py
  participant VPS as VPS

  P->>A: AnomalyEvent
  A->>DB: create_incident
  A->>A: correlate_incident + Claude plan
  A->>DB: proposed_actions (pending)
  A->>WS: action_pending
  Op->>WS: approve_action (or MCP approve_action)
  alt risk = low AND auto_execute enabled
    A->>E: execute (no wait)
  else
    Op->>WS: approve after review
  end
  E->>VPS: SSH / docker (snapshot first)
  E->>WS: action_log_line (stream)
  E->>VPS: health check
  alt health fail
    E->>VPS: rollback
    E->>WS: action_rolled_back
  else
    E->>DB: incident resolved
    E->>WS: incident_resolved
  end
```

### Risk tiers

```mermaid
flowchart TD
  Action["ProposedAction"] --> Check{"risk_tier?"}

  Check -->|LOW| Low["Restart container · diagnostics"]
  Check -->|MEDIUM| Med["Compose change · rollback · scale"]
  Check -->|HIGH| High["Arbitrary SSH command"]

  Low --> Auto{"auto_execute_risk_tier: low?"}
  Auto -->|yes| Run["executor.py runs"]
  Auto -->|no| Wait["Dashboard approval"]

  Med --> Approve["Always requires approval"]
  High --> Confirm["Approval + type CONFIRM"]

  Approve --> Run
  Confirm --> Run
  Wait --> Run

  Run --> Protected{"service in protected_services?"}
  Protected -->|yes| Block["Blocked even if LOW"]
  Protected -->|no| SSH["SSH execute + health check"]
```

### WebSocket protocol

```mermaid
flowchart LR
  subgraph ServerToClient["Server → client"]
    S1["snapshot_update<br/>live metrics"]
    S2["incident_created"]
    S3["action_pending<br/>approval card"]
    S4["action_log_line<br/>SSH stream"]
    S5["action_executed"]
    S6["action_rolled_back"]
    S7["incident_resolved"]
    S8["action_pending_reminder<br/>after 60s"]
  end

  subgraph ClientToServer["Client → server"]
    C1["approve_action"]
    C2["reject_action"]
    C3["request_handoff<br/>Phase 4"]
  end

  Hub["ws_hub.py"] --> ServerToClient
  ClientToServer --> Hub
```

### External integrations

```mermaid
flowchart TB
  subgraph DevOpsAgent["devops-agent"]
    Poll["poller.py"]
    Agt["agent.py"]
    Exe["executor.py"]
    CICD["tools/cicd.py"]
    Infra["tools/infrastructure.py"]
  end

  VPS["VPS fleet<br/>Paramiko SSH · 10s timeout · key auth"]
  GH["GitHub<br/>PyGithub REST · Actions runs & logs"]
  AI["Anthropic<br/>HTTPS · one-shot JSON plan"]
  CD["Claude Desktop<br/>MCP SSE localhost:8080/mcp"]
  BR["Browser<br/>WebSocket + static HTTP"]

  Poll --> Infra --> VPS
  Exe --> VPS
  Agt --> AI
  CICD --> GH
  Agt --> CICD
  CD <-->|approve · reject · reminder| DevOpsAgent
  BR <-->|live UI| DevOpsAgent
```

---

## The approval gate

| Tier | Examples | Default behavior |
|------|----------|------------------|
| **Low** | Restart one container, read-only diagnostics | May auto-execute if `auto_execute_risk_tier: low` in `config/rules.yaml` |
| **Medium** | Compose changes, rollback deploy, scale, trigger workflow | Always requires approval |
| **High** | Arbitrary SSH | Approval + type **CONFIRM** in dashboard |

Executor enforces tiers even if the model mis-labels risk. Rejections become natural-language **feedback rules** Claude must respect on future plans.

---

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Agent runtime | Python 3.11+ | Async SSH, MCP, FastAPI ecosystem |
| API / realtime | FastAPI + WebSocket | Single origin with static dashboard |
| Protocol | MCP | Claude Desktop + tool standardization |
| LLM | Anthropic API | Planning, postmortem, handoff |
| Remote access | Paramiko (SSH) | No agent on VPS—realistic ops constraint |
| CI/CD data | PyGithub | Actions runs, logs, diffs |
| State | SQLite (aiosqlite) | Zero extra infrastructure |
| UI | React 18 + Vite + Tailwind | Fast dashboard, served as static build |
| Charts | Recharts | Server metric trends (Phase 4+) |

---

## Project structure

```
devops-mcp/
├── server.py              # Entry: FastAPI + MCP + WebSocket + static
├── poller.py              # 30s health loop
├── agent.py               # Claude observe→plan→gate loop
├── executor.py            # Risk-gated execution orchestration
├── tools/                 # MCP tool implementations
├── db/                    # schema.sql + store.py (only DB access)
├── models/                # Dataclasses / config models
├── dashboard/             # React SPA → dist/
├── config/
│   ├── servers.yaml
│   ├── rules.yaml
│   └── repos.yaml         # Multi-repo CI/CD (your config)
└── tests/
```

Full layout: [Project.md](Project.md#4-complete-file-structure).

---

## Setup

**Prerequisites:** Python 3.11+, Node 18+, SSH key access to VPS, Anthropic + GitHub tokens.

```bash
git clone https://github.com/NevilPatel01/devops-mcp
cd devops-mcp

# Python 3.11+ (use 3.11 venv — 3.14 lacks pydantic-core wheels)
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Dashboard
cd dashboard && npm install && npm run build && cd ..

# Config (servers.yaml and repos.yaml are gitignored)
cp .env.example .env
cp config/servers.yaml.example config/servers.yaml
cp config/repos.yaml.example config/repos.yaml
# Edit servers.yaml (SSH hosts) and repos.yaml (GitHub owner/name + linked_servers)

# Run
python server.py
# → http://127.0.0.1:8080
```

### Setup checklist

Before relying on the agent, confirm each item:

| Step | Command / action |
|------|------------------|
| Repos | `cp config/repos.yaml.example config/repos.yaml` — edit owner/name and `linked_servers` |
| Env | `cp .env.example .env` — set `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, optional `DATABASE_PATH` |
| Servers | `cp config/servers.yaml.example config/servers.yaml` — SSH hosts and services |
| Dashboard | `cd dashboard && npm install && npm run build` |
| Server | `python server.py` (from repo root with venv active) |
| Health | `curl -s http://127.0.0.1:8080/api/health` → `{"status":"ok",...}` |
| Setup | `curl -s http://127.0.0.1:8080/api/setup/status` — all flags should be true when ready |

The Overview page shows a **Setup checklist** banner when anything is missing (dismissible while incomplete).

**Handoff shortcut:** on the dashboard, press **H** to open the oncall handoff drawer (or use **Generate handoff** in the header).

**Claude Desktop (approval fallback):** copy `claude_desktop_config.json` to your Claude Desktop config and set the absolute path to `server.py`.

---

## Development

Phased build order: **[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)** (summary) and **[Project.md §11](Project.md#11-build-phases)** (full spec). Phase 6 decisions: **[docs/DECISIONS.md](docs/DECISIONS.md)**.

### Tests (no VPS required)

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
ruff check .
```

CI runs the same on Python 3.11 with mocked SSH/GitHub. Optional local integration test: copy `config/servers.yaml.example` → `config/servers.yaml` and fill real hosts (`test_servers_config_loads` skips if missing).

Cursor workflow: `.cursor/rules/` and `.cursor/commands/`.

---

## What I built & learned

- **MCP tool design:** Consistent `{success, error}` contracts and shared approval handlers for dashboard + Claude Desktop.
- **Async Python:** Poller, agent, and WebSocket in one process without blocking SSH.
- **Human-in-the-loop AI:** Risk tiers enforced at execution time, not only in prompts; rejections become durable natural-language rules.
- **Ops realism:** SSH-only monitoring—no daemon on managed servers—mirrors how small teams run VPS today.
- **Phase 6 compliance:** Sensitive-service tiers, audit log, dashboard `COMPLIANCE` ack for HIGH—documented in [docs/DECISIONS.md](docs/DECISIONS.md); not a certification claim.

### Works offline vs needs your VPS

| Works without VPS | Needs real infrastructure |
|-------------------|---------------------------|
| `pytest`, `ruff`, dashboard `npm run build` | `python server.py` poller + live metrics |
| MCP tool handlers (mocked in tests) | SSH in `config/servers.yaml` |
| Dashboard UI against empty DB | Kill/restart demo on `test-nginx` |
| Claude planning (with `ANTHROPIC_API_KEY`) | GitHub correlation (`GITHUB_TOKEN`, `repos.yaml`) |

---

## License

MIT — see [LICENSE](LICENSE).

---

## References

- [Project specification](Project.md)
- [Development plan](docs/DEVELOPMENT_PLAN.md)
- [Architecture decisions](docs/DECISIONS.md)
