"""
CFS Log Exporter - K8s Pod Log Watcher

Watches for CFS pods on a CSM K8s cluster, streams their Ansible logs,
parses them into structured events, and POSTs batches to a remote receiver.

Resilience:
- POST failures: retries indefinitely with backoff (pauses streaming until receiver
  is reachable, so no lines are dropped while the receiver is temporarily down).
- K8s stream drops: reconnects using since_time= set to the last successfully
  flushed timestamp, so missed lines are re-fetched from the API server.
- Pod watch reconnect: resumes from last resource_version on 410/network errors.
"""

import asyncio
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from kubernetes_asyncio import client, config, watch

from parser import CFSLogParser, RE_XNAME

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
RECEIVER_URL = os.environ.get("RECEIVER_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "changeme")
NAMESPACE = os.environ.get("NAMESPACE", "services")
POD_PREFIX = os.environ.get("POD_PREFIX", "cfs-")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "ansible")
BATCH_INTERVAL = int(os.environ.get("BATCH_INTERVAL", "2"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))
IN_CLUSTER = os.environ.get("IN_CLUSTER", "true").lower() == "true"
CLUSTER_NAME = os.environ.get("CLUSTER_NAME") or None  # e.g. "system1", "system2"

# Retry / backoff constants
MAX_CONTAINER_WAIT = 600        # seconds to wait for container readiness
CONTAINER_POLL_INTERVAL = 5     # seconds between container-ready polls
POST_INITIAL_BACKOFF = 1        # seconds
POST_MAX_BACKOFF = 30           # seconds (retries indefinitely, no give-up)
STREAM_RECONNECT_DELAY = 3      # seconds between stream reconnect attempts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("cfs-exporter")

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
active_pods: dict[str, asyncio.Task] = {}
shutdown_event = asyncio.Event()
_shutdown_started = False
http_client: Optional[httpx.AsyncClient] = None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def post_batch(
    session_dict: dict,
    events: list[dict],
    status: str,
) -> None:
    """POST a batch of events to the receiver, retrying indefinitely until success.

    Streaming is paused (this coroutine blocks) while the receiver is unreachable,
    so no lines are dropped. Exits immediately if shutdown is requested.
    """
    assert http_client is not None

    if not events and status == "running":
        return  # nothing to send

    payload = {
        "session": {
            "session_uuid": session_dict.get("session_id"),
            "pod_name": session_dict.get("pod_name"),
            "batcher_id": session_dict.get("batcher_id"),
            "cluster": CLUSTER_NAME,
            "xnames": session_dict.get("xnames", []),
            "playbooks": session_dict.get("playbooks", []),
            "started_at": session_dict.get("started_at"),
            "ended_at": session_dict.get("ended_at"),
            "status": status,
        },
        "events": events,
    }

    url = f"{RECEIVER_URL.rstrip('/')}/api/ingest"
    backoff = POST_INITIAL_BACKOFF
    attempt = 0

    while not shutdown_event.is_set():
        attempt += 1
        try:
            resp = await http_client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            if resp.status_code < 300:
                log.info(
                    "Sent batch: pod=%s events=%d status=%s (HTTP %d)",
                    session_dict.get("pod_name"),
                    len(events),
                    status,
                    resp.status_code,
                )
                return
            log.warning(
                "Receiver returned HTTP %d for pod=%s (attempt %d): %s",
                resp.status_code,
                session_dict.get("pod_name"),
                attempt,
                resp.text[:200],
            )
        except (httpx.HTTPError, OSError) as exc:
            log.warning(
                "POST failed for pod=%s (attempt %d): %s — retrying in %ds",
                session_dict.get("pod_name"),
                attempt,
                exc,
                backoff,
            )

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, POST_MAX_BACKOFF)


# ---------------------------------------------------------------------------
# Container readiness
# ---------------------------------------------------------------------------

async def wait_for_container_ready(
    v1: client.CoreV1Api,
    pod_name: str,
    namespace: str,
    container: str,
) -> bool:
    """Poll pod status until the target container is running. Returns True on success."""
    deadline = time.monotonic() + MAX_CONTAINER_WAIT
    interval = CONTAINER_POLL_INTERVAL

    while time.monotonic() < deadline:
        if shutdown_event.is_set():
            return False
        try:
            pod = await v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            if pod.status and pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    if cs.name == container and cs.state:
                        if cs.state.running:
                            log.info(
                                "Container %s in pod %s is running",
                                container,
                                pod_name,
                            )
                            return True
                        if cs.state.terminated:
                            log.info(
                                "Container %s in pod %s already terminated",
                                container,
                                pod_name,
                            )
                            return True
        except client.exceptions.ApiException as exc:
            log.warning(
                "Error polling pod %s status: %s", pod_name, exc.reason
            )

        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 30)

    log.error(
        "Timed out waiting for container %s in pod %s", container, pod_name
    )
    return False


