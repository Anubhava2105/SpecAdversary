import { useEffect, useRef, useState } from 'react';
import { SpecInput } from './SpecInput';
import { LiveFeed } from './LiveFeed';
import { ReportView } from './ReportView';
import { Sidebar } from './Sidebar';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { Finding, Session } from './types';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_BASE = API.replace('http', 'ws');
const MAX_BACKOFF_MS = 30_000;

export default function App() {
  const [raw, setRaw] = useState('');
  const [findings, setFindings] = useState<Finding[]>([]);
  const [sections, setSections] = useState<string[]>([]);
  const [status, setStatus] = useState('waiting');
  const [revised, setRevised] = useState('');
  const [id, setId] = useState('');
  const [error, setError] = useState('');
  const [wsConnected, setWsConnected] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const retryCount = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  /** Load a session by ID (used by sidebar + URL restore). */
  const loadSession = async (sessionId: string) => {
    try {
      const r = await fetch(`${API}/sessions/${sessionId}`);
      if (!r.ok) return;
      const x: Session = await r.json();
      setId(sessionId);
      setRaw(x.raw_spec);
      setFindings(x.findings);
      setSections(Object.keys(x.parsed_sections));
      setRevised(x.revised_spec || '');
      setStatus(x.status);
      setError('');
      history.replaceState(null, '', `?session=${sessionId}`);
    } catch {
      /* best-effort */
    }
  };

  const submit = async (spec: string) => {
    setRaw(spec);
    setFindings([]);
    setSections([]);
    setRevised('');
    setStatus('parsing');
    setError('');
    const r = await fetch(`${API}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_spec: spec }),
    });
    const x = await r.json();
    setId(x.id);
    history.replaceState(null, '', `?session=${x.id}`);
    setRefreshKey((k) => k + 1);
  };

  /** Backfill state from REST after a reconnect so we don't miss events. */
  const backfill = async (sessionId: string) => {
    try {
      const r = await fetch(`${API}/sessions/${sessionId}`);
      if (!r.ok) return;
      const x: Session = await r.json();
      if (x.findings?.length) setFindings(x.findings);
      if (x.revised_spec) setRevised(x.revised_spec);
      if (x.status) setStatus(x.status);
      if (x.parsed_sections) {
        setSections(Object.keys(x.parsed_sections));
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

      const ws = new WebSocket(`${WS_BASE}/sessions/${id}/stream`);
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
        if (x.type === 'finding') setFindings((v) => [...v, x.finding]);
        if (x.type === 'section_parsed') setSections((v) => [...v, x.section]);
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
  }, [id]);

  // Restore session from URL on initial load
  useEffect(() => {
    const existing = new URLSearchParams(location.search).get('session');
    if (existing) loadSession(existing);
  }, []);

  const showReport = status === 'synthesizing' || !!revised;

  return (
    <main>
      <Group orientation="horizontal">
        <Panel defaultSize={15} minSize={10}>
          <Sidebar activeId={id} refreshKey={refreshKey} onSelect={loadSession} />
        </Panel>
        
        <Separator className="resize-handle" />
        
        <Panel defaultSize={25} minSize={15}>
          <SpecInput onSubmit={submit} busy={status !== 'waiting' && status !== 'done'} />
        </Panel>
        
        <Separator className="resize-handle" />
        
        <Panel defaultSize={30} minSize={20}>
          <LiveFeed
            findings={findings}
            status={status}
            sections={sections}
            connected={wsConnected}
          />
        </Panel>
        
        <Separator className="resize-handle" />
        
        <Panel defaultSize={30} minSize={20}>
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
              {error && <p className="error">{error}</p>}
            </section>
          )}
        </Panel>
      </Group>
    </main>
  );
}
