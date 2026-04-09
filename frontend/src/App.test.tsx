import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "./App";

// Mock child components to isolate navigation logic
vi.mock("./components/SessionList", () => ({
  default: ({ onSelectSession, clusterFilter }: { onSelectSession: (id: string) => void; clusterFilter: string | null }) => (
    <div data-testid="session-list" data-cluster={clusterFilter ?? ""}>
      <button onClick={() => onSelectSession("abc-123")}>Select session</button>
    </div>
  ),
}));

vi.mock("./components/SessionDetail", () => ({
  default: ({ sessionUuid, onBack }: { sessionUuid: string; onBack: () => void }) => (
    <div data-testid="session-detail" data-uuid={sessionUuid}>
      <button onClick={onBack}>Back</button>
    </div>
  ),
}));

vi.mock("./components/ClusterSelector", () => ({
  default: ({ selected, onChange }: { selected: string | null; onChange: (c: string | null) => void }) => (
    <div data-testid="cluster-selector" data-selected={selected ?? ""}>
      <button onClick={() => onChange("cluster-a")}>Pick cluster</button>
      <button onClick={() => onChange(null)}>Clear cluster</button>
    </div>
  ),
}));

function setURL(search: string) {
  window.history.replaceState(null, "", search || "/");
}

describe("App navigation", () => {
  beforeEach(() => {
    setURL("/");
  });

  it("renders session list by default", () => {
    render(<App />);
    expect(screen.getByTestId("session-list")).toBeInTheDocument();
    expect(screen.queryByTestId("session-detail")).not.toBeInTheDocument();
  });

  it("navigates to session detail when selecting a session", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Select session"));

    expect(screen.getByTestId("session-detail")).toBeInTheDocument();
    expect(screen.getByTestId("session-detail")).toHaveAttribute("data-uuid", "abc-123");
    expect(window.location.search).toBe("?session=abc-123");
  });

  it("navigates back to session list via onBack", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Select session"));
    expect(screen.getByTestId("session-detail")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Back"));
    expect(screen.getByTestId("session-list")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("navigates back to session list via header title click", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Select session"));
    expect(screen.getByTestId("session-detail")).toBeInTheDocument();

    await userEvent.click(screen.getByText("CFS Log Viewer"));
    expect(screen.getByTestId("session-list")).toBeInTheDocument();
  });

  it("handles browser back button (popstate)", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Select session"));
    expect(screen.getByTestId("session-detail")).toBeInTheDocument();

    // Simulate browser back
    act(() => {
      window.history.back();
    });

    // popstate fires asynchronously after history.back()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId("session-list")).toBeInTheDocument();
  });

  it("initializes from URL with session param", () => {
    setURL("/?session=xyz-789");
    render(<App />);
    expect(screen.getByTestId("session-detail")).toBeInTheDocument();
    expect(screen.getByTestId("session-detail")).toHaveAttribute("data-uuid", "xyz-789");
  });

  it("initializes from URL with cluster param", () => {
    setURL("/?cluster=cluster-a");
    render(<App />);
    expect(screen.getByTestId("session-list")).toHaveAttribute("data-cluster", "cluster-a");
  });

  it("updates URL when selecting a cluster", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Pick cluster"));
    expect(window.location.search).toBe("?cluster=cluster-a");
  });

  it("preserves cluster in URL when selecting a session", async () => {
    setURL("/?cluster=cluster-a");
    render(<App />);
    await userEvent.click(screen.getByText("Select session"));
    expect(window.location.search).toBe("?session=abc-123&cluster=cluster-a");
  });
});
