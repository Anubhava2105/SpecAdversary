export type Critic = 'assumption' | 'competitor' | 'economics' | 'feasibility' | 'security' | 'compliance' | 'marketing';
export type Severity = 'structural' | 'significant' | 'minor';
export interface ThreadMessage { role: string; content: string }
export interface Finding { id: string; critic: Critic; severity: Severity; claim: string; critique: string; suggested_fix?: string | null; thread?: ThreadMessage[]; dismissed?: boolean }
export interface Session { id:string; raw_spec:string; selected_critics?: Critic[]; parsed_sections:Record<string,string>; missing_context?: string[]; findings:Finding[]; revised_spec?:string|null; status:string }
export interface SessionSummary { id: string; created_at: string; status: string; title: string }
