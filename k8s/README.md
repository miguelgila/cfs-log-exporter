# Kubernetes Deployment

Example manifests for deploying the CFS Log Exporter stack on Kubernetes.

## Architecture

```
CSM Cluster(s)              Management Cluster
┌─────────────────┐         ┌──────────────────────┐
│  cfs-log-exporter│ ──────> │  cfs-log-receiver    │
│  (watches CFS   │  HTTP   │  (API + UI + SQLite) │
│   pods, streams │         │                      │
│   logs)         │         │  Ingress (optional)  │
└─────────────────┘         └──────────────────────┘
```

- **Exporter** runs on each CSM cluster being monitored. It watches for CFS pods, parses their Ansible logs, and sends structured events to the receiver.
- **Receiver** runs on any cluster (or standalone). It stores sessions in SQLite and serves the web UI.

## Quick Start

1. **Edit secrets** — replace the base64-encoded `api-key` in both `exporter/secret.yaml` and `receiver/secret.yaml` with a matching strong secret:

   ```bash
   echo -n "my-strong-secret" | base64
   ```

2. **Deploy the receiver** (on your management cluster):

   ```bash
   kubectl create namespace cfs-log-viewer
   kubectl apply -f receiver/
   ```

3. **Deploy the exporter** (on each CSM cluster):

   Update `RECEIVER_URL` in `exporter/deployment.yaml` to point to the receiver service, then:

   ```bash
   kubectl apply -f exporter/
   ```

4. **(Optional) Configure Ingress** — edit `receiver/ingress.yaml` with your hostname and TLS settings.

## Subdirectories

- [`exporter/`](exporter/) — Exporter deployment, RBAC, and secret
- [`receiver/`](receiver/) — Receiver deployment, service, PVC, ingress, and secret
