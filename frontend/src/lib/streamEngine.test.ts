import { describe, expect, it } from 'vitest';
import {
  applyFrame,
  initialStreamState,
  nextBackoffMs,
  resetForReplay,
} from './streamEngine';

const finding = (id: string, claim = 'claim') => ({
  id,
  critic: 'assumption' as const,
  severity: 'minor' as const,
  claim,
  critique: 'q',
});

describe('applyFrame', () => {
  it('upserts findings by id instead of double-appending replays', () => {
    let s = initialStreamState();
    s = applyFrame(s, { type: 'finding', finding: finding('a', 'one') });
    s = applyFrame(s, { type: 'finding', finding: finding('b') });
    s = applyFrame(s, { type: 'finding', finding: finding('a', 'updated') });
    expect(s.findings.map((f) => f.id)).toEqual(['b', 'a']);
    expect(s.findings[1].claim).toBe('updated');
  });

  it('dedupes replayed sections', () => {
    let s = initialStreamState();
    s = applyFrame(s, { type: 'section_parsed', section: 'problem_statement' });
    s = applyFrame(s, { type: 'section_parsed', section: 'problem_statement' });
    expect(s.sections).toEqual(['problem_statement']);
  });

  it('replaces the feed on moderation', () => {
    let s = applyFrame(initialStreamState(), { type: 'finding', finding: finding('a') });
    s = applyFrame(s, { type: 'findings_moderated', findings: [finding('b')] });
    expect(s.findings.map((f) => f.id)).toEqual(['b']);
  });

  it('records gatekeeper context', () => {
    const s = applyFrame(initialStreamState(), {
      type: 'gatekeeper',
      missing_context: ['business_model'],
    });
    expect(s.missingContext).toEqual(['business_model']);
  });

  it('drops token/status frames that arrive after done', () => {
    let s = applyFrame(initialStreamState(), { type: 'token', content: 'hello' });
    s = applyFrame(s, { type: 'done', revised_spec: 'final' });
    s = applyFrame(s, { type: 'token', content: 'stray garbage' });
    s = applyFrame(s, { type: 'status', status: 'parsing' });
    expect(s.revised).toBe('final');
    expect(s.status).toBe('done');
  });

  it('treats error frames as terminal with code', () => {
    const s = applyFrame(initialStreamState('parsing'), {
      type: 'error',
      message: 'Session is already being analyzed by another run.',
      code: 'session_busy',
    });
    expect(s.status).toBe('failed');
    expect(s.error).toBe('Session is already being analyzed by another run. (session_busy)');
  });

  it('ignores unknown frames', () => {
    const s = applyFrame(initialStreamState(), { type: 'heartbeat' });
    expect(s).toEqual(initialStreamState());
  });
});

describe('resetForReplay', () => {
  it('clears accumulators so replay rebuilds instead of double-appending', () => {
    let s = applyFrame(initialStreamState(), { type: 'finding', finding: finding('a') });
    s = applyFrame(s, { type: 'section_parsed', section: 'risks' });
    const reset = resetForReplay(s);
    expect(reset.findings).toEqual([]);
    expect(reset.sections).toEqual([]);
    expect(reset.revised).toBe('');
    expect(reset.status).toBe(s.status);
  });
});

describe('nextBackoffMs', () => {
  it('backs off exponentially and caps at the ceiling', () => {
    expect(nextBackoffMs(0)).toBe(1000);
    expect(nextBackoffMs(2)).toBe(4000);
    expect(nextBackoffMs(10)).toBe(30_000);
    expect(nextBackoffMs(10, 5000)).toBe(5000);
  });
});
