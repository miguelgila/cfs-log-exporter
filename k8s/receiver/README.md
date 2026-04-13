# Receiver Manifests

Deploys the CFS Log Receiver (API + web UI) on a management cluster or any Kubernetes environment.

## Files

| File | Description |
|------|-------------|
| `deployment.yaml` | Receiver Deployment with health probes and persistent storage |
| `service.yaml` | ClusterIP Service exposing port 8000 |
| `pvc.yaml` | PersistentVolumeClaim for the SQLite database |
| `secret.yaml` | API key for authenticating ingest requests |
| `ingress.yaml` | (Optional) Ingress with cert-manager TLS certificate |

## Configuration

Key environment variables in `deployment.yaml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | — | Shared secret for authenticating exporters (from Secret) |
| `DB_PATH` | `/data/cfs_logs.db` | Path to the SQLite database file |

## Ingress

The `ingress.yaml` includes both a cert-manager `Certificate` and an nginx `Ingress` resource. Edit the following before applying:

- Replace `cfs-log-viewer.example.com` with your actual hostname
- Adjust the `ClusterIssuer` name if yours differs from `letsencrypt`
- Modify annotations as needed for your ingress controller

The ingress is optional — the receiver can also be accessed via port-forwarding:

```bash
kubectl port-forward -n cfs-log-viewer svc/cfs-log-receiver 8000:8000
```

## Storage

The PVC defaults to 5Gi with `ReadWriteOnce` access. Uncomment and set `storageClassName` if your cluster requires a specific storage class.
