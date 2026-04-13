# CFS Log Exporter

A near-real-time log streaming and parsing system for ALPS CSM Kubernetes clusters. Watches for CFS (Configuration Framework Service) session pods, streams their Ansible logs in real time, parses structured data (hostnames, playbooks, tasks, statuses), and presents them in a filterable React web UI.

## Overview

CFS Log Exporter runs as a two-tier system:

1. **Exporter** (on CSM cluster): Watches the Kubernetes API for CFS pods, streams their container logs, parses Ansible output into structured events, and batches them to a remote receiver over HTTPS.

2. **Receiver** (on remote cluster): Ingests events via a REST API, stores them in SQLite, and serves a React web UI for browsing and filtering CFS sessions.

This allows operations teams to monitor CFS session execution across cluster boundaries in near-real-time.

## Architecture

```
┌──────────────────────────────────────────┐
│         CSM K8s Cluster                  │
│  ┌──────────────────────────────────┐    │
│  │    cfs-* Pods                    │    │
│  │  (Ansible execution)             │    │
│  └──────────┬───────────────────────┘    │
│             │ logs (tail -f)             │
│             ▼                            │
│  ┌──────────────────────────────────┐    │
│  │  cfs-log-exporter Pod            │    │
│  │  - Watch K8s API                 │    │
│  │  - Parse logs with CFSLogParser  │    │
│  │  - Batch events every 2s         │    │
│  └──────────┬───────────────────────┘    │
│             │ HTTPS POST /api/ingest     │
└─────────────┼────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────┐
│    Remote K8s Cluster                    │
│  ┌──────────────────────────────────┐    │
│  │ cfs-log-receiver Pod             │    │
│  │ - FastAPI ingest endpoint        │    │
│  │ - SQLite database                │    │
│  │ - SSE /api/stream for live logs  │    │
│  └──────────────────────────────────┘    │
│             │                            │
│             ▼                            │
│  ┌──────────────────────────────────┐    │
│  │ React Web UI (Vite)              │    │
│  │ - Session list                   │    │
│  │ - Live log stream                │    │
│  │ - Filter by xname, playbook      │    │
│  └──────────────────────────────────┘    │
└──────────────────────────────────────────┘
```

## Components

### Exporter (`exporter/`)
- **parser.py**: Stateful Ansible log parser. Extracts playbooks, plays, tasks, task results, xnames (hardware node names), and status events from raw CFS logs.
- **exporter.py**: Kubernetes watcher. Monitors for CFS pods in a namespace, streams container logs, parses them, batches events, and POSTs to the receiver with retry logic.

**Key features:**
- Extracts xnames from subset lines and task results
- Captures batcher ID for correlation
- Retries with exponential backoff on POST failures
- Waits for container readiness before streaming logs

### Receiver (`receiver/`)
- **app.py**: FastAPI application. Exposes REST API for ingesting events, querying sessions, and streaming live logs via SSE.
- **models.py**: SQLAlchemy models for sessions and log lines. SQLite database schema.

**Key endpoints:**
- `POST /api/ingest`: Receive batched events from exporter
- `GET /api/sessions`: List all sessions
- `GET /api/sessions/{uuid}`: Get session metadata and all logs
- `GET /api/stream/{uuid}`: SSE stream of live logs for a session
- `GET /api/health`: Health check for K8s probes

### Frontend (`frontend/`)
- **React + Vite**: Single-page app for browsing sessions and logs.
- **SessionList**: Shows all captured CFS sessions with xname counts, playbooks, and timing.
- **SessionDetail**: Displays parsed logs for a session with live updates and filtering.
- **FilterBar**: Filter logs by xname, playbook, task name, or status.

## Quick Start (Local Development)

### Prerequisites
- Python 3.10+
- Node.js 18+
- `kubeconfig` with access to a CSM cluster

### Option 1: Run Local Script (recommended)

The `run_local.sh` script starts both the receiver and exporter in one command:

```bash
./scripts/run_local.sh
```

This will:
- Create a Python virtualenv and install dependencies
- Build the frontend (on first run)
- Start the receiver on `http://localhost:8000`
- Start the exporter connected to your local kubeconfig cluster