# ---------------------------------------------------------------------------
# Per-pod log streaming task
# ---------------------------------------------------------------------------

async def stream_pod_logs(pod_name: str, target_xnames: list[str] | None = None) -> None:
    """Stream and parse logs for a single CFS pod, batching events to the receiver.

    Reconnects the K8s log stream on network errors, using since_time= to resume
    from the last successfully flushed timestamp (avoids re-sending already-sent
    lines in most cases; receiver deduplicates by line_number if any overlap).
    """
    log.info("Starting log stream for pod %s", pod_name)
    parser = CFSLogParser(pod_name=pod_name)
    # Pre-seed xnames from pod spec (ANSIBLE_ARGS --limit)
    if target_xnames:
        parser.xnames.update(target_xnames)
    event_buffer: list[dict] = []
    line_number = 0
    final_status = "completed"

    # Tracks the last timestamp at which we successfully POSTed a batch.
    # Used as since_time= on stream reconnects so we don't lose lines.
    last_flushed_at: Optional[datetime] = None

    if IN_CLUSTER:
        await config.load_incluster_config()
    else:
        await config.load_kube_config()

    async with client.ApiClient() as api:
        v1 = client.CoreV1Api(api)

        # Wait for container readiness
        ready = await wait_for_container_ready(
            v1, pod_name, NAMESPACE, CONTAINER_NAME
        )
        if not ready:
            log.error("Abandoning pod %s - container never became ready", pod_name)
            return

        # Helper: flush buffer to receiver (blocks until POST succeeds)
        async def flush_buffer(status: str = "running") -> None:
            nonlocal event_buffer, last_flushed_at
            if not event_buffer:
                return
            session_info = parser.get_session_info().to_dict()
            await post_batch(session_info, list(event_buffer), status)
            event_buffer.clear()
            # Record the wall-clock time of the last successful flush so we can
            # use it as since_time= if we need to reconnect the K8s stream.
            last_flushed_at = datetime.now(timezone.utc)

        # Helper: flush on interval (runs as a background task)
        async def periodic_flush() -> None:
            while not shutdown_event.is_set():
                await asyncio.sleep(BATCH_INTERVAL)
                await flush_buffer("running")

        flush_task = asyncio.create_task(periodic_flush())

        # Read completed init/sidecar container logs before streaming ansible
        for pre_container in ["git-clone", "inventory"]:
            try:
                resp = await v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=NAMESPACE,
                    container=pre_container,
                    _preload_content=False,
                )
                content = await resp.content.read()
                text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
                for raw_line in text.splitlines():
                    line_number += 1
                    event = parser.parse_line(line_number, raw_line)
                    if event is not None:
                        event.container = pre_container
                        event_buffer.append(event.to_dict())
            except Exception as exc:
                log.debug("Could not read %s logs for pod %s: %s", pre_container, pod_name, exc)

        # Reconnect loop: keeps re-opening the K8s log stream on failures
        stream_disconnect_since: float | None = None
        stream_last_warned: float = 0
        while not shutdown_event.is_set():
            try:
                kwargs: dict = {
                    "name": pod_name,
                    "namespace": NAMESPACE,
                    "container": CONTAINER_NAME,
                    "follow": True,
                    "_preload_content": False,
                }
                if last_flushed_at is not None:
                    # Resume from last successfully flushed point.
                    # Kubernetes returns logs with timestamp >= since_time.
                    # The receiver deduplicates by line_number, so any overlap is fine.
                    kwargs["since_time"] = last_flushed_at.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    log.info(
                        "Reconnecting stream for pod %s (since_time=%s, lines_so_far=%d)",
                        pod_name,
                        kwargs["since_time"],
                        line_number,
                    )

                resp = await v1.read_namespaced_pod_log(**kwargs)

                if stream_disconnect_since is not None:
                    elapsed = int(time.monotonic() - stream_disconnect_since)
                    log.info(
                        "Stream reconnected for pod %s after %dm %ds",
                        pod_name, elapsed // 60, elapsed % 60,
                    )
                    stream_disconnect_since = None

                async for raw_line in resp.content:
                    if shutdown_event.is_set():
                        final_status = "running"
                        break

                    line_text = (
                        raw_line.decode("utf-8", errors="replace")
                        if isinstance(raw_line, bytes)
                        else raw_line
                    )

                    for single_line in line_text.splitlines():
                        line_number += 1
                        event = parser.parse_line(line_number, single_line)
                        if event is not None:
                            event.container = "ansible"
                            event_buffer.append(event.to_dict())

                        if len(event_buffer) >= BATCH_SIZE:
                            await flush_buffer("running")

                # Stream ended cleanly (pod finished)
                log.info("Log stream ended for pod %s (lines=%d)", pod_name, line_number)
                break

            except client.exceptions.ApiException as exc:
                if exc.status == 404:
                    log.info("Pod %s no longer exists, stream complete", pod_name)
                    break
                now = time.monotonic()
                if stream_disconnect_since is None:
                    stream_disconnect_since = now
                    stream_last_warned = now
                    log.warning(
                        "K8s API error streaming pod %s: %s — will retry",
                        pod_name, exc.reason,
                    )
                elif now - stream_last_warned >= 300:
                    elapsed = int(now - stream_disconnect_since)
                    log.warning(
                        "Still unable to stream pod %s (disconnected %dm %ds): %s",
                        pod_name, elapsed // 60, elapsed % 60, exc.reason,
                    )
                    stream_last_warned = now
            except Exception as exc:
                now = time.monotonic()
                if stream_disconnect_since is None:
                    stream_disconnect_since = now
                    stream_last_warned = now
                    log.warning(
                        "Stream error for pod %s: %s — will retry",
                        pod_name, exc,
                    )
                elif now - stream_last_warned >= 300:
                    elapsed = int(now - stream_disconnect_since)
                    log.warning(
                        "Still unable to stream pod %s (disconnected %dm %ds): %s",
                        pod_name, elapsed // 60, elapsed % 60, exc,
                    )
                    stream_last_warned = now

            if not shutdown_event.is_set():
                await asyncio.sleep(STREAM_RECONNECT_DELAY)

        # Determine final status
        if shutdown_event.is_set():
            final_status = "running"

        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass

        # Send any remaining events with final status
        if final_status == "completed":
            parser.last_seen_timestamp = (
                parser.last_seen_timestamp or datetime.now(timezone.utc)
            )
        session_info = parser.get_session_info().to_dict()
        await post_batch(session_info, list(event_buffer), final_status)
        event_buffer.clear()

        log.info(
            "Finished streaming pod %s (status=%s, lines=%d)",
            pod_name,
            final_status,
            line_number,
        )


