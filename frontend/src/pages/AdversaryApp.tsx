import { ChevronRight, Maximize2, Minimize2 } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { Link } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { LiveFeed } from "../components/app/LiveFeed";
import { ReportView } from "../components/app/ReportView";
import { RiskRegister } from "../components/app/RiskRegister";
import { Sidebar } from "../components/app/Sidebar";
import { SpecInput } from "../components/app/SpecInput";
import { useStreamSession } from "../hooks/useStreamSession";
import { API, apiFetch, errorDetail } from "../lib/api";
import { DEFAULT_CRITICS } from "../lib/critics";
import type { Critic, Session } from "../types";

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
  const [id, setId] = useState("");
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedCritics, setSelectedCritics] = useState<Critic[]>([
    ...DEFAULT_CRITICS,
  ]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isInputCollapsed, setIsInputCollapsed] = useState(false);
  const [focusMode, setFocusMode] = useState<"report" | null>(null);
  const [targetRiskId, setTargetRiskId] = useState<string | null>(null);
  const [mobileTab, setMobileTab] = useState<MobileTab>("input");
  const [reportTab, setReportTab] = useState<ReportTab>("spec");

  const { token, user } = useAuth();
  const isMobile = useIsMobile();

  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};

  const {
    findings,
    sections,
    missingContext,
    status,
    revised,
    tokenUsage,
    connected: wsConnected,
    reset: resetStream,
    hydrate: hydrateStream,
  } = useStreamSession({
    sessionId: id,
    token,
    authHeaders,
    onError: setError,
    onDone: () => setRefreshKey((k) => k + 1),
  });

  const newSession = () => {
    resetStream("waiting");
    setRaw("");
    setId("");
    setError("");
    setSelectedCritics([
      ...DEFAULT_CRITICS,
    ]);
    setIsInputCollapsed(false);
    setFocusMode(null);
    setTargetRiskId(null);
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
      hydrateStream({
        findings: x.findings,
        sections: Object.keys(x.parsed_sections),
        missingContext: x.missing_context || [],
        revised: x.revised_spec || "",
        status: x.status,
        tokenUsage: x.token_usage ?? null,
      });
      setError("");
      setSelectedCritics(
        x.selected_critics || [
          ...DEFAULT_CRITICS,
        ],
      );
      if (x.status === "done" || x.status === "synthesizing") {
        setIsInputCollapsed(true);
      } else {
        setIsInputCollapsed(false);
      }
      history.replaceState(null, "", `?session=${sessionId}`);
      if (isMobile) setMobileTab("feed");
    } catch {
      /* best-effort */
    }
  };

  const submit = async (spec: string, selectedCritics: Critic[]) => {
    resetStream("parsing");
    setRaw(spec);
    setError("");
    setSelectedCritics(selectedCritics);
    setIsInputCollapsed(true);
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
        resetStream("waiting");
        return;
      }
      const x = await r.json();
      setId(x.id);
      history.replaceState(null, "", `?session=${x.id}`);
      setRefreshKey((k) => k + 1);
    } catch (err: unknown) {
      setError(`Network error: ${err instanceof Error ? err.message : 'request failed'}`);
      resetStream("waiting");
    }
  };

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
      targetRiskId={targetRiskId}
      onClearTargetRisk={() => setTargetRiskId(null)}
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
      onViewRisk={(findingId) => {
        setReportTab("risks");
        setTargetRiskId(findingId);
      }}
    />
  );

  const inputPanel = (
    <SpecInput
      onSubmit={submit}
      busy={status !== "waiting" && status !== "done"}
      isSidebarOpen={isSidebarOpen}
      onToggleSidebar={() => setIsSidebarOpen((v) => !v)}
      onCollapse={() => setIsInputCollapsed(true)}
      missingContext={missingContext}
      selectedCritics={selectedCritics}
      onCriticsChange={setSelectedCritics}
    />
  );

  const reportPanel = showReport ? (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {showRiskRegister && (
        <nav className="report-tab-bar" style={{ display: 'flex', alignItems: 'center' }}>
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
          <button
            type="button"
            className={`panel-focus-btn ${focusMode === 'report' ? 'active' : ''}`}
            onClick={() => setFocusMode(prev => prev === 'report' ? null : 'report')}
            title={focusMode === 'report' ? 'Restore standard view' : 'Focus reading view'}
            aria-label={focusMode === 'report' ? 'Restore standard view' : 'Focus reading view'}
            style={{ marginLeft: 'auto' }}
          >
            {focusMode === 'report' ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
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
            tokenUsage={tokenUsage}
          />
        ) : (
          riskRegisterPanel
        )}
      </div>
    </div>
  ) : (
    <section className="report empty" aria-label="Revised specification">
      <div style={{ display: 'flex', alignItems: 'center', minHeight: '28px', marginBottom: '16px' }}>
        <h2 className="panel-heading" style={{ margin: 0 }}>Revised spec</h2>
      </div>
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
        <div className="app-topbar">
          <Link to="/" className="home-link" aria-label="Back to home page">
            Spec<span>Adversary</span>
          </Link>
        </div>
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
      <div className="app-topbar">
        <Link to="/" className="home-link" aria-label="Back to home page">
          Spec<span>Adversary</span>
        </Link>
      </div>
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

        {isInputCollapsed && (
          <button
            type="button"
            className="input-rail-collapsed"
            aria-label="Expand hearing input"
            title="Click to expand hearing input"
            onClick={() => setIsInputCollapsed(false)}
          >
            <span className="input-rail-expand-btn" aria-hidden="true">
              <ChevronRight size={16} />
            </span>
            <span className="input-rail-label">HEARING SPEC</span>
            <span className="input-rail-badge">{selectedCritics.length} counsel</span>
          </button>
        )}

        <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
          <Group
            key={`${hasActiveSession ? "active" : "empty"}-${isInputCollapsed ? "collapsed" : "expanded"}-${focusMode || "normal"}`}
            orientation="horizontal"
          >
            {focusMode === "report" ? (
              <>
                <Panel defaultSize={25} minSize={15}>
                  {feedPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={75} minSize={50}>
                  {reportPanel}
                </Panel>
              </>
            ) : isInputCollapsed ? (
              <>
                <Panel defaultSize={48} minSize={30}>
                  {feedPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={52} minSize={30}>
                  {reportPanel}
                </Panel>
              </>
            ) : hasActiveSession ? (
              <>
                <Panel defaultSize={30} minSize={20}>
                  {inputPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={34} minSize={20}>
                  {feedPanel}
                </Panel>
                <Separator className="resize-handle" />
                <Panel defaultSize={36} minSize={20}>
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
