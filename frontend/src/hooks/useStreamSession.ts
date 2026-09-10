import { useEffect, useRef, useState } from 'react';
import { API, WS_BASE } from '../lib/api';
import { applyFrame, initialStreamState, nextBackoffMs, resetForReplay, type StreamState } from '../lib/streamEngine';
import type { Finding } from '../types';

export interface StreamSnapshot {
  findings: Finding[];
  sections: string[];
  missingContext: string[];
  revised: string;
  status: string;
  tokenUsage: number | null;
}

interface Options {
  sessionId: string;
  token: string | null;
  authHeaders: Record<string, string>;
  /** Terminal error frames and auth failures surface here (view owns display). */
  onError: (message: string) => void;
  /** Fired when `done` lands so the view can refresh session history. */
  onDone: () => void;
}

/**
 * Stream engine hook: session id in; findings, sections, status, revised
 * spec, and connection state out. Owns the socket, replay reset, reconnect
 * backoff, and stale-frame guards — the view keeps composition.
 *
 * Every frame flows through `applyFrame` (the tested seam); React state is
 * a synced projection of the engine state.
 */
export function useStreamSession({ sessionId, token, authHeaders, onError, onDone }: Options) {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [sections, setSections] = useState<string[]>([]);
  const [missingContext, setMissingContext] = useState<string[]>([]);
  const [status, setStatus] = useState('waiting');
  const [revised, setRevised] = useState('');
  const [tokenUsage, setTokenUsage] = useState<number | null>(null);
  const [connected, setConnected] = useState(true);

  const engine = useRef<StreamState>(initialStreamState());
  const retryCount = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Latest callbacks/headers without re-keying the socket effect.
  const cbRef = useRef({ onError, onDone });
  cbRef.current = { onError, onDone };
  const headersRef = useRef(authHeaders);
  headersRef.current = authHeaders;

  const sync = (state: StreamState) => {
    setFindings(state.findings);
    setSections(state.sections);
    setMissingContext(state.missingContext);
    setStatus(state.status);
    setRevised(state.revised);
    setTokenUsage(state.tokenUsage);
  };

  /** Submit/new-session path: clear accumulators and move to a fresh status. */
  const reset = (nextStatus: string) => {
    engine.current = { ...initialStreamState(nextStatus) };
    sync(engine.current);
  };

  /** Restore path: fill the view from a persisted session snapshot. */
  const hydrate = (snapshot: StreamSnapshot) => {
    engine.current = {
      ...initialStreamState(snapshot.status),
      findings: snapshot.findings,
      sections: snapshot.sections,
      missingContext: snapshot.missingContext,
      revised: snapshot.revised,
      tokenUsage: snapshot.tokenUsage,
      done: snapshot.status === 'done',
    };
    sync(engine.current);
  };

  // biome-ignore lint/correctness/useExhaustiveDependencies: reconnects are keyed to sessionId/token only; headers/callbacks ride refs so the socket survives renders
  useEffect(() => {
    if (!sessionId) return;

    let unmounted = false;

    async function connect() {
      if (unmounted) return;

      const wsUrl = new URL(`${WS_BASE}/sessions/${sessionId}/stream`);
      let protocols: string[] | undefined;
      if (token) {
        try {
          const response = await fetch(`${API}/sessions/${sessionId}/stream-ticket`, {
            method: 'POST',
            headers: headersRef.current,
          });
          if (!response.ok) throw new Error('Could not create stream ticket');
          const { ticket } = await response.json();
          protocols = ['specadversary', ticket];
        } catch {
          cbRef.current.onError('Could not authenticate the live connection.');
          return;
        }
      }
      if (unmounted) return;
      const ws = protocols ? new WebSocket(wsUrl.toString(), protocols) : new WebSocket(wsUrl.toString());
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // The server replays full authoritative state (snapshot + coalesced
        // history) on every connection. Reset accumulators first so replayed
        // events rebuild the view instead of double-appending onto stale data.
        engine.current = resetForReplay(engine.current);
        sync(engine.current);
        retryCount.current = 0;
      };

      ws.onmessage = (e) => {
        const frame = JSON.parse(e.data);
        engine.current = applyFrame(engine.current, frame);
        sync(engine.current);
        if (frame.type === 'done') cbRef.current.onDone();
        // Every error frame the backend emits is terminal for the run
        // (session_busy, state_conflict, cancelled, …): surface the message.
        if (frame.type === 'error') {
          const code = frame.code as string | undefined;
          cbRef.current.onError(code ? `${frame.message} (${code})` : frame.message);
        }
      };

      ws.onclose = () => {
        if (unmounted) return;
        setConnected(false);
        scheduleReconnect();
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    function scheduleReconnect() {
      const delay = nextBackoffMs(retryCount.current);
      retryCount.current += 1;
      reconnectTimer.current = setTimeout(connect, delay);
    }

    connect();

    return () => {
      unmounted = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [sessionId, token]);

  return { findings, sections, missingContext, status, revised, tokenUsage, connected, reset, hydrate };
}
