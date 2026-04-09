import { useState } from "react";
import SessionList from "./components/SessionList";
import SessionDetail from "./components/SessionDetail";
import ClusterSelector from "./components/ClusterSelector";

export default function App() {
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-4">
        <h1
          className="text-lg font-bold text-blue-400 cursor-pointer shrink-0"
          onClick={() => setSelectedSession(null)}
        >
          CFS Log Viewer
        </h1>
        <span className="text-gray-600 text-sm shrink-0">ALPS Configuration Framework Service</span>
        <div className="flex-1" />
        <ClusterSelector selected={selectedCluster} onChange={(c) => {
          setSelectedCluster(c);
          setSelectedSession(null);
        }} />
      </header>
      <main className="max-w-7xl mx-auto p-6">
        {selectedSession ? (
          <SessionDetail
            sessionUuid={selectedSession}
            onBack={() => setSelectedSession(null)}
          />
        ) : (
          <SessionList
            onSelectSession={setSelectedSession}
            clusterFilter={selectedCluster}
          />
        )}
      </main>
    </div>
  );
}