### Option 2: Manual Setup

**1. Install dependencies:**

```bash
# Receiver
cd receiver
pip install -r requirements.txt

# Frontend (from project root)
cd frontend
npm install
```

**2. Start receiver (development):**

```bash
cd receiver
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

**3. Start frontend (development):**

```bash
cd frontend
npm run dev
```

Frontend will run on `http://localhost:5173`, API on `http://localhost:8000`.

**4. Open browser:**

```bash
open http://localhost:5173
```

## Deployment

Pre-built container images are publicly available on GitHub Container Registry:

- `ghcr.io/miguelgila/cfs-log-exporter:latest`
- `ghcr.io/miguelgila/cfs-log-receiver:latest`

Tagged releases are also available (e.g., `ghcr.io/miguelgila/cfs-log-exporter:v0.0.6`).

Example Kubernetes manifests are provided in the [`k8s/`](k8s/) directory. See the [k8s README](k8s/README.md) for a full walkthrough.

### Deploy Receiver (management cluster)

```bash
kubectl create namespace cfs-log-viewer
kubectl apply -f k8s/receiver/
```

Edit `k8s/receiver/secret.yaml` and `k8s/receiver/ingress.yaml` with your API key and hostname before applying.

### Deploy Exporter (each CSM cluster)

Edit `k8s/exporter/deployment.yaml` to set `RECEIVER_URL` pointing to the receiver, then:

```bash
kubectl apply -f k8s/exporter/
```

### Verify

```bash
# Receiver health
curl https://your-receiver-hostname/api/health

# Exporter logs
kubectl logs -f deployment/cfs-log-exporter -n services

# Receiver logs
kubectl logs -f deployment/cfs-log-receiver -n cfs-log-viewer
```

## Configuration

### Exporter Environment Variables

Set these in the exporter deployment:

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIVER_URL` | `http://localhost:8000` | Base URL of the receiver API (use HTTPS in production) |
| `API_KEY` | `changeme` | Bearer token for authenticating requests to receiver |
| `NAMESPACE` | `services` | Kubernetes namespace to watch for CFS pods |
| `POD_PREFIX` | `cfs-` | Pod name prefix to match |
| `CONTAINER_NAME` | `ansible` | Container name within pod to stream logs from |
| `BATCH_INTERVAL` | `2` | Seconds between batches sent to receiver |
| `BATCH_SIZE` | `100` | Maximum events per batch |
| `IN_CLUSTER` | `true` | Use Kubernetes in-cluster auth (`false` uses kubeconfig) |

### Receiver Environment Variables

Set these in the receiver deployment:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `/data/cfs_logs.db` | Path to SQLite database file |
| `API_KEY` | `changeme` | Bearer token for validating ingest requests |

Ensure both exporter and receiver use the same `API_KEY`.

## API Reference

### POST /api/ingest
Receive a batch of parsed events from the exporter.

**Headers:**
```
Authorization: Bearer {API_KEY}
```

**Request body:**
```json
{
  "session": {
    "session_uuid": "c452edd0-7b87-4af1-b4c4-65d988cc694b",
    "pod_name": "cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc",
    "batcher_id": "1dfcf57d-064c-42e0-9f6a-63e4be92c924",
    "xnames": ["x1300c7s5b0n0", "x1102c7s1b1n0"],
    "playbooks": ["csm_packages.yml"],
    "started_at": "2026-04-07T10:45:30",
    "ended_at": "2026-04-07T10:45:53",
    "status": "completed"
  },
  "events": [
    {
      "event_type": "playbook_start",
      "line_number": 42,
      "raw_line": "Running csm_packages.yml from repo https://...",
      "playbook": "csm_packages.yml",
      "repo_url": "https://api-gw-service-nmn.local/vcs/cray/csm-config-management.git"
    },
    {
      "event_type": "task_result",
      "line_number": 156,
      "raw_line": "changed: [x1300c7s5b0n0]",
      "playbook": "csm_packages.yml",
      "task_name": "Apply package updates",
      "status": "changed",
      "xname": "x1300c7s5b0n0"
    }
  ]
}
```

