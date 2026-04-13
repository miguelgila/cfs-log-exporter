import { useState, useEffect } from "react";
import { getXnames } from "../api";
import type { XnameInfo } from "../types";

export interface SessionFilters {
  xname?: string;
  status?: string;
  session_name?: string;
  started_after?: string;
}

interface FilterBarProps {
  onFilter: (filters: SessionFilters) => void;
  currentFilters: SessionFilters;
}

const TIME_PRESETS: { label: string; hours: number }[] = [
  { label: "Last 1 hour", hours: 1 },
  { label: "Last 12 hours", hours: 12 },
  { label: "Last 1 day", hours: 24 },
  { label: "Last 5 days", hours: 120 },
  { label: "Last 10 days", hours: 240 },
  { label: "Last 30 days", hours: 720 },
];

function hoursToISO(hours: number): string {
  return new Date(Date.now() - hours * 3600_000).toISOString();
}

function matchPreset(isoStr?: string): string {
  if (!isoStr) return "";
  const ts = new Date(isoStr).getTime();
  const now = Date.now();
  const diffH = (now - ts) / 3600_000;
  // Match the closest preset (within 10% tolerance)
  for (const p of TIME_PRESETS) {
    if (Math.abs(diffH - p.hours) / p.hours < 0.1) return String(p.hours);
  }
  return "";
}

export default function FilterBar({ onFilter, currentFilters }: FilterBarProps) {
  const [xnames, setXnames] = useState<XnameInfo[]>([]);
  const [xnameInput, setXnameInput] = useState(currentFilters.xname || "");
  const [nameInput, setNameInput] = useState(currentFilters.session_name || "");
  const [showSuggestions, setShowSuggestions] = useState(false);

  useEffect(() => {
    getXnames().then(setXnames).catch(console.error);
  }, []);

  const filtered = xnameInput
    ? xnames.filter((x) => x.xname.includes(xnameInput))
    : [];

  const hasFilters = currentFilters.xname || currentFilters.status
    || currentFilters.session_name || currentFilters.started_after;

  return (
    <div className="flex flex-wrap gap-3 items-center p-4 bg-gray-800 rounded-lg">
      {/* Session name filter */}
      <input
        type="text"
        placeholder="Filter by session name..."
        value={nameInput}
        onChange={(e) => setNameInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            onFilter({ ...currentFilters, session_name: nameInput || undefined });
          }
        }}
        onBlur={() => {
          onFilter({ ...currentFilters, session_name: nameInput || undefined });
        }}
        className="bg-gray-700 text-gray-200 px-3 py-1.5 rounded text-sm w-48
                   border border-gray-600 focus:border-blue-500 focus:outline-none"
      />

      {/* Xname filter */}
      <div className="relative">
        <input
          type="text"
          placeholder="Filter by xname..."
          value={xnameInput}
          onChange={(e) => {
            setXnameInput(e.target.value);
            setShowSuggestions(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              onFilter({ ...currentFilters, xname: xnameInput || undefined });
              setShowSuggestions(false);
            }
          }}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
          className="bg-gray-700 text-gray-200 px-3 py-1.5 rounded text-sm w-56
                     border border-gray-600 focus:border-blue-500 focus:outline-none"
        />
        {showSuggestions && filtered.length > 0 && (
          <div className="absolute z-10 mt-1 w-full bg-gray-700 rounded shadow-lg max-h-48 overflow-y-auto">
            {filtered.slice(0, 10).map((x) => (
              <button
                key={x.xname}
                className="block w-full text-left px-3 py-1.5 text-sm text-gray-200
                           hover:bg-gray-600"
                onMouseDown={() => {
                  setXnameInput(x.xname);
                  onFilter({ ...currentFilters, xname: x.xname });
                  setShowSuggestions(false);
                }}
              >
                {x.xname}{" "}
                <span className="text-gray-400">({x.session_count} sessions)</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Status filter */}
      <select
        value={currentFilters.status || ""}
        onChange={(e) =>
          onFilter({ ...currentFilters, status: e.target.value || undefined })
        }
        className="bg-gray-700 text-gray-200 px-3 py-1.5 rounded text-sm
                   border border-gray-600 focus:border-blue-500 focus:outline-none"
      >
        <option value="">All statuses</option>
        <option value="running">Running</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
        <option value="incomplete">Incomplete</option>
        <option value="unknown">Unknown</option>
      </select>

      {/* Time range filter */}
      <select
        value={matchPreset(currentFilters.started_after)}
        onChange={(e) => {
          const hours = e.target.value ? Number(e.target.value) : undefined;
          onFilter({
            ...currentFilters,
            started_after: hours ? hoursToISO(hours) : undefined,
          });
        }}
        className="bg-gray-700 text-gray-200 px-3 py-1.5 rounded text-sm
                   border border-gray-600 focus:border-blue-500 focus:outline-none"
      >
        <option value="">All time</option>
        {TIME_PRESETS.map((p) => (
          <option key={p.hours} value={p.hours}>
            {p.label}
          </option>
        ))}
      </select>

      {hasFilters && (
        <button
          onClick={() => {
            setXnameInput("");
            setNameInput("");
            onFilter({});
          }}
          className="text-sm text-gray-400 hover:text-gray-200"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
