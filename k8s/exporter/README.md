# Exporter Manifests

Deploys the CFS Log Exporter on a CSM cluster. It watches for CFS pods in the target namespace, streams their Ansible logs, and sends parsed events to the receiver.

## Files

| File | Description |
|------|-------------|
| `deployment.yaml` | Exporter Deployment with environment configuration |
| `rbac.yaml` | ServiceAccount, ClusterRole, and ClusterRoleBinding |
| `secret.yaml` | API key for authenticating with the receiver |

## Configuration

Key environment variables in `deployment.yaml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIVER_URL` | — | URL of the receiver API (required) |
| `NAMESPACE` | `services` | Namespace where CFS pods run |
| `POD_PREFIX` | `cfs-` | Pod name prefix to watch |
| `CONTAINER_NAME` | `ansible` | Container to stream logs from |
| `BATCH_INTERVAL` | `2` | Seconds between batch flushes |
| `BATCH_SIZE` | `100` | Max events per batch |

## RBAC

The RBAC manifest creates a ServiceAccount with permissions to watch/list pods, read pod logs, and read ConfigMaps (for cluster name auto-detection).

On CSM clusters with permissive defaults, the default service account may already have these permissions — in that case `rbac.yaml` is optional. It is included to document the minimum required permissions and to support clusters with stricter RBAC policies.
