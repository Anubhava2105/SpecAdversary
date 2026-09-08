import type { Critic, Severity } from '../types';

/**
 * Single home for critic identity (was defined 3× and already drifting:
 * "Marketing Skeptic" vs CONTEXT.md "Marketing Critic"). Titles match
 * CONTEXT.md exactly.
 */
export const CRITICS: { id: Critic; title: string; job: string }[] = [
  { id: 'assumption', title: 'Assumption Hunter', job: 'Finds claims you treat as facts.' },
  { id: 'competitor', title: 'Competitor Simulator', job: "Attacks from a rival's point of view." },
  { id: 'economics', title: 'Economics Tester', job: 'Checks the numbers hold up.' },
  { id: 'feasibility', title: 'Feasibility Auditor', job: 'Finds what breaks when you build it.' },
  { id: 'security', title: 'Security Auditor', job: 'Looks for auth gaps, leaks, and insecure defaults.' },
  { id: 'compliance', title: 'Compliance Critic', job: 'Flags regulatory exposure.' },
  { id: 'marketing', title: 'Marketing Critic', job: 'Tests whether buyers will care.' },
];

export const CRITIC_TITLES: Record<Critic, string> = Object.fromEntries(
  CRITICS.map((c) => [c.id, c.title]),
) as Record<Critic, string>;

/** Severity rendered as the record's ruling language. */
export const RULINGS: Record<Severity, { stamp: string; className: string }> = {
  structural: { stamp: 'Sustained', className: 'ruling-sustained' },
  significant: { stamp: 'Admitted', className: 'ruling-admitted' },
  minor: { stamp: 'Overruled', className: 'ruling-overruled' },
};

/**
 * Exhibit letter for a risk's source critic (A–G in panel order). Risks carry
 * no spec-section field, so the filing critic is the stable source key.
 */
export const exhibitLetter = (criticId: string): string => {
  const i = CRITICS.findIndex((c) => c.id === criticId);
  return i < 0 ? '–' : String.fromCharCode(65 + i);
};
