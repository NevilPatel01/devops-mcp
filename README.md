# DevOps MCP — Multi-site fleet control

**DevOps MCP** is a local-first control plane for agencies and indie hackers managing **5–20 client sites** on Docker Compose VPS hosts. One dashboard shows **live uptime**, per-site HTTP latency, container logs, and restart actions across your fleet—no agent installed on servers, only SSH.

The same runtime still includes the original **AI DevOps agent** (Phases 0–8): SSH poller, Claude planning, risk-gated execution, and MCP tools for investigation. The **product UI** is now **fleet-first**; advanced agent/Terraform/runbook features stay in the codebase but are not the primary nav.

> **Status:** Fleet product v2 shipped (onboarding, sites, live uptime, fleet table UI). Core agent Phases 0–8 complete. **Production deploy** (`devopsmcp.nevil.ca`) still needs HTTPS, auth, and Slack delivery — see [Product status](#product-status) below.  
> **Original spec:** [Project.md](Project.md) · **Decisions:** [docs/DECISIONS.md](docs/DECISIONS.md)

---

## Why we pivoted

This repo started as a **portfolio-grade autonomous DevOps agent** demo: poller → Claude → approval gate → SSH execute, with Terraform UI, compliance typing, runbooks, and Claude Desktop as a first-class approval channel.

That architecture is strong engineering, but it is **not what operators with many small client VPS sites reach for daily**. Feedback and real use pointed to a simpler job:

| Old focus | Problem |
|-----------|---------|
| Server-centric grid + incident feed | Hard to see **which client site** is down at a glance |
| YAML-first onboarding | High friction vs “paste SSH key, add URL” |
| Terraform / compliance / runbooks in main nav | Impressive for demos, **noise** for 5–20 Compose sites |
| Claude Desktop as approval path | Wrong default for a **web product** |

**Pivot (2026):** **Site-first fleet product** — connect VPS over SSH, register client sites with URLs, get **automatic uptime checks every 60s** with WebSocket live updates, inline check/restart/logs, optional AI remediation behind the existing approval gate. MCP remains for **investigation** (logs, incidents), not as the main UI.

We kept the agent, executor, and MCP layer; we **cut/hid** portfolio theater from the default experience and invested in onboarding + live fleet visibility.

---

## What you get today (Fleet)

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','lineColor':'#475569'}}}%%
flowchart TB
  subgraph Local["Your machine · python server.py :8080"]
    UI["Fleet dashboard"]
    Uptime["Uptime checker · 60s"]
    Poller["SSH poller · 30s"]
    Agent["AI agent · optional"]
    MCP["MCP /mcp"]
    DB[("SQLite")]
  end

  subgraph VPS["Client VPS hosts"]
    S1["Site A · Compose"]
    S2["Site B · Compose"]
  end

  UI <-->|WebSocket| Uptime
  Uptime -->|HTTP probe| S1 & S2
  Poller -->|SSH| S1 & S2
  Agent --> MCP
  Uptime & Poller --> DB
```

| Feature | Status |
|---------|--------|
| SSH server onboarding (key path or upload) | ✅ |
| Add client sites (URL, container, optional compose path) | ✅ |
| Live uptime (60s) + WebSocket `site_update` | ✅ |
| Fleet table: status, HTTP, latency, last check | ✅ |
| Per-site check / check-all / restart / logs | ✅ |
| Connected servers panel | ✅ |
| Alerts tab (down sites + pending AI approvals) | ✅ |
| Incidents history | ✅ |
| Settings (Slack webhook + email **stored**) | ⚠️ stored only — not sent yet |
| AI auto-remediation | ⚠️ needs `ANTHROPIC_API_KEY` in `.env` |
| GitHub deploy correlation | ⚠️ needs `GITHUB_TOKEN` + `repos.yaml` |
| HTTPS + login for public deploy | ❌ not yet |
| Slack/email on downtime | ❌ not yet |

---

## How it works

### Fleet loop (primary)

1. **Connect** — Add VPS via SSH (UI wizard or legacy `config/servers.yaml`).
2. **Register sites** — Client name, URL, server, container name (compose path optional).
3. **Monitor** — Uptime checker probes URLs every **60s**; dashboard updates live via WebSocket.
4. **Act** — Restart containers, tail logs, manual re-check from the fleet table.
5. **Alert** — Down sites surface in the fleet banner and **Alerts** tab; AI approvals appear when the agent proposes fixes.

### Agent loop (optional, unchanged)

1. **Observe** — Poller SSHes each VPS every 30s; metrics and containers → SQLite.
2. **Detect** — Threshold / baseline anomaly → incident.
3. **Plan** — Claude one-shot JSON `ProposedAction` (Python pre-gathers context).
4. **Gate** — Dashboard approval; LOW may auto-execute; HIGH requires typed `CONFIRM`.
5. **Execute & verify** — Risk-gated SSH, live logs, post-action health check.

---

## High-level architecture

Single process on **`127.0.0.1:8080`** — `python server.py` runs FastAPI, WebSocket, MCP (SSE), the 30s poller, and serves the React build. No agent on VPS; all remote access is SSH + GitHub API.

### Deployment topology

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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

  classDef client fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  classDef core fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  classDef data fill:#e2e8f0,stroke:#475569,color:#0f172a
  classDef remote fill:#dcfce7,stroke:#15803d,color:#0f172a
  class Browser,ClaudeDesktop client
  class Entry,Hub,Poller,Agent,Executor core
  class Store data
  class VPS,GitHub,Anthropic remote
```

### System context

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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

  classDef operator fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  classDef runtime fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  classDef tools fill:#fef3c7,stroke:#b45309,color:#0f172a
  classDef managed fill:#dcfce7,stroke:#15803d,color:#0f172a
  classDef external fill:#e2e8f0,stroke:#475569,color:#0f172a
  class UI,CD operator
  class S,P,A,E runtime
  class DB external
  class Infra,Inc,CI,ExT tools
  class VPS,GHA managed
  class LLM external
```

---

## System design

### Layered architecture

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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

  style Presentation fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  style Application fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  style Domain fill:#dcfce7,stroke:#15803d,color:#0f172a
  style ToolsLayer fill:#fef3c7,stroke:#b45309,color:#0f172a
  style Persistence fill:#fce7f3,stroke:#be185d,color:#0f172a
  style External fill:#e2e8f0,stroke:#475569,color:#0f172a
  classDef node fill:#ffffff,stroke:#64748b,color:#0f172a
  class Dash,WSClient,API,WS,MCP,Static,Poll,Agt,Exec,T1,T2,T3,T4,SSH,GH,AI node
  class SQL node
```

### Design constraints

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
flowchart TB
  ROOT(["⚙️ Design constraints"])

  subgraph RUN["🚀 Runtime"]
    direction TB
    R1["Single process · python server.py"]
    R2["Bind 127.0.0.1:8080"]
    R3["No message broker"]
  end

  subgraph SAF["🛡️ Safety"]
    direction TB
    S1["Human-in-the-loop approval gate"]
    S2["Risk enforced in executor.py"]
    S3["Max 1 pending action / server"]
    S4["protected_services block writes"]
  end

  subgraph OPS["🌐 Remote ops"]
    direction TB
    O1["SSH only · paramiko"]
    O2["No daemon on VPS"]
    O3["10s timeout · pooled connections"]
  end

  subgraph DAT["💾 Data"]
    direction TB
    D1["SQLite via store.py only"]
    D2["UTC in DB · local in UI"]
    D3["Snapshots pruned after 7d"]
  end

  subgraph MCP["🔌 MCP contract"]
    direction TB
    M1["Return success + error"]
    M2["Never raise to caller"]
    M3["Claude Desktop via SSE"]
    M4["MCP rejects HIGH risk approvals"]
  end

  subgraph LRN["🧠 Learning"]
    direction TB
    L1["Rejections → feedback_rules"]
    L2["Claude respects on replan"]
  end

  ROOT --> RUN & SAF & OPS & DAT & MCP & LRN

  style ROOT fill:#4338ca,stroke:#312e81,color:#ffffff,stroke-width:2px
  style RUN fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  style SAF fill:#fee2e2,stroke:#b91c1c,color:#0f172a
  style OPS fill:#dcfce7,stroke:#15803d,color:#0f172a
  style DAT fill:#fef3c7,stroke:#b45309,color:#0f172a
  style MCP fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  style LRN fill:#fce7f3,stroke:#be185d,color:#0f172a
  style R1 fill:#bfdbfe,stroke:#1d4ed8,color:#0f172a
  style R2 fill:#bfdbfe,stroke:#1d4ed8,color:#0f172a
  style R3 fill:#bfdbfe,stroke:#1d4ed8,color:#0f172a
  style S1 fill:#fecaca,stroke:#b91c1c,color:#0f172a
  style S2 fill:#fecaca,stroke:#b91c1c,color:#0f172a
  style S3 fill:#fecaca,stroke:#b91c1c,color:#0f172a
  style S4 fill:#fecaca,stroke:#b91c1c,color:#0f172a
  style O1 fill:#bbf7d0,stroke:#15803d,color:#0f172a
  style O2 fill:#bbf7d0,stroke:#15803d,color:#0f172a
  style O3 fill:#bbf7d0,stroke:#15803d,color:#0f172a
  style D1 fill:#fde68a,stroke:#b45309,color:#0f172a
  style D2 fill:#fde68a,stroke:#b45309,color:#0f172a
  style D3 fill:#fde68a,stroke:#b45309,color:#0f172a
  style M1 fill:#ddd6fe,stroke:#6d28d9,color:#0f172a
  style M2 fill:#ddd6fe,stroke:#6d28d9,color:#0f172a
  style M3 fill:#ddd6fe,stroke:#6d28d9,color:#0f172a
  style M4 fill:#ddd6fe,stroke:#6d28d9,color:#0f172a
  style L1 fill:#fbcfe8,stroke:#be185d,color:#0f172a
  style L2 fill:#fbcfe8,stroke:#be185d,color:#0f172a
```

### Component map

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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

  classDef entry fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  classDef observe fill:#dcfce7,stroke:#15803d,color:#0f172a
  classDef reason fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  classDef act fill:#fee2e2,stroke:#b91c1c,color:#0f172a
  classDef realtime fill:#fef3c7,stroke:#b45309,color:#0f172a
  classDef ui fill:#fce7f3,stroke:#be185d,color:#0f172a
  classDef data fill:#e2e8f0,stroke:#475569,color:#0f172a
  class server entry
  class poller,metrics,ssh observe
  class agent reason
  class executor act
  class hub realtime
  class react ui
  class store,schema data
```

### Data model

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a'}}}%%
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
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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
    UI -->|"approve · reject · CONFIRM"| Agent
    MCP -->|"approve LOW/MEDIUM only"| Agent
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

  style Ingest fill:#dcfce7,stroke:#15803d,color:#0f172a
  style DetectPlan fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  style Gate fill:#fef3c7,stroke:#b45309,color:#0f172a
  style Execute fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  classDef node fill:#ffffff,stroke:#64748b,color:#0f172a
  classDef store fill:#e2e8f0,stroke:#475569,color:#0f172a
  class VPS,Poller,Anomaly,Agent,Claude,WS,UI,MCP,Exec,VPS2 node
  class Snap,Base,Inc,Act,Logs store
```

### Approval & risk flow

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','primaryColor':'#e0e7ff','primaryBorderColor':'#6366f1','secondaryColor':'#f8fafc','tertiaryColor':'#ffffff','lineColor':'#475569','textColor':'#0f172a','actorBkg':'#f8fafc','actorBorder':'#64748b','actorTextColor':'#0f172a','actorLineColor':'#475569','signalColor':'#475569','signalTextColor':'#0f172a','labelBoxBkgColor':'#f1f5f9','labelBoxBorderColor':'#64748b','labelTextColor':'#0f172a','loopTextColor':'#0f172a','noteBkgColor':'#fef9c3','noteBorderColor':'#ca8a04','noteTextColor':'#0f172a','activationBorderColor':'#475569','activationBkgColor':'#e2e8f0','sequenceNumberColor':'#0f172a'}}}%%
sequenceDiagram
  autonumber

  box rgb(220,252,231) Ingest
    participant P as poller.py
  end

  box rgb(237,233,254) Agent
    participant A as agent.py
    participant DB as SQLite
  end

  box rgb(254,243,199) Approval gate
    participant WS as WebSocket
    participant UI as Dashboard
    participant MCP as Claude Desktop
  end

  box rgb(219,234,254) Execute
    participant E as executor.py
    participant VPS as VPS
  end

  P->>A: AnomalyEvent
  A->>DB: create_incident
  A->>A: correlate_incident + Claude plan
  A->>DB: proposed_actions (pending)
  A->>WS: action_pending

  alt risk = LOW AND auto_execute enabled AND not protected/sensitive
    A->>E: execute immediately (no approval wait)
  else LOW / MEDIUM / HIGH — human gate required
    A->>A: schedule 60s timer (approval_timeout_seconds)

    opt still pending after 60s
      A->>WS: action_pending_reminder
      Note over WS,MCP: Passive MCP nudge — approve via dashboard<br/>or MCP for LOW/MEDIUM only
    end

    alt risk = LOW or MEDIUM
      par Dashboard path
        UI->>WS: approve_action
        WS->>A: approve (source=dashboard)
      and MCP fallback path
        MCP->>A: approve_action (source=mcp)
        Note over MCP: Allowed for LOW and MEDIUM
      end
    else risk = HIGH — dashboard only
      MCP->>A: approve_action (source=mcp)
      A-->>MCP: reject — HIGH requires dashboard CONFIRM
      UI->>WS: approve_action + confirm_text=CONFIRM
      Note over UI: Sensitive HIGH also requires COMPLIANCE ack
      WS->>A: approve (source=dashboard)
    end

    A->>DB: status = approved
    A->>E: execute_and_finalize
  end

  E->>VPS: SSH / docker (snapshot first)
  E->>WS: action_log_line (stream)
  E->>VPS: health check
  alt health fail
    E->>VPS: rollback
    E->>WS: action_rolled_back
  else health OK
    E->>DB: incident resolved
    E->>WS: incident_resolved
  end
```

### Risk tiers

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
flowchart TD
  Action["ProposedAction"] --> Check{"risk_tier?"}

  Check -->|LOW| Low["Restart container · diagnostics"]
  Check -->|MEDIUM| Med["Compose change · rollback · scale"]
  Check -->|HIGH| High["Arbitrary SSH command"]

  Low --> Auto{"auto_execute_risk_tier: low?<br/>and not protected/sensitive?"}
  Auto -->|yes| Run["executor.py runs"]
  Auto -->|no| LowWait["Dashboard or MCP approval"]

  Med --> MedWait["Dashboard or MCP approval<br/>no CONFIRM required"]

  High --> DashOnly["Dashboard only — MCP rejects"]
  DashOnly --> Confirm["Type CONFIRM to approve"]
  Confirm --> Sensitive{"sensitive service?"}
  Sensitive -->|yes| Compliance["Also type COMPLIANCE"]
  Sensitive -->|no| Run

  LowWait --> Run
  MedWait --> Run
  Compliance --> Run

  Run --> Protected{"service in protected_services?"}
  Protected -->|yes| Block["Blocked even if LOW"]
  Protected -->|no| SSH["SSH execute + health check"]

  style Action fill:#4338ca,stroke:#312e81,color:#ffffff
  style Check fill:#fef3c7,stroke:#b45309,color:#0f172a
  style Low fill:#dcfce7,stroke:#15803d,color:#0f172a
  style Med fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  style High fill:#fee2e2,stroke:#b91c1c,color:#0f172a
  style DashOnly fill:#fecaca,stroke:#b91c1c,color:#0f172a
  style Confirm fill:#991b1b,stroke:#7f1d1d,color:#ffffff
  style Compliance fill:#9a3412,stroke:#7c2d0d,color:#ffffff
  style Run fill:#bbf7d0,stroke:#15803d,color:#0f172a
  style LowWait fill:#dcfce7,stroke:#15803d,color:#0f172a
  style MedWait fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  style Sensitive fill:#fef3c7,stroke:#b45309,color:#0f172a
  style Protected fill:#fef3c7,stroke:#b45309,color:#0f172a
  style Auto fill:#fef3c7,stroke:#b45309,color:#0f172a
  style Block fill:#334155,stroke:#0f172a,color:#ffffff
  style SSH fill:#bbf7d0,stroke:#15803d,color:#0f172a
```

### WebSocket protocol

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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

  style ServerToClient fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  style ClientToServer fill:#dcfce7,stroke:#15803d,color:#0f172a
  style Hub fill:#4338ca,stroke:#312e81,color:#ffffff
  classDef evt fill:#ffffff,stroke:#64748b,color:#0f172a
  class S1,S2,S3,S4,S5,S6,S7,S8,C1,C2,C3 evt
```

### External integrations

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryTextColor':'#0f172a','secondaryTextColor':'#0f172a','tertiaryTextColor':'#0f172a','lineColor':'#475569','textColor':'#0f172a','clusterBkg':'#f8fafc','clusterBorder':'#64748b','titleColor':'#0f172a'}}}%%
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

  classDef agent fill:#dbeafe,stroke:#1d4ed8,color:#0f172a
  classDef external fill:#dcfce7,stroke:#15803d,color:#0f172a
  classDef channel fill:#ede9fe,stroke:#6d28d9,color:#0f172a
  class Poll,Agt,Exe,CICD,Infra agent
  class VPS,GH,AI external
  class CD,BR channel
```

---

## The approval gate

| Tier | Examples | Default behavior |
|------|----------|------------------|
| **Low** | Restart one container, read-only diagnostics | May auto-execute if `auto_execute_risk_tier: low` in `config/rules.yaml` (not on protected/sensitive services) |
| **Medium** | Compose changes, rollback deploy, scale, trigger workflow | Always requires approval — dashboard **or** MCP |
| **High** | Arbitrary SSH | **Dashboard only** — type **CONFIRM**; MCP `approve_action` is rejected |

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
├── fleet_routes.py        # Fleet API: servers, sites, settings
├── fleet_sync.py          # DB ↔ servers.yaml sync
├── onboarding.py          # SSH test, compose discovery, containers
├── uptime_checker.py      # HTTP uptime every 60s
├── poller.py              # 30s SSH health loop
├── agent.py               # Claude observe→plan→gate loop
├── executor.py            # Risk-gated execution orchestration
├── tools/                 # MCP tool implementations
├── db/                    # schema.sql + store.py (only DB access)
├── dashboard/             # React SPA → dist/ (Fleet UI)
├── config/                # servers.yaml, rules.yaml, repos.yaml (gitignored)
└── tests/                 # 60 tests, mocked SSH/GitHub
```

Full original layout: [Project.md](Project.md#4-complete-file-structure).

---

## Product status

Verified locally (2026-06-29):

| Check | Result |
|-------|--------|
| `pytest tests/` | **60 passed** |
| `npm run build` (dashboard) | ✅ |
| `GET /api/fleet/overview` | ✅ sites/servers stats |
| `GET /api/setup/status` | ✅ `product: fleet` |
| Uptime checker + WS `site_update` | ✅ |
| Fleet UI (table, check all, logs) | ✅ |

**Known gaps (planned, not blockers for local use):**

- **Slack/email alerts** — webhook saved in Settings; sender not wired to uptime transitions.
- **Public deploy** — no reverse proxy, TLS, or login yet (`devopsmcp.nevil.ca`).
- **AI features** — optional; require real Anthropic + GitHub tokens in `.env`.
- **Legacy UI pages** — Terraform, Runbooks, old Dashboard still in repo; hidden from main nav.
- **Servers without Docker** — poller errors (e.g. `docker: command not found`); uptime still works if URL is set.

---

## Setup

**Prerequisites:** Python 3.11+, Node 18+, SSH key access to at least one VPS.

```bash
git clone https://github.com/NevilPatel01/DevOpsAI
cd DevOpsAI

python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cd dashboard && npm install && npm run build && cd ..

cp .env.example .env
cp config/repos.yaml.example config/repos.yaml   # optional — for GitHub correlation

python server.py
# → http://127.0.0.1:8080
```

### First run (UI — recommended)

1. Open **http://127.0.0.1:8080** → **Fleet** tab.
2. **Add server** — host, SSH user, key path or upload private key; test connection.
3. **Add site** — client name, URL, pick server, container name (compose path optional).
4. Watch the fleet table — status, HTTP code, latency, and last check update every **60s** (live via WebSocket).

### Legacy YAML path (optional)

```bash
cp config/servers.yaml.example config/servers.yaml
# Edit hosts — imported into DB on first start if DB is empty
```

Set `ANTHROPIC_API_KEY` and `GITHUB_TOKEN` in `.env` when you want AI remediation and deploy correlation.

### Setup checklist

Before relying on the agent, confirm each item:

| Step | Command / action |
|------|------------------|
| Env | `cp .env.example .env` — optional keys for AI/GitHub |
| Dashboard | `cd dashboard && npm install && npm run build` |
| Server | `python server.py` (venv active) |
| Health | `curl -s http://127.0.0.1:8080/api/health` |
| Fleet | `curl -s http://127.0.0.1:8080/api/fleet/overview` |
| Setup | `curl -s http://127.0.0.1:8080/api/setup/status` — `servers_in_db`, `sites_count`, `product: fleet` |

The Fleet page shows a **setup banner** when servers or sites are missing.

**Claude Desktop / Cursor MCP:** connect to `http://127.0.0.1:8080/mcp` (SSE) while `python server.py` is running — see `claude_desktop_config.json`.

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

- **Product pivot:** Optimizing for **daily fleet ops** (uptime, logs, restart) beat showcasing every agent feature in the main nav.
- **Site-first data model:** `sites` + `managed_servers` in SQLite with YAML sync for the legacy poller.
- **Live UX:** WebSocket `site_update` beats polling; fleet table shows everything without drilling into drawers.
- **MCP tool design:** Consistent `{success, error}` contracts; MCP for investigation, dashboard for actions.
- **Human-in-the-loop AI:** Risk tiers enforced in `executor.py`, not only in prompts.
- **Ops realism:** SSH-only on VPS — no daemon on client servers.

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
