import { useState, useEffect, useCallback } from "react";
import { formatDateTime } from "../utils";
import { getSession, createSessionStream } from "../api";
import type { SessionDetail as SessionDetailType, LogLine } from "../types";
import LogStream from "./LogStream";

interface SessionDetailProps {
  sessionUuid: string;
  onBack: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  ok: "text-green-400",
  changed: "text-yellow-300",
  failed: "text-red-400",
  fatal: "text-red-400",
  skipping: "text-gray-500",
  unreachable: "text-red-500",
};

/** Parse a recap_host status string like "ok=42 changed=18 unreachable=0 failed=0 skipped=82 rescued=0 ignored=2" */
function parseRecapCounts(status: string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const match of status.matchAll(/(\w+)=(\d+)/g)) {
    counts[match[1]] = parseInt(match[2], 10);
  }
  return counts;
}

function TaskSummary({ lines }: { lines: LogLine[] }) {
  const recapHosts = lines.filter((l) => l.event_type === "recap_host" && l.xname && l.status);
  const allSuccess = lines.some(
    (l) => l.event_type === "info" && l.raw_line.includes("All playbooks completed successfully")
  );

  // Distinct repo URLs from playbook_start events
  const repoUrls = [...new Set(
    lines.filter((l) => l.event_type === "playbook_start" && l.repo_url).map((l) => l.repo_url!)
  )];

  if (recapHosts.length > 0) {
    // Primary path: use PLAY RECAP host data (authoritative)
    const recapStatusOrder = ["ok", "changed", "failed", "unreachable", "skipped", "rescued", "ignored"];
    // Aggregate per-xname across all playbooks (sum counts for same xname)
    const perXname: Record<string, Record<string, number>> = {};
    for (const l of recapHosts) {
      const x = l.xname!;
      const counts = parseRecapCounts(l.status!);
      if (!perXname[x]) perXname[x] = {};
      for (const [k, v] of Object.entries(counts)) {
        perXname[x][k] = (perXname[x][k] || 0) + v;
      }
    }
    // Aggregate totals across all xnames
    const totals: Record<string, number> = {};
    for (const counts of Object.values(perXname)) {
      for (const [k, v] of Object.entries(counts)) {
        totals[k] = (totals[k] || 0) + v;
      }
    }
    const activeStatuses = recapStatusOrder.filter((s) => totals[s]);
    const xnames = Object.keys(perXname).sort();

    return (
      <div className="bg-gray-800 rounded-lg p-4 text-sm space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="text-gray-300 font-semibold">PLAY RECAP Summary</h3>
          {allSuccess && (
            <span className="text-green-400 text-xs font-medium">All playbooks completed successfully</span>
          )}
        </div>

        {repoUrls.length > 0 && (
          <div className="text-xs text-gray-500">
            {repoUrls.map((url) => (
              <div key={url} className="truncate">
                Repo: <span className="text-gray-400 font-mono">{url}</span>
              </div>
            ))}
          </div>
        )}

        {/* Totals row */}
        <div className="flex gap-4 flex-wrap">
          {activeStatuses.map((s) => (
            <span key={s} className={STATUS_COLORS[s] || "text-gray-300"}>
              {s}: {totals[s]}
            </span>
          ))}
          <span className="text-gray-500 text-xs">({xnames.length} hosts)</span>
        </div>

        {/* Per-xname breakdown */}
        {xnames.length > 0 && xnames.length <= 20 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left py-1 pr-4">Xname</th>
                  {activeStatuses.map((s) => (
                    <th key={s} className={`text-right px-2 py-1 ${STATUS_COLORS[s] || "text-gray-300"}`}>{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {xnames.map((x) => (
                  <tr key={x} className="border-b border-gray-700/30">
                    <td className="py-1 pr-4 font-mono text-gray-300">{x}</td>
                    {activeStatuses.map((s) => (
                      <td key={s} className={`text-right px-2 py-1 ${STATUS_COLORS[s] || "text-gray-300"}`}>
                        {perXname[x][s] ?? "-"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {xnames.length > 20 && (
          <div className="text-gray-500 text-xs">{xnames.length} xnames — per-xname table hidden</div>
        )}
      </div>
    );
  }

  // Fallback path: count task_result events
  const results = lines.filter((l) => l.event_type === "task_result" && l.status);
  const totals: Record<string, number> = {};
  const perXname: Record<string, Record<string, number>> = {};

  for (const l of results) {
    const s = l.status!;
    totals[s] = (totals[s] || 0) + 1;
    if (l.xname) {
      if (!perXname[l.xname]) perXname[l.xname] = {};
      perXname[l.xname][s] = (perXname[l.xname][s] || 0) + 1;
    }
  }

  const statusOrder = ["ok", "changed", "skipping", "failed", "fatal", "unreachable"];
  const activeStatuses = statusOrder.filter((s) => totals[s]);
  const xnames = Object.keys(perXname).sort();

  return (
    <div className="bg-gray-800 rounded-lg p-4 text-sm">
      <h3 className="text-gray-300 font-semibold mb-3">Task Summary</h3>

      {/* Totals row */}
      <div className="flex gap-4 mb-3 flex-wrap">
        {activeStatuses.map((s) => (
          <span key={s} className={STATUS_COLORS[s] || "text-gray-300"}>
            {s}: {totals[s]}
          </span>
        ))}
        <span className="text-gray-500">({results.length} total)</span>
      </div>

      {/* Per-xname breakdown (collapsible if many) */}
      {xnames.length > 0 && xnames.length <= 20 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700">
                <th className="text-left py-1 pr-4">Xname</th>
                {activeStatuses.map((s) => (
                  <th key={s} className={`text-right px-2 py-1 ${STATUS_COLORS[s]}`}>{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {xnames.map((x) => (
                <tr key={x} className="border-b border-gray-700/30">
                  <td className="py-1 pr-4 font-mono text-gray-300">{x}</td>
                  {activeStatuses.map((s) => (
                    <td key={s} className={`text-right px-2 py-1 ${STATUS_COLORS[s]}`}>
                      {perXname[x][s] || "-"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {xnames.length > 20 && (
        <div className="text-gray-500 text-xs">{xnames.length} xnames — per-xname table hidden</div>
      )}
    </div>
  );
}

export default function SessionDetail({ sessionUuid, onBack }: SessionDetailProps) {
  const [session, setSession] = useState<SessionDetailType | null>(null);
  const [extraLines, setExtraLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterXname, setFilterXname] = useState<string>("");
  const [filterContainer, setFilterContainer] = useState<string>("ansible");
  const [showTimestamps, setShowTimestamps] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    getSession(sessionUuid)
      .then((s) => {
        setSession(s);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionUuid]);

  useEffect(() => {
    load();
  }, [load]);

  // SSE for live sessions
  useEffect(() => {
    if (!session || session.status !== "running") return;

    const maxLine = session.log_lines.length > 0
      ? Math.max(...session.log_lines.map((l) => l.line_number))
      : 0;

    const es = createSessionStream(sessionUuid, maxLine);
    es.onmessage = (event) => {
      try {
        const newLine: LogLine = JSON.parse(event.data);
        setExtraLines((prev) => [...prev, newLine]);
      } catch {
        // ignore parse errors
      }
    };
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, [session?.status, sessionUuid, session?.log_lines.length]);

  if (loading) {
    return <div className="text-gray-400 text-center py-12">Loading session...</div>;
  }

  if (error || !session) {
    return (
      <div className="text-center py-12">
        <div className="text-red-400 mb-4">{error || "Session not found"}</div>
        <button onClick={onBack} className="text-blue-400 hover:underline">
          Back to sessions
        </button>
      </div>
    );
  }

  const allLines = [...session.log_lines, ...extraLines];
  const isLive = session.status === "running";

  const CONTAINER_ORDER = ["git-clone", "inventory", "ansible"];
  const presentContainers = CONTAINER_ORDER.filter((c) =>
    allLines.some((l) => l.container === c)
  );

  const statusColors: Record<string, string> = {
    running: "text-blue-400",
    completed: "text-green-400",
    failed: "text-red-400",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="text-gray-400 hover:text-gray-200 text-sm"
        >
          &larr; Back
        </button>
        <h2 className="text-xl font-bold text-gray-100 font-mono">
          {session.session_uuid.slice(0, 8)}...
        </h2>
        <span className={`text-sm font-medium ${statusColors[session.status] || ""}`}>
          {isLive && (
            <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-pulse mr-1.5" />
          )}
          {session.status}
        </span>
      </div>

      {/* Session metadata */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 bg-gray-800 rounded-lg text-sm">
        <div>
          <div className="text-gray-400">Pod</div>
          <div className="text-gray-200 font-mono text-xs truncate">{session.pod_name}</div>
        </div>
        <div>
          <div className="text-gray-400">Started</div>
          <div className="text-gray-200">
            {formatDateTime(session.started_at)}
          </div>
        </div>
        <div>
          <div className="text-gray-400">Playbooks</div>
          <div className="text-gray-200">{session.playbooks.join(", ")}</div>
        </div>
        <div>
          <div className="text-gray-400">
            {session.xnames.length === 0 ? "Type" : `Xnames (${session.xnames.length})`}
          </div>
          <div className="text-gray-200 text-xs max-h-16 overflow-y-auto">
            {session.xnames.length === 0 ? (
              <span className="text-amber-400 font-medium">Image Build</span>
            ) : (
              <>
                {session.xnames.slice(0, 5).join(", ")}
                {session.xnames.length > 5 && ` +${session.xnames.length - 5} more`}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Container tabs */}
      {presentContainers.length > 0 && (
        <div className="flex gap-1 border-b border-gray-700">
          {presentContainers.map((c) => (
            <button
              key={c}
              onClick={() => setFilterContainer(c)}
              className={`px-4 py-2 text-sm font-mono transition-colors ${
                filterContainer === c
                  ? "text-blue-400 border-b-2 border-blue-400"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              {c}
            </button>
          ))}
          <button
            onClick={() => setFilterContainer("")}
            className={`px-4 py-2 text-sm transition-colors ${
              filterContainer === ""
                ? "text-blue-400 border-b-2 border-blue-400"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            all
          </button>
        </div>
      )}

      {/* Log view controls */}
      <div className="flex items-center gap-4 flex-wrap">
        {session.xnames.length > 0 && (
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400">Filter by xname:</label>
            <select
              value={filterXname}
              onChange={(e) => setFilterXname(e.target.value)}
              className="bg-gray-700 text-gray-200 px-2 py-1 rounded text-sm
                         border border-gray-600 focus:border-blue-500 focus:outline-none"
            >
              <option value="">All xnames</option>
              {session.xnames.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </div>
        )}
        <button
          onClick={() => setShowTimestamps((v) => !v)}
          className={`px-3 py-1 rounded text-sm transition-colors ${
            showTimestamps
              ? "bg-blue-600 text-white"
              : "bg-gray-700 text-gray-300 hover:bg-gray-600"
          }`}
        >
          Timestamps
        </button>
      </div>

      <LogStream
        lines={allLines}
        isLive={isLive}
        filterXname={filterXname || undefined}
        filterContainer={filterContainer || undefined}
        showTimestamps={showTimestamps}
      />

      {/* Task result summary */}
      {!isLive && allLines.some((l) => l.event_type === "task_result" || l.event_type === "recap_host") && (
        <TaskSummary lines={allLines} />
      )}
    </div>
  );
}
