import { useEffect, useRef } from "react";
import { formatTime } from "../utils";
import type { LogLine } from "../types";

interface LogStreamProps {
  lines: LogLine[];
  isLive: boolean;
  filterXname?: string;
  filterContainer?: string;
  showTimestamps?: boolean;
}

function lineClass(line: LogLine): string {
  switch (line.event_type) {
    case "playbook_start":
      return "text-cyan-400 font-bold";
    case "play_start":
      return "text-yellow-400 font-bold";
    case "task_start":
      return "text-blue-400 font-semibold";
    case "play_recap":
      return "text-purple-400 font-bold";
    case "recap_host":
      return "text-purple-300";
    case "warning":
      return "text-orange-400";
    case "task_result":
      switch (line.status) {
        case "ok":
          return "text-green-400";
        case "changed":
          return "text-yellow-300";
        case "failed":
        case "fatal":
          return "text-red-400 font-semibold";
        case "skipping":
          return "text-gray-500";
        case "unreachable":
          return "text-red-500 font-bold";
        default:
          return "text-gray-300";
      }
    default:
      return "text-gray-400";
  }
}

function StatusIcon({ status }: { status: string | null }) {
  if (!status) return null;
  const icons: Record<string, string> = {
    ok: "~",
    changed: "*",
    failed: "!",
    fatal: "!!",
    skipping: "-",
    unreachable: "X",
  };
  return (
    <span className="text-gray-600 mr-2 w-4 inline-block text-right">
      {icons[status] || " "}
    </span>
  );
}

export default function LogStream({ lines, isLive, filterXname, filterContainer, showTimestamps }: LogStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);

  useEffect(() => {
    if (autoScroll.current && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines.length]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    autoScroll.current = atBottom;
  };

  const filtered = lines
    .filter((l) =>
      !filterXname ||
      l.xname === filterXname ||
      l.event_type !== "task_result" ||
      l.raw_line.includes(filterXname)
    )
    .filter((l) => !filterContainer || l.container === filterContainer);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="bg-gray-950 rounded-lg p-4 font-mono text-xs leading-relaxed
                 overflow-y-auto max-h-[70vh] border border-gray-800"
    >
      {filtered.map((line) => (
        <div key={line.id || line.line_number} className={`${lineClass(line)} hover:bg-gray-900/50`}>
          <span className="text-gray-700 select-none mr-3 w-12 inline-block text-right">
            {line.line_number}
          </span>
          {showTimestamps && (
            <span className="text-gray-600 mr-3 select-none">
              {line.timestamp
                ? formatTime(line.timestamp)
                : "        "}
            </span>
          )}
          {line.event_type === "task_result" && (
            <StatusIcon status={line.status} />
          )}
          {line.raw_line}
        </div>
      ))}
      {isLive && (
        <div className="flex items-center gap-2 text-blue-400 mt-2">
          <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
          Streaming live...
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