**Response:**
```json
{
  "session_uuid": "c452edd0-7b87-4af1-b4c4-65d988cc694b",
  "lines_inserted": 42,
  "status": "ok"
}
```

### GET /api/sessions
List all captured CFS sessions.

**Query parameters:**
- `limit` (optional, default 100): Maximum number of sessions
- `offset` (optional, default 0): Pagination offset

**Response:**
```json
{
  "sessions": [
    {
      "session_uuid": "c452edd0-7b87-4af1-b4c4-65d988cc694b",
      "pod_name": "cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc",
      "batcher_id": "1dfcf57d-064c-42e0-9f6a-63e4be92c924",
      "xnames": ["x1300c7s5b0n0", "x1102c7s1b1n0"],
      "playbooks": ["csm_packages.yml", "gpu_customize_driver_playbook.yml"],
      "started_at": "2026-04-07T10:45:30",
      "ended_at": "2026-04-07T10:45:53",
      "status": "completed",
      "line_count": 42
    }
  ]
}
```

### GET /api/sessions/{uuid}
Get session metadata and all parsed log events.

**Response:**
```json
{
  "session": {
    "session_uuid": "c452edd0-7b87-4af1-b4c4-65d988cc694b",
    "pod_name": "cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc",
    "batcher_id": "1dfcf57d-064c-42e0-9f6a-63e4be92c924",
    "xnames": ["x1300c7s5b0n0", "x1102c7s1b1n0"],
    "playbooks": ["csm_packages.yml"],
    "started_at": "2026-04-07T10:45:30",
    "ended_at": "2026-04-07T10:45:53",
    "status": "completed"
  },
  "events": [
    {
      "event_type": "playbook_start",
      "line_number": 42,
      "raw_line": "Running csm_packages.yml...",
      "timestamp": "2026-04-07T10:45:30",
      "playbook": "csm_packages.yml"
    }
  ]
}
```

### GET /api/stream/{uuid}
Server-sent events (SSE) stream of live logs for a session.

**Usage (JavaScript):**
```javascript
const eventSource = new EventSource('/api/stream/c452edd0-7b87-4af1-b4c4-65d988cc694b');
eventSource.onmessage = (event) => {
  const logEvent = JSON.parse(event.data);
  console.log(logEvent);
};
```

### GET /api/health
Health check for Kubernetes probes.

**Response:** HTTP 200 OK

## Log Parsing Details

The parser extracts the following data from Ansible CFS logs:

### EventTypes

| Type | When emitted | Example raw line |
|------|-------------|------------------|
| `playbook_start` | Playbook execution begins | `Running csm_packages.yml from repo https://...` |
| `play_start` | Play within playbook starts | `PLAY [Compute:&cfs_image] **********` |
| `task_start` | Task within play starts | `TASK [role_name : task description] **********` |
| `task_result` | Task completes on a host | `changed: [x1300c7s5b0n0]` or `ok: [x1102c7s1b1n0] => (item=eth0)` |
| `play_recap` | Play summary line | `PLAY RECAP *****` |
| `warning` | Ansible warning line | `[WARNING]: Could not match supplied host pattern` |
| `info` | Other notable lines | Inventory generation, sidecar availability |

### Extracted Fields

| Field | Source | Example |
|-------|--------|---------|
| `xname` | Task results or subset lines | `x1300c7s5b0n0` (hardware node name) |
| `playbook` | Playbook start line | `csm_packages.yml` |
| `repo_url` | Playbook start line | `https://api-gw-service-nmn.local/vcs/cray/csm-config-management.git` |
| `play_name` | Play start line | `Compute:&cfs_image` |
| `role` | Task name line (before colon) | `role_name` (if task has role prefix) |
| `task_name` | Task start line | `task description` |
| `status` | Task result line | `ok`, `changed`, `failed`, `fatal`, `skipping`, `unreachable` |
| `item` | Task result with item loop | `eth0` (from `(item=eth0)`) |
| `batcher_id` | Log context | `1dfcf57d-064c-42e0-9f6a-63e4be92c924` (from batcher labels) |
| `timestamp` | Log timestamp lines | Extracted from lines like `Tuesday 07 April 2026  10:45:30 +0000` |

