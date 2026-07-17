export type Critic = 'assumption' | 'competitor' | 'economics' | 'feasibility';
export type Severity = 'structural' | 'significant' | 'minor';
export interface Finding { critic: Critic; severity: Severity; claim: string; critique: string; suggested_fix?: string | null }
export interface Session { id:string; raw_spec:string; parsed_sections:Record<string,string>; findings:Finding[]; revised_spec?:string|null; status:string }
export interface SessionSummary { id: string; created_at: string; status: string; title: string }
