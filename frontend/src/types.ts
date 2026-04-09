export interface Session {
  id: number;
  session_uuid: string;
  pod_name: string;
  batcher_id: string | null;
  cluster: string | null;
  status: "running" | "completed" | "failed";
  started_at: string | null;
  ended_at: string | null;
  xnames: string[];
  playbooks: string[];
  created_at: string;
}

export interface LogLine {
  id: number;
  session_id: number;
  line_number: number;
  timestamp: string | null;
  event_type: string;
  raw_line: string;
  playbook: string | null;
  repo_url: string | null;
  play_name: string | null;
  role: string | null;
  task_name: string | null;
  status: string | null;
  xname: string | null;
  item: string | null;
  container: string | null;
}

export interface SessionDetail extends Session {
  log_lines: LogLine[];
}

export interface XnameInfo {
  xname: string;
  session_count: number;
}

export interface SessionsResponse {
  sessions: Session[];
  total: number;
}
