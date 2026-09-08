import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { Link } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { LiveFeed } from "../components/app/LiveFeed";
import { ReportView } from "../components/app/ReportView";
import { RiskRegister } from "../components/app/RiskRegister";
import { Sidebar } from "../components/app/Sidebar";
import { SpecInput } from "../components/app/SpecInput";
import { API, apiFetch, errorDetail, WS_BASE } from "../lib/api";
import type { Critic, Finding, Session } from "../types";

const MAX_BACKOFF_MS = 30_000;
const MOBILE_BREAKPOINT = 900;

function useIsMobile() {
  const subscribe = (cb: () => void) => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`);
    mql.addEventListener("change", cb);
    return () => mql.removeEventListener("change", cb);
  };
  const getSnapshot = () => window.innerWidth <= MOBILE_BREAKPOINT;
  return useSyncExternalStore(subscribe, getSnapshot);
}

type MobileTab = "input" | "feed" | "report" | "risks";
type ReportTab = "spec" | "risks";

export default function App() {
  const [raw, setRaw] = useState("");
  const [findings, setFindings] = useState<Finding[]>([]);
  const [sections, setSections] = useState<string[]>([]);
  const [missingContext, setMissingContext] = useState<string[]>([]);
  const [status, setStatus] = useState("waiting");
  const [revised, setRevised] = useState("");
  const [id, setId] = useState("");
  const [error, setError] = useState("");
  const [wsConnected, setWsConnected] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedCritics, setSelectedCritics] = useState<Critic[]>([
    "assumption",
    "competitor",
    "economics",
    "feasibility",
  ]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("input");
  const [reportTab, setReportTab] = useState<ReportTab>("spec");

  const { token, user } = useAuth();
  const isMobile = useIsMobile();

  const retryCount = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  // Frames can arrive late or twice (replay + live tail overlap). Once `done`
  // lands for this run, later token/status frames are stale. Ignore them so a
  // stray token cannot append garbage to the finished spec.
  const streamDone = useRef(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};

  const newSession = () => {
    streamDone.current = false;
    setRaw("");
    setFindings([]);
    setSections([]);
    setMissingContext([]);
    setRevised("");
    setStatus("waiting");
    setId("");
    setError("");
    setSelectedCritics([
      "assumption",
      "competitor",
      "economics",
      "feasibility",
    ]);
    history.replaceState(null, "", "/app");
    if (isMobile) setMobileTab("input");
  };

  /** Load a session by ID (used by sidebar + URL restore). */
  const loadSession = async (sessionId: string) => {
    try {
      const r = await fetch(`${API}/sessions/${sessionId}`, {
        headers: authHeaders,
      });
      if (!r.ok) return;
      const x: Session = await r.json();
      setId(sessionId);
      setRaw(x.raw_spec);
      setFindings(x.findings);
      setSections(Object.keys(x.parsed_sections));
      setMissingContext(x.missing_context || []);
      setRevised(x.revised_spec || "");
      setStatus(x.status);
      streamDone.current = x.status === "done";
      setError("");
      setSelectedCritics(
        x.selected_critics || [
          "assumption",
          "competitor",
          "economics",
          "feasibility",
        ],
      );
      history.replaceState(null, "", `?session=${sessionId}`);
      if (isMobile) setMobileTab("feed");
    } catch {
      /* best-effort */
    }
  };

  const submit = async (spec: string, selectedCritics: Critic[]) => {
    streamDone.current = false;
    setRaw(spec);
    setFindings([]);
    setSections([]);
    setMissingContext([]);
    setRevised("");
    setStatus("parsing");
    setError("");
    setSelectedCritics(selectedCritics);
    if (isMobile) setMobileTab("feed");
    try {
      const r = await fetch(`${API}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          raw_spec: spec,
          selected_critics: selectedCritics,
        }),
      });
      if (!r.ok) {
        setError(await errorDetail(r, "Failed to create session"));
        setStatus("waiting");
        return;
      }
      const x = await r.json();
      setId(x.id);
      history.replaceState(null, "", `?session=${x.id}`);
      setRefreshKey((k) => k + 1);
    } catch (err: unknown) {
      setError(`Network error: ${err instanceof Error ? err.message : 'request failed'}`);
      setStatus("waiting");
    }
  };

  // biome-ignore lint/correctness/useExhaustiveDependencies: reconnects are keyed to id/token only; authHeaders is stable and would retrigger the socket
  useEffect(() => {
    if (!id) return;

    let unmounted = false;

    async function connect() {
      if (unmounted) return;

      const wsUrl = new URL(`${WS_BASE}/sessions/${id}/stream`);
      let protocols: string[] | undefined;
      if (token) {
        try {
          const response = await fetch(`${API}/sessions/${id}/stream-ticket`, {
            method: "POST",
            headers: authHeaders,
          });
          if (!response.ok) throw new Error("Could not create stream ticket");
          const { ticket } = await response.json();
          protocols = ["specadversary", ticket];
        } catch {
          setError("Could not authenticate the live connection.");
          return;
        }
      }
      if (unmounted) return;
      const ws = protocols ? new WebSocket(wsUrl.toString(), protocols) : new WebSocket(wsUrl.toString());
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        // The server replays full authoritative state (snapshot + coalesced
        // history) on every connection. Reset accumulators first so replayed
        // events rebuild the view instead of double-appending onto stale data.
        setRevised("");
        setFindings([]);
        setSections([]);
        retryCount.current = 0;
      };

      ws.onmessage = (e) => {
        const x = JSON.parse(e.data);
        if (x.type === "finding") {
          setFindings((v) => {
            const filtered = v.filter((f) => f.id !== x.finding.id);
            return [...filtered, x.finding];
          });
        }
        if (x.type === "section_parsed")
          setSections((v) => (v.includes(x.section) ? v : [...v, x.section]));
        if (x.type === "gatekeeper") setMissingContext(x.missing_context || []);
        if (x.type === "findings_moderated") setFindings(x.findings || []);
        if (x.type === "status" && !streamDone.current) setStatus(x.status);
        if (x.type === "token" && !streamDone.current) setRevised((v) => v + x.content);
        if (x.type === "done") {
          streamDone.current = true;
          setRevised(x.revised_spec);
          setStatus("done");
          setRefreshKey((k) => k + 1);
        }
        // Every error frame the backend emits is terminal for the run
        // (session_busy, state_conflict, cancelled, …): surface the message
        // and move the status off whatever it was stuck on.
        if (x.type === "error") {
          setError(x.code ? `${x.message} (${x.code})` : x.message);
          setStatus("failed");
        }
      };

      ws.onclose = () => {
        if (unmounted) return;
        setWsConnected(false);
        scheduleReconnect();
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    function scheduleReconnect() {
      const delay = Math.min(1000 * 2 ** retryCount.current, MAX_BACKOFF_MS);
      retryCount.current += 1;
      reconnectTimer.current = setTimeout(connect, delay);
    }

    connect();

    return () => {
      unmounted = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [id, token]);

  // Restore session from URL on initial load
  // biome-ignore lint/correctness/useExhaustiveDependencies: deliberately runs once on mount, not on every loadSession identity change
  useEffect(() => {
    const existing = new URLSearchParams(location.search).get("session");
    if (existing) loadSession(existing);
  }, [token]);

  // Auto-switch mobile tab when synthesis starts
  useEffect(() => {
    if (isMobile && status === "synthesizing") {
      setMobileTab("report");
    }
  }, [isMobile, status]);

  const replyToFinding = async (findingId: string, reply: string) => {
    if (!id) return;
    try {
      const r = await apiFetch(
        `${API}/sessions/${id}/findings/${findingId}/reply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reply }),
        },
        authHeaders,
      );
      if (!r.ok) setError(await errorDetail(r, "Reply failed"));
    } catch (e) {
      console.error(e);
    }
  };

  const showReport = status === "synthesizing" || !!revised;
  const showRiskRegister = status === "done" && !!id;

  const riskRegisterPanel = showRiskRegister ? (
    <RiskRegister
      sessionId={id}
      authHeaders={authHeaders}
      isAuthenticated={!!user}
    />
  ) : null;

  const feedPanel = (
    <LiveFeed
      findings={findings}
      status={status}
      sections={sections}
      missingContext={missingContext}
      connected={wsConnected}
      onReply={replyToFinding}
      selectedCritics={selectedCritics}
    />
  );

  const inputPanel = (
    <SpecInput
      onSubmit={submit}
      busy={status !== "waiting" && status !== "done"}
      isSidebarOpen={isSidebarOpen}
      onOpenSidebar={() => setIsSidebarOpen(true)}
      missingContext={missingContext}
      selectedCritics={selectedCritics}
      onCriticsChange={setSelectedCritics}
    />
  );

  const reportPanel = showReport ? (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {showRiskRegister && (
        <nav className="report-tab-bar">
          <button
            type="button"
            className={`report-tab ${reportTab === 'spec' ? 'active' : ''}`}
            onClick={() => setReportTab('spec')}
          >
            Revised Spec
          </button>
          <button
            type="button"
            className={`report-tab ${reportTab === 'risks' ? 'active' : ''}`}
            onClick={() => setReportTab('risks')}
          >
            Risk Register
          </button>
        </nav>
      )}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {reportTab === 'spec' ? (
          <ReportView
            raw={raw}
            revised={revised}
            findings={findings}
            streaming={status === "synthesizing"}
          />
        ) : (
          riskRegisterPanel
        )}
      </div>
    </div>
  ) : (
    <section className="report empty" aria-label="Revised specification">
      <h2 className="panel-heading">Revised spec</h2>
      <p>Run the critics and the revised spec appears here.</p>
      {error && (
        <p className="error" style={{ color: "#ff6b6b" }}>
          {error}
        </p>
      )}
    </section>
  );

  // ── Mobile layout ──────────────────────────────────────
  if (isMobile) {
    return (
      <main className="mobile-app">
        {!user && (
          <div
            style={{
              background: "#34352f",
              color: "#e8e4d9",
              padding: "8px",
              textAlign: "center",
              fontSize: "12px",
            }}
          >
            You are using a guest session.{" "}
            <Link
              to={`/login?claim_session=${id}`}
              style={{ color: "#d5ff4d", textDecoration: "underline" }}
            >
              Sign in to save your sessions.
            </Link>
          </div>
        )}
        <div className="mobile-content">
          {mobileTab === "input" && inputPanel}
          {mobileTab === "feed" && feedPanel}
          {mobileTab === "report" && reportPanel}
          {mobileTab === "risks" && riskRegisterPanel}
        </div>
        <nav className="mobile-tab-bar">
          <button
            type="button"
            className={`mobile-tab ${mobileTab === "input" ? "active" : ""}`}
            onClick={() => setMobileTab("input")}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round" aria-hidden="true"
            >
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
            Input
          </button>
          <button
            type="button"
            className={`mobile-tab ${mobileTab === "feed" ? "active" : ""}`}
            onClick={() => setMobileTab("feed")}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round" aria-hidden="true"
            >
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
            Feed
            {findings.length > 0 && (
              <span className="mobile-tab-badge">{findings.length}</span>
            )}
          </button>
          <button
            type="button"
            className={`mobile-tab ${mobileTab === "report" ? "active" : ""}`}
            onClick={() => setMobileTab("report")}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round" aria-hidden="true"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            Report
          </button>
          {showRiskRegister && (
              <button
                type="button"
                className={`mobile-tab ${mobileTab === "risks" ? "active" : ""}`}
              onClick={() => setMobileTab("risks")}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round" aria-hidden="true"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              Risks
            </button>
          )}
        </nav>
      </main>
    );
  }

  const hasActiveSession =
    status !== "waiting" || showReport || findings.length > 0;

  // ── Desktop layout ──────────────────────────────────────
  return (
    <main
      style={{
        display: "flex",
        height: "100vh",
        width: "100vw",
        overflow: "hidden",
        flexDirection: "column",
      }}
    >
      {!user && (
        <div
          style={{
            background: "#34352f",
            color: "#e8e4d9",
            padding: "8px",
            textAlign: "center",
            fontSize: "12px",
          }}
        >
          You are using a guest session.{" "}
          <Link
            to={`/login?claim_session=${id}`}
            style={{ color: "#d5ff4d", textDecoration: "underline" }}
          >
            Sign in to save your sessions.
          </Link>
        </div>
      )}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {isSidebarOpen && (
          <div
            style={{
              width: "260px",
              flexShrink: 0,
              borderRight: "1px solid #34352f",
              height: "100%",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <Sidebar
              activeId={id}
              refreshKey={refreshKey}
              onSelect={loadSession}
              onClose={() => setIsSidebarOpen(false)}
              onNewSession={newSession}
            />
          </div>
        )}

        <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
          <Group
            key={hasActiveSession ? "3-panel" : "2-panel"}
            orientation="horizontal"
          >
            {hasActiveSession ? (
              <>
                <Panel defaultSize={33} minSize={20}>
                  {inputPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={33} minSize={20}>
                  {feedPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={34} minSize={20}>
                  {reportPanel}
                </Panel>
              </>
            ) : (
              <>
                <Panel defaultSize={55} minSize={35}>
                  {inputPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={45} minSize={30}>
                  {feedPanel}
                </Panel>
              </>
            )}
          </Group>
        </div>
      </div>
    </main>
  );
}
