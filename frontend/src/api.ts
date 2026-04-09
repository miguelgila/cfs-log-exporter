import type { Session, SessionDetail, XnameInfo } from "./types";

const API_BASE = import.meta.env.VITE_API_URL || "";

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export async function getSessions(params?: {
  xname?: string;
  status?: string;
  cluster?: string;
  limit?: number;
  offset?: number;
}): Promise<Session[]> {
  const sp = new URLSearchParams();
  if (params?.xname) sp.set("xname", params.xname);
  if (params?.status) sp.set("status", params.status);
  if (params?.cluster) sp.set("cluster", params.cluster);
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString();
  return fetchJSON(`/api/sessions${qs ? `?${qs}` : ""}`);
}

export async function getClusters(): Promise<{ cluster: string }[]> {
  return fetchJSON("/api/clusters");
}

export async function getSession(
  uuid: string,
  params?: { event_type?: string; xname?: string }
): Promise<SessionDetail> {
  const sp = new URLSearchParams();
  if (params?.event_type) sp.set("event_type", params.event_type);
  if (params?.xname) sp.set("xname", params.xname);
  const qs = sp.toString();
  return fetchJSON(`/api/sessions/${uuid}${qs ? `?${qs}` : ""}`);
}

export async function getXnames(): Promise<XnameInfo[]> {
  return fetchJSON("/api/xnames");
}

export function createSessionStream(
  uuid: string,
  afterLine: number = 0
): EventSource {
  return new EventSource(
    `${API_BASE}/api/sessions/${uuid}/stream?after_line=${afterLine}`
  );
}
