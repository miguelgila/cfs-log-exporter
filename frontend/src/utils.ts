const pad = (n: number) => String(n).padStart(2, "0");

export function formatDateTime(ts: string | null): string {
  if (!ts) return "-";
  const d = new Date(ts);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatTime(ts: string | null): string {
  if (!ts) return "-";
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