### Noise Filtering

The parser ignores these low-value lines:
- HTTP headers and responses
- Progress bars (curl `%` output)
- SSH key messages
- Separator lines (`~~~`, `===`, `---`)
- Failed patch attempts
- "Playbook run took" summary

These are not stored in the database, reducing noise in the UI.

## Development

### Project Structure

```
.
├── exporter/
│   ├── parser.py          # CFS log parser
│   ├── exporter.py        # K8s watcher and event sender
│   ├── test_parser.py     # Parser unit tests
│   ├── requirements.txt
│   └── Dockerfile
├── receiver/
│   ├── app.py             # FastAPI app (API + staleness reconciler)
│   ├── models.py          # SQLAlchemy models
│   ├── test_reconciler.py # Reconciler unit tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx        # Main app with browser history navigation
│   │   ├── App.test.tsx   # Navigation unit tests
│   │   └── components/
│   │       ├── SessionList.tsx
│   │       ├── SessionDetail.tsx
│   │       ├── FilterBar.tsx
│   │       └── LogStream.tsx
│   ├── package.json
│   └── vite.config.ts
├── k8s/
│   ├── exporter/          # K8s manifests for the exporter
│   └── receiver/          # K8s manifests for the receiver + UI
├── scripts/
│   └── run_local.sh       # Run full stack locally
└── .github/workflows/
    ├── test.yml           # CI: unit tests + type checks
    ├── build-images.yml   # Build container images (push on release tags)
    └── release.yml        # GitHub releases
```

### Testing

Unit tests are run automatically in CI on every PR. To run locally:

```bash
# Exporter parser tests
cd exporter && python3 -m pytest test_parser.py -v

# Receiver reconciler tests
cd receiver && python3 -m pytest test_reconciler.py -v

# Frontend tests (type-check + vitest)
cd frontend && npx tsc -b --noEmit && npm test
```

## Troubleshooting

### Exporter not connecting to receiver

1. Check exporter logs:
   ```bash
   kubectl logs -f deployment/cfs-log-exporter -n services
   ```

2. Verify receiver is running:
   ```bash
   curl https://your-receiver-hostname/api/health
   ```

3. Check network connectivity from exporter pod:
   ```bash
   kubectl exec -it deployment/cfs-log-exporter -n services -- \
     curl -v https://your-receiver-hostname/api/health
   ```

4. Verify API keys match:
   ```bash
   kubectl get secret cfs-log-exporter -n services -o jsonpath='{.data.api-key}' | base64 -d
   kubectl get secret cfs-log-receiver -o jsonpath='{.data.api-key}' | base64 -d
   ```

### No logs appearing in UI

1. Check that events were ingested:
   ```bash
   curl -X GET http://your-receiver-hostname/api/sessions
   ```

2. Check receiver logs:
   ```bash
   kubectl logs -f deployment/cfs-log-receiver
   ```

3. Verify database has data:
   ```bash
   kubectl exec -it deployment/cfs-log-receiver -- sqlite3 /data/cfs_logs.db
   sqlite> SELECT COUNT(*) FROM log_lines;
   ```

### Parser not recognizing xnames or playbooks

1. Check the sample log format matches expected patterns (see regex patterns in `exporter/parser.py`)
2. Ensure pod names match the pattern `cfs-<uuid>-*` for session ID extraction
3. Look for "batcher-" and "subset:" in the logs for batcher ID and xname extraction

## Notes for Operations

- **Real-time updates**: The web UI uses SSE to stream live logs as the exporter sends them. The stream connection has a 1-hour timeout (configurable in ingress).

- **Database growth**: SQLite logs can grow with many CFS sessions. Monitor disk usage and plan for cleanup of old logs if needed. Consider archiving sessions to S3 or similar after a retention period.

- **API key rotation**: To rotate the API key, update both the exporter and receiver secrets and redeploy.

- **Network security**: The exporter->receiver connection uses HTTPS. Ensure TLS certificates are valid and expiration is monitored.

- **Scalability**: Currently runs single replicas on both clusters. For higher volume, consider adding database replication and load balancing the receiver API.
