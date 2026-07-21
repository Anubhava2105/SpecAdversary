import { useEffect, useRef, useState } from 'react';
import { SpecInput } from '../components/app/SpecInput';
import { LiveFeed } from '../components/app/LiveFeed';
import { ReportView } from '../components/app/ReportView';
import { Sidebar } from '../components/app/Sidebar';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { Finding, Session, Critic } from '../types';
import { useAuth } from '../AuthContext';
import { Link } from 'react-router-dom';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_BASE = API.replace('http', 'ws');
const MAX_BACKOFF_MS = 30_000;

export default function App() {
  const [raw, setRaw] = useState('');
  const [findings, setFindings] = useState<Finding[]>([]);
  const [sections, setSections] = useState<string[]>([]);
  const [missingContext, setMissingContext] = useState<string[]>([]);
  const [status, setStatus] = useState('waiting');
  const [revised, setRevised] = useState('');
  const [id, setId] = useState('');
  const [error, setError] = useState('');
  const [wsConnected, setWsConnected] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedCritics, setSelectedCritics] = useState<Critic[]>(['assumption', 'competitor', 'economics', 'feasibility']);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const { token, user } = useAuth();

  const retryCount = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

  /** Load a session by ID (used by sidebar + URL restore). */
  const loadSession = async (sessionId: string) => {
    try {
      const r = await fetch(`${API}/sessions/${sessionId}`, { headers: authHeaders });
      if (!r.ok) return;
      const x: Session = await r.json();
      setId(sessionId);
      setRaw(x.raw_spec);
      setFindings(x.findings);
      setSections(Object.keys(x.parsed_sections));
      setMissingContext(x.missing_context || []);
      setRevised(x.revised_spec || '');
      setStatus(x.status);
      setError('');
      setSelectedCritics(x.selected_critics || ['assumption', 'competitor', 'economics', 'feasibility']);
      history.replaceState(null, '', `?session=${sessionId}`);
    } catch {
      /* best-effort */
    }
  };

  const submit = async (spec: string, selectedCritics: Critic[]) => {
    setRaw(spec);
    setFindings([]);
    setSections([]);
    setMissingContext([]);
    setRevised('');
    setStatus('parsing');
    setError('');
    setSelectedCritics(selectedCritics);
    const r = await fetch(`${API}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ raw_spec: spec, selected_critics: selectedCritics }),
    });
    if (!r.ok) {
      setError('Failed to create session');
      setStatus('waiting');
      return;
    }
    const x = await r.json();
    setId(x.id);
    history.replaceState(null, '', `?session=${x.id}`);
    setRefreshKey((k) => k + 1);
  };

  /** Backfill state from REST after a reconnect so we don't miss events. */
  const backfill = async (sessionId: string) => {
    try {
      const r = await fetch(`${API}/sessions/${sessionId}`, { headers: authHeaders });
      if (!r.ok) return;
      const x: Session = await r.json();
      if (x.findings?.length) setFindings(x.findings);
      if (x.revised_spec) setRevised(x.revised_spec);
      if (x.status) setStatus(x.status);
      if (x.parsed_sections) {
        setSections(Object.keys(x.parsed_sections));
      }
      if (x.missing_context) setMissingContext(x.missing_context);
      if (x.selected_critics) {
        setSelectedCritics(x.selected_critics);
      }
    } catch {
      /* backfill is best-effort */
    }
  };

  useEffect(() => {
    if (!id) return;

    let unmounted = false;

    function connect() {
      if (unmounted) return;

      const wsUrl = new URL(`${WS_BASE}/sessions/${id}/stream`);
      if (token) wsUrl.searchParams.set('token', token);

      const ws = new WebSocket(wsUrl.toString());
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        if (retryCount.current > 0) {
          backfill(id);
        }
        retryCount.current = 0;
      };

      ws.onmessage = (e) => {
        const x = JSON.parse(e.data);
        if (x.type === 'finding') {
          setFindings((v) => {
            const filtered = v.filter((f) => f.id !== x.finding.id);
            return [...filtered, x.finding];
          });
        }
        if (x.type === 'section_parsed') setSections((v) => v.includes(x.section) ? v : [...v, x.section]);
        if (x.type === 'gatekeeper') setMissingContext(x.missing_context || []);
        if (x.type === 'findings_moderated') setFindings(x.findings || []);
        if (x.type === 'status') setStatus(x.status);
        if (x.type === 'token') setRevised((v) => v + x.content);
        if (x.type === 'done') {
          setRevised(x.revised_spec);
          setStatus('done');
          setRefreshKey((k) => k + 1);
        }
        if (x.type === 'error') setError(x.message);
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
  useEffect(() => {
    const existing = new URLSearchParams(location.search).get('session');
    if (existing) loadSession(existing);
  }, [token]);

  const replyToFinding = async (findingId: string, reply: string) => {
    if (!id) return;
    try {
      await fetch(`${API}/sessions/${id}/findings/${findingId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ reply }),
      });
    } catch (e) {
      console.error(e);
    }
  };

  const showReport = status === 'synthesizing' || !!revised;

  return (
    <main style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', flexDirection: 'column' }}>
      {!user && (
        <div style={{ background: '#34352f', color: '#e8e4d9', padding: '8px', textAlign: 'center', fontSize: '12px' }}>
          You are using a guest session. <Link to={`/login?claim_session=${id}`} style={{ color: '#d5ff4d', textDecoration: 'underline' }}>Sign in to save your sessions.</Link>
        </div>
      )}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {isSidebarOpen && (
          <div style={{ width: '260px', flexShrink: 0, borderRight: '1px solid #34352f', height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Sidebar activeId={id} refreshKey={refreshKey} onSelect={loadSession} onClose={() => setIsSidebarOpen(false)} />
          </div>
        )}
        
        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          <Group orientation="horizontal">
            <Panel defaultSize={33} minSize={20}>
              <SpecInput 
                onSubmit={submit} 
                busy={status !== 'waiting' && status !== 'done'} 
                isSidebarOpen={isSidebarOpen}
                onOpenSidebar={() => setIsSidebarOpen(true)}
                missingContext={missingContext}
              />
            </Panel>
          
          <Separator className="resize-handle" />
          
          <Panel defaultSize={33} minSize={20}>
            <LiveFeed
              findings={findings}
              status={status}
              sections={sections}
              missingContext={missingContext}
              connected={wsConnected}
              onReply={replyToFinding}
            />
          </Panel>
          
          <Separator className="resize-handle" />
          
          <Panel defaultSize={33} minSize={20}>
            {showReport ? (
              <ReportView
                raw={raw}
                revised={revised}
                findings={findings}
                streaming={status === 'synthesizing'}
              />
            ) : (
              <section className="report empty">
                <p className="eyebrow">03 / REPORT</p>
                <p>Revised spec will appear here when synthesis completes.</p>
                {error && <p className="error" style={{color: '#ff6b6b'}}>{error}</p>}
              </section>
            )}
          </Panel>
          </Group>
        </div>
      </div>
    </main>
  );
}