def _task_done_callback(pod_name: str, task: asyncio.Task) -> None:
    """Remove completed pod tasks from the active set."""
    active_pods.pop(pod_name, None)
    if not task.cancelled() and task.exception():
        log.error(
            "Task for pod %s ended with exception: %s",
            pod_name,
            task.exception(),
        )


# ---------------------------------------------------------------------------
# Main pod watcher
# ---------------------------------------------------------------------------

def _extract_target_xnames(pod) -> list[str]:
    """Extract target xnames from the ANSIBLE_ARGS env var in the ansible container."""
    try:
        for container in pod.spec.containers or []:
            if container.name != CONTAINER_NAME:
                continue
            for env in container.env or []:
                if env.name != "ANSIBLE_ARGS":
                    continue
                # Parse --limit value: could be single xname or comma-separated
                parts = (env.value or "").split()
                for i, part in enumerate(parts):
                    if part == "--limit" and i + 1 < len(parts):
                        candidates = parts[i + 1].split(",")
                        return [c for c in candidates if RE_XNAME.fullmatch(c)]
    except Exception:
        pass
    return []


async def _detect_cluster_name(v1: client.CoreV1Api) -> str | None:
    """Try to read the CSM cluster domain from the cray-dns-unbound ConfigMap.

    Falls back to None if the ConfigMap is absent or unparseable.
    The ConfigMap lives in the same namespace as the exporter (services),
    so no extra RBAC beyond what is already in the deployment manifests.
    """
    try:
        cm = await v1.read_namespaced_config_map("cray-dns-unbound", NAMESPACE)
        conf = (cm.data or {}).get("unbound.conf", "")
        m = re.search(r"^\s*domain_name:\s*(\S+)", conf, re.MULTILINE)
        if m:
            return m.group(1)
    except Exception as exc:
        log.debug("cray-dns-unbound lookup failed: %s", exc)
    return None


