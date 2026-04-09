import { useState, useEffect, useCallback } from "react";
import SessionList from "./components/SessionList";
import SessionDetail from "./components/SessionDetail";
import ClusterSelector from "./components/ClusterSelector";

function parseURL(): { session: string | null; cluster: string | null } {
  const params = new URLSearchParams(window.location.search);
  return {
    session: params.get("session"),
    cluster: params.get("cluster"),
  };
}

function buildSearch(session: string | null, cluster: string | null): string {
  const params = new URLSearchParams();
  if (session) params.set("session", session);
  if (cluster) params.set("cluster", cluster);
  const qs = params.toString();
  return qs ? `?${qs}` : window.location.pathname;
}

export default function App() {
  const [selectedSession, setSelectedSession] = useState<string | null>(() => parseURL().session);
  const [selectedCluster, setSelectedCluster] = useState<string | null>(() => parseURL().cluster);

  useEffect(() => {
    const onPopState = () => {
      const { session, cluster } = parseURL();
      setSelectedSession(session);
      setSelectedCluster(cluster);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((session: string | null, cluster: string | null) => {
    setSelectedSession(session);
    setSelectedCluster(cluster);
    window.history.pushState(null, "", buildSearch(session, cluster));
  }, []);

  const selectSession = useCallback((uuid: string | null) => {
    navigate(uuid, selectedCluster);
  }, [navigate, selectedCluster]);

  const selectCluster = useCallback((cluster: string | null) => {
    navigate(null, cluster);
  }, [navigate]);

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-4">
        <h1
          className="text-lg font-bold text-blue-400 cursor-pointer shrink-0"
          onClick={() => selectSession(null)}
        >
          CFS Log Viewer
        </h1>
        <span className="text-gray-600 text-sm shrink-0">ALPS Configuration Framework Service</span>
        <div className="flex-1" />
        <ClusterSelector selected={selectedCluster} onChange={selectCluster} />
      </header>
      <main className="max-w-7xl mx-auto p-6">
        {selectedSession ? (
          <SessionDetail
            sessionUuid={selectedSession}
            onBack={() => selectSession(null)}
          />
        ) : (
          <SessionList
            onSelectSession={selectSession}
            clusterFilter={selectedCluster}
          />
        )}
      </main>
    </div>
  );
}
