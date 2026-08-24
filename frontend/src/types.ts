export type Critic = 'assumption' | 'competitor' | 'economics' | 'feasibility' | 'security' | 'compliance' | 'marketing';
export type Severity = 'structural' | 'significant' | 'minor';
export interface ThreadMessage { role: string; content: string }
export interface Finding { id: string; critic: Critic; severity: Severity; claim: string; critique: string; suggested_fix?: string | null; thread?: ThreadMessage[]; dismissed?: boolean }
export interface Session { id:string; raw_spec:string; selected_critics?: Critic[]; parsed_sections:Record<string,string>; missing_context?: string[]; findings:Finding[]; revised_spec?:string|null; status:string }
export interface SessionSummary { id: string; created_at: string; status: string; title: string }

// ── Risk Register ─────────────────────────────────────────────────────────
export type RiskStatus = 'open' | 'mitigating' | 'accepted' | 'deferred' | 'dismissed' | 'resolved';

export interface RiskComment {
  id: string;
  risk_id: string;
  author_id: string | null;
  author_email: string | null;
  body: string;
  created_at: string;
}

export interface Risk {
  id: string;
  session_id: string;
  finding_id: string | null;
  critic: string;
  severity: string;
  claim: string;
  critique: string;
  suggested_fix: string | null;
  confidence: number | null;
  evidence: Record<string, unknown>[] | null;
  validation_plan: string | null;
  status: RiskStatus;
  owner_id: string | null;
  owner_email: string | null;
  due_date: string | null;
  source_run_id: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  comments?: RiskComment[];
}

export interface RiskSummary {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  overdue: number;
  unassigned: number;
  resolved?: number;
}
