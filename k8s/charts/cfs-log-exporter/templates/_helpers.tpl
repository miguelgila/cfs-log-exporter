{{/*
Common labels
*/}}
{{- define "cfs-log-exporter.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end }}

{{/*
Exporter labels
*/}}
{{- define "cfs-log-exporter.exporter.labels" -}}
{{ include "cfs-log-exporter.labels" . }}
app.kubernetes.io/name: cfs-log-exporter
app.kubernetes.io/component: exporter
{{- end }}

{{/*
Receiver labels
*/}}
{{- define "cfs-log-exporter.receiver.labels" -}}
{{ include "cfs-log-exporter.labels" . }}
app.kubernetes.io/name: cfs-log-receiver
app.kubernetes.io/component: receiver
{{- end }}

{{/*
Exporter selector labels
*/}}
{{- define "cfs-log-exporter.exporter.selectorLabels" -}}
app.kubernetes.io/name: cfs-log-exporter
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: exporter
{{- end }}

{{/*
Receiver selector labels
*/}}
{{- define "cfs-log-exporter.receiver.selectorLabels" -}}
app.kubernetes.io/name: cfs-log-receiver
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: receiver
{{- end }}
