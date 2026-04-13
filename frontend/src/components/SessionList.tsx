import { useState, useEffect, useCallback } from "react";
import { getSessions } from "../api";
import type { Session } from "../types";
import FilterBar from "./FilterBar";
import type { SessionFilters } from "./FilterBar";
import { formatDateTime } from "../utils";

interface SessionListProps {
  onSelectSession: (uuid: string) => void;
  clusterFilter: string | null;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    completed: "bg-green-500/20 text-green-400 border-green-500/30",
    failed: "bg-red-500/20 text-red-400 border-red-500/30",
    incomplete: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    unknown: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border ${colors[status] || "bg-gray-500/20 text-gray-400"}`}
    >
      {status === "running" && (
        <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
      )}
      {status}
    </span>
  );
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "-";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const diff = Math.floor((e - s) / 1000);
  const m = Math.floor(diff / 60);
  const sec = diff % 60;
  return `${m}m ${sec}s`;
}

function formatTime(ts: string | null): string {
  return formatDateTime(ts);
}

export default function SessionList({ onSelectSession, clusterFilter }: SessionListProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [filters, setFilters] = useState<SessionFilters>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    getSessions({ ...filters, cluster: clusterFilter ?? undefined, limit: 50 })
      .then(setSessions)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filters, clusterFilter]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">CFS Sessions</h1>
        <span className="text-sm text-gray-400">{sessions.length} sessions</span>
      </div>

      <FilterBar onFilter={setFilters} currentFilters={filters} />

      {loading && sessions.length === 0 ? (
        <div className="text-gray-400 text-center py-12">Loading...</div>
      ) : sessions.length === 0 ? (
        <div className="text-gray-400 text-center py-12">No sessions found</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-400 uppercase bg-gray-800/50">
              <tr>
                <th className="px-4 py-3">Session</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Playbooks</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.session_uuid}
                  onClick={() => onSelectSession(s.session_uuid)}
                  className="border-b border-gray-700/50 hover:bg-gray-800/50 cursor-pointer
                             transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="font-mono text-blue-400 text-xs">
                      {s.session_uuid.slice(0, 8)}...
                    </div>
                    {s.batcher_id && (
                      <div className="text-gray-500 text-xs mt-0.5">
                        batch: {s.batcher_id.slice(0, 8)}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="px-4 py-3 text-gray-300">
                    {formatTime(s.started_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-300">
                    {formatDuration(s.started_at, s.ended_at)}
                  </td>
                  <td className="px-4 py-3">
                    {s.xnames.length === 0 ? (
                      <span className="text-amber-400 text-xs font-medium">Image Build</span>
                    ) : (
                      <span className="text-gray-300">{s.xnames.length} xnames</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-300">{s.playbooks.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
