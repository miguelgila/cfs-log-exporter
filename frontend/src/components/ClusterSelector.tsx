import { useEffect, useState } from "react";
import { getClusters } from "../api";

interface ClusterSelectorProps {
  selected: string | null;
  onChange: (cluster: string | null) => void;
}

export default function ClusterSelector({ selected, onChange }: ClusterSelectorProps) {
  const [clusters, setClusters] = useState<string[]>([]);

  useEffect(() => {
    getClusters()
      .then((rows) => setClusters(rows.map((r) => r.cluster)))
      .catch(console.error);
  }, []);

  return (
    <div className="flex items-center gap-2">
      <span className="text-gray-500 text-sm">Cluster:</span>
      <div className="flex gap-1">
        <button
          onClick={() => onChange(null)}
          className={`px-3 py-1 rounded text-sm transition-colors ${
            selected === null
              ? "bg-blue-600 text-white"
              : "bg-gray-700 text-gray-300 hover:bg-gray-600"
          }`}
        >
          All
        </button>
        {clusters.map((c) => (
          <button
            key={c}
            onClick={() => onChange(selected === c ? null : c)}
            className={`px-3 py-1 rounded text-sm transition-colors ${
              selected === c
                ? "bg-blue-600 text-white"
                : "bg-gray-700 text-gray-300 hover:bg-gray-600"
            }`}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  );
}
