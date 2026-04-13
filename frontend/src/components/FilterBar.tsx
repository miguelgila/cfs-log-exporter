import { useState, useEffect } from "react";
import { getXnames } from "../api";
import type { XnameInfo } from "../types";

interface FilterBarProps {
  onFilter: (filters: { xname?: string; status?: string }) => void;
  currentFilters: { xname?: string; status?: string };
}

export default function FilterBar({ onFilter, currentFilters }: FilterBarProps) {
  const [xnames, setXnames] = useState<XnameInfo[]>([]);
  const [xnameInput, setXnameInput] = useState(currentFilters.xname || "");
  const [showSuggestions, setShowSuggestions] = useState(false);

  useEffect(() => {
    getXnames().then(setXnames).catch(console.error);
  }, []);

  const filtered = xnameInput
    ? xnames.filter((x) => x.xname.includes(xnameInput))
    : [];

  return (
    <div className="flex flex-wrap gap-3 items-center p-4 bg-gray-800 rounded-lg">
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

      {(currentFilters.xname || currentFilters.status) && (
        <button
          onClick={() => {
            setXnameInput("");
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