async def watch_pods() -> None:
    """Watch for CFS pods and spawn a streaming task for each new one."""
    global CLUSTER_NAME
    if IN_CLUSTER:
        await config.load_incluster_config()
    else:
        await config.load_kube_config()

    async with client.ApiClient() as api:
        v1 = client.CoreV1Api(api)
        resource_version: Optional[str] = None

        if CLUSTER_NAME is None:
            CLUSTER_NAME = await _detect_cluster_name(v1)
            if CLUSTER_NAME:
                log.info("Auto-detected cluster name from cray-dns-unbound: %s", CLUSTER_NAME)
            elif not IN_CLUSTER:
                try:
                    _, active_ctx = config.list_kube_config_contexts()
                    CLUSTER_NAME = active_ctx["context"]["cluster"]
                    log.info("Auto-detected cluster name from kubeconfig: %s", CLUSTER_NAME)
                except Exception as exc:
                    log.warning("Could not auto-detect cluster name: %s", exc)

        watch_disconnect_since: float | None = None
        watch_last_warned: float = 0

        while not shutdown_event.is_set():
            log.info(
                "Starting pod watch in namespace=%s prefix=%s (rv=%s)",
                NAMESPACE,
                POD_PREFIX,
                resource_version or "latest",
            )
            w = watch.Watch()
            try:
                kwargs: dict = {
                    "namespace": NAMESPACE,
                    "timeout_seconds": 600,
                }
                if resource_version:
                    kwargs["resource_version"] = resource_version

                async for event in w.stream(
                    v1.list_namespaced_pod, **kwargs
                ):
                    if watch_disconnect_since is not None:
                        elapsed = int(time.monotonic() - watch_disconnect_since)
                        log.info(
                            "Pod watch reconnected after %dm %ds",
                            elapsed // 60, elapsed % 60,
                        )
                        watch_disconnect_since = None

                    if shutdown_event.is_set():
                        break

                    evt_type = event["type"]
                    pod = event["object"]
                    pod_name: str = pod.metadata.name
                    resource_version = pod.metadata.resource_version

                    if not pod_name.startswith(POD_PREFIX):
                        continue

                    if evt_type in ("ADDED", "MODIFIED"):
                        if pod_name not in active_pods:
                            # Extract target xnames from ANSIBLE_ARGS --limit
                            target_xnames = _extract_target_xnames(pod)
                            log.info(
                                "Detected CFS pod %s (event=%s, phase=%s, targets=%s)",
                                pod_name,
                                evt_type,
                                pod.status.phase if pod.status else "Unknown",
                                target_xnames or "none",
                            )
                            task = asyncio.create_task(
                                stream_pod_logs(pod_name, target_xnames=target_xnames),
                                name=f"stream-{pod_name}",
                            )
                            task.add_done_callback(
                                lambda t, pn=pod_name: _task_done_callback(pn, t)
                            )
                            active_pods[pod_name] = task

            except client.exceptions.ApiException as exc:
                if exc.status == 410:
                    log.warning(
                        "Watch returned 410 Gone - resetting resource_version"
                    )
                    resource_version = None
                else:
                    now = time.monotonic()
                    if watch_disconnect_since is None:
                        watch_disconnect_since = now
                        watch_last_warned = now
                        log.error("Lost connection to K8s API: %s — will retry", exc.reason)
                    elif now - watch_last_warned >= 300:
                        elapsed = int(now - watch_disconnect_since)
                        log.error(
                            "Still disconnected from K8s API (for %dm %ds): %s",
                            elapsed // 60, elapsed % 60, exc.reason,
                        )
                        watch_last_warned = now
                    await asyncio.sleep(5)
            except Exception as exc:
                now = time.monotonic()
                if watch_disconnect_since is None:
                    watch_disconnect_since = now
                    watch_last_warned = now
                    log.error("Lost connection to K8s API: %s — will retry", exc)
                elif now - watch_last_warned >= 300:
                    elapsed = int(now - watch_disconnect_since)
                    log.error(
                        "Still disconnected from K8s API (for %dm %ds): %s",
                        elapsed // 60, elapsed % 60, exc,
                    )
                    watch_last_warned = now
                await asyncio.sleep(5)
            finally:
                await w.close()

            # Brief pause before reconnecting the watch
            if not shutdown_event.is_set():
                await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

async def graceful_shutdown() -> None:
    """Signal all tasks to stop and wait for them to flush. Idempotent."""
    global _shutdown_started
    if _shutdown_started:
        return
    _shutdown_started = True
    log.info("Shutting down - flushing remaining buffers...")
    shutdown_event.set()

    tasks = list(active_pods.values())
    if tasks:
        log.info("Waiting for %d active pod tasks to finish...", len(tasks))
        await asyncio.gather(*tasks, return_exceptions=True)

    if http_client:
        await http_client.aclose()

    log.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    global http_client

    log.info(
        "CFS Log Exporter starting (receiver=%s, namespace=%s, prefix=%s)",
        RECEIVER_URL,
        NAMESPACE,
        POD_PREFIX,
    )

    http_client = httpx.AsyncClient()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(graceful_shutdown()))

    try:
        await watch_pods()
    except asyncio.CancelledError:
        pass
    finally:
        await graceful_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
