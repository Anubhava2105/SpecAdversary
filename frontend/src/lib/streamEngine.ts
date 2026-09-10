import type { Finding } from '../types';

/** Upper bound for reconnect backoff (matches the old inline constant). */
export const MAX_BACKOFF_MS = 30_000;

export interface StreamState {
  findings: Finding[];
  sections: string[];
  missingContext: string[];
  status: string;
  revised: string;
  error: string;
  connected: boolean;
  /** Once `done` lands, later token/status frames are stale replay tail. */
  done: boolean;
}

export function initialStreamState(status = 'waiting'): StreamState {
  return {
    findings: [],
    sections: [],
    missingContext: [],
    status,
    revised: '',
    error: '',
    connected: true,
    done: false,
  };
}

/**
 * Pure frame reducer behind the stream seam: one frame in, next state out.
 * Mirrors the backend's delivery contract (snapshot + coalesced history on
 * every connection, terminal error frames, done-then-stale-tail).
 */
export function applyFrame(state: StreamState, frame: Record<string, unknown>): StreamState {
  switch (frame.type) {
    case 'finding': {
      const incoming = frame.finding as Finding;
      return {
        ...state,
        findings: [...state.findings.filter((f) => f.id !== incoming.id), incoming],
      };
    }
    case 'section_parsed': {
      const section = frame.section as string;
      return state.sections.includes(section)
        ? state
        : { ...state, sections: [...state.sections, section] };
    }
    case 'gatekeeper':
      return { ...state, missingContext: (frame.missing_context as string[]) || [] };
    case 'findings_moderated':
      return { ...state, findings: (frame.findings as Finding[]) || [] };
    case 'status':
      return state.done ? state : { ...state, status: frame.status as string };
    case 'token':
      return state.done ? state : { ...state, revised: state.revised + (frame.content as string) };
    case 'done':
      return {
        ...state,
        done: true,
        revised: frame.revised_spec as string,
        status: 'done',
      };
    case 'error': {
      const code = frame.code as string | undefined;
      const message = frame.message as string;
      return {
        ...state,
        error: code ? `${message} (${code})` : message,
        status: 'failed',
      };
    }
    default:
      return state;
  }
}

/** Reset accumulators before a replay rebuilds the view (avoids double-append). */
export function resetForReplay(state: StreamState): StreamState {
  return { ...state, findings: [], sections: [], revised: '' };
}

/** Exponential backoff with ceiling: 1s, 2s, 4s, … capped at maxMs. */
export function nextBackoffMs(retryCount: number, maxMs: number = MAX_BACKOFF_MS): number {
  return Math.min(1000 * 2 ** retryCount, maxMs);
}
