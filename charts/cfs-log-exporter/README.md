# CFS Log Exporter Helm Chart

Helm chart for deploying the CFS Log Exporter stack (exporter + receiver/UI) on Kubernetes.

## Installation

```bash
# Deploy both components in a single release
helm install cfs-log ./charts/cfs-log-exporter/ \
  --set apiKey="my-secret-key"

# From OCI registry (when published)
helm install cfs-log oci://ghcr.io/miguelgila/charts/cfs-log-exporter
```

### Deploy components separately

The exporter runs on CSM clusters and the receiver typically runs on a management cluster. Use the `enabled` toggles to deploy them independently:

```bash
# Receiver only (management cluster)
helm install cfs-log ./charts/cfs-log-exporter/ \
  --namespace cfs-log-viewer --create-namespace \
  --set exporter.enabled=false \
  --set apiKey="my-secret-key"

# Exporter only (CSM cluster)
helm install cfs-log ./charts/cfs-log-exporter/ \
  --namespace services \
  --set receiver.enabled=false \
  --set apiKey="my-secret-key" \
  --set exporter.receiverUrl="http://cfs-log-receiver.cfs-log-viewer.svc:8000"
```

## Configuration

### Global

| Parameter | Default | Description |
|-----------|---------|-------------|
| `apiKey` | `changeme` | Shared secret between exporter and receiver |

### Exporter

| Parameter | Default | Description |
|-----------|---------|-------------|
| `exporter.enabled` | `true` | Deploy the exporter |
| `exporter.image.repository` | `ghcr.io/miguelgila/cfs-log-exporter` | Exporter image |
| `exporter.image.tag` | `latest` | Image tag |
| `exporter.receiverUrl` | `http://cfs-log-receiver:8000` | Receiver API URL |
| `exporter.namespace` | `services` | Namespace to watch for CFS pods |
| `exporter.podPrefix` | `cfs-` | Pod name prefix to match |
| `exporter.containerName` | `ansible` | Container to stream logs from |
| `exporter.batchInterval` | `2` | Seconds between batch flushes |
| `exporter.batchSize` | `100` | Max events per batch |
| `exporter.rbac.create` | `true` | Create ServiceAccount and RBAC. Set to `false` on CSM clusters with permissive defaults |
| `exporter.resources.requests.cpu` | `50m` | CPU request |
| `exporter.resources.requests.memory` | `64Mi` | Memory request |
| `exporter.resources.limits.cpu` | `200m` | CPU limit |
| `exporter.resources.limits.memory` | `128Mi` | Memory limit |

### Receiver

| Parameter | Default | Description |
|-----------|---------|-------------|
| `receiver.enabled` | `true` | Deploy the receiver |
| `receiver.image.repository` | `ghcr.io/miguelgila/cfs-log-receiver` | Receiver image |
| `receiver.image.tag` | `latest` | Image tag |
| `receiver.dbPath` | `/data/cfs_logs.db` | SQLite database path |
| `receiver.replicas` | `1` | Number of replicas |
| `receiver.resources.requests.cpu` | `100m` | CPU request |
| `receiver.resources.requests.memory` | `128Mi` | Memory request |
| `receiver.resources.limits.cpu` | `500m` | CPU limit |
| `receiver.resources.limits.memory` | `256Mi` | Memory limit |

#### Service

| Parameter | Default | Description |
|-----------|---------|-------------|
| `receiver.service.type` | `ClusterIP` | Service type |
| `receiver.service.port` | `8000` | Service port |

#### Persistence

| Parameter | Default | Description |
|-----------|---------|-------------|
| `receiver.persistence.enabled` | `true` | Enable PVC for SQLite |
| `receiver.persistence.size` | `5Gi` | Storage size |
| `receiver.persistence.accessMode` | `ReadWriteOnce` | PVC access mode |
| `receiver.persistence.storageClass` | — | Storage class (uses default if empty) |

#### Ingress

| Parameter | Default | Description |
|-----------|---------|-------------|
| `receiver.ingress.enabled` | `false` | Enable ingress |
| `receiver.ingress.className` | `nginx` | Ingress class |
| `receiver.ingress.host` | `cfs-log-viewer.example.com` | Hostname |
| `receiver.ingress.tls.enabled` | `true` | Enable TLS with cert-manager |
| `receiver.ingress.tls.secretName` | — | TLS secret name (auto-generated if empty) |
| `receiver.ingress.tls.issuerRef.kind` | `ClusterIssuer` | cert-manager issuer kind |
| `receiver.ingress.tls.issuerRef.name` | `letsencrypt` | cert-manager issuer name |

## Templates

| Template | Description |
|----------|-------------|
| `secret.yaml` | Shared API key secret |
| `exporter-deployment.yaml` | Exporter Deployment |
| `exporter-rbac.yaml` | ServiceAccount, ClusterRole, ClusterRoleBinding |
| `receiver-deployment.yaml` | Receiver Deployment with health probes |
| `receiver-service.yaml` | Receiver ClusterIP Service |
| `receiver-pvc.yaml` | PersistentVolumeClaim for SQLite |
| `receiver-ingress.yaml` | Ingress + cert-manager Certificate |
