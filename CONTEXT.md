# SpecAdversary

SpecAdversary is an AI-powered stress-testing platform that hardens product theses and technical specifications. A user submits a raw specification; a panel of adversarial AI critics attacks it; the system distills their attack into a Risk Register and synthesizes a revised, more robust specification. This file is the project's domain glossary: use these terms, exactly, when naming things in code, issues, tests, and discussion.

## Language

### The work users submit and receive

**Specification (Spec)**:
The raw product thesis or technical document a user submits for stress-testing. The input to everything.
_Avoid_: prompt, input text, doc

**Revised Spec**:
The hardened specification synthesized after critiques have been moderated — the primary deliverable of an analysis.

**Analysis**:
One end-to-end pass of a Spec through the critic pipeline, from parsing through synthesis. Users start one; the system executes it durably.
_Avoid_: job, task, request

**Session**:
A Specification together with its accumulated results — parsed sections, findings, revised spec — owned by zero or one user. The unit of ownership, access control, and claiming.
_Avoid_: workspace, project

**Guest Session**:
A Session created without authentication. Open to anyone holding its identifier until claimed.

**Claiming**:
Attaching a Guest Session to a User account at signup or OAuth login, so anonymous work becomes owned work. One-time and irreversible.
_Avoid_: adopting, merging

### The adversarial panel

**Critic**:
One specialist adversary on the panel. Each Critic reads the Spec's relevant sections and returns Findings.
_Avoid_: agent, reviewer, persona

The current panel:

- **Assumption Hunter** — surfaces unverified claims masquerading as facts
- **Competitor Simulator** — role-plays a rival team attacking positioning and conversion
- **Economics Tester** — attacks unit economics, cost structure, pricing
- **Feasibility Auditor** — pinpoints technical risk and scalability bottlenecks
- **Security Auditor** — hunts auth gaps, injection points, data exposure, insecure defaults
- **Compliance Critic** — flags regulatory and policy exposure
- **Marketing Critic** — attacks go-to-market claims and beachhead choice

**Gatekeeper**:
The intake stage that parses the raw Spec into sections and decides which Critics are relevant. The Spec's first line of defense against being processed wholesale.
_Avoid_: parser, router

**Moderator**:
The stage between critique and synthesis that deduplicates, merges, and softens overlapping Findings before they reach the user.
_Avoid_: filter, judge

**Finding**:
One concrete attack produced by a Critic: the claim under fire, the critique, a suggested fix, and a severity. The atom of adversarial output.
_Avoid_: issue, vulnerability (reserved for security findings)

**Severity**:
A Finding's blast radius: `structural` (core value prop doesn't land), `significant` (limits adoption), or `minor` (polish).

**Re-evaluation**:
Re-running the panel against a single Finding after a human replies in its thread, producing updated verdicts without redoing the whole Analysis.

### The Risk Register

**Risk Register**:
The normalized, human-workable ledger derived from a session's Findings: each Finding becomes a Risk that users track, assign, and resolve over time. The Register outlives the Analysis that created it.
_Avoid_: backlog, issue list

**Risk**:
One tracked entry in the Register, linked 1:1 to its source Finding. User-managed fields (status, owner, due date) survive re-analysis; AI-owned fields (critique, severity, fix) do not.

**Risk Status**:
Where a Risk sits in its human lifecycle: `open → mitigating/accepted/deferred/dismissed → resolved`, with legal transitions enforced everywhere a status changes.

### Execution model

**Run**:
One durable execution of an Analysis. Retries, re-evaluations, and worker restarts create new Runs rather than mutating old ones.
_Avoid_: execution, attempt

**Run Status**:
A Run's execution state: `queued → running → succeeded | failed | cancelled`.

**Session Status**:
What the user-facing Session is doing right now: the in-flight stages `parsing → critiquing → moderating → synthesizing`, terminating in `done` or `failed`. In-flight Sessions reject client edits; terminal ones accept them.

**Event**:
An append-only record of anything that happened during a Run (status changes, streamed tokens, completion). Events persist before delivery; live push is an accelerator, never the source of truth.

**Replay**:
Reconstructing a client's view by resending persisted Events in sequence order after a reconnect. Sequence numbers let clients drop duplicates.

**Stall / Reaping**:
A Run whose event stream has gone silent (or exceeded its maximum age) is considered orphaned; **reaping** marks it failed so clients never spin forever. Runs may be reaped by either process; the outcome must agree.

### People and access

**User**:
An authenticated person. May own many Sessions. Identity comes from password credentials or a linked OAuth provider.
_Avoid_: account, customer

**Guest**:
An unauthenticated visitor working inside Guest Sessions.

**Ownership Rule**:
Guest Sessions are open; owned Sessions are closed to everyone but their owner. Every access path enforces this identically.

**OAuth Linking**:
Connecting an OAuth provider identity to an existing account. Only proceeds when the provider email is verified — otherwise it becomes an account-takeover vector.

### Trust and limits

**Token Budget**:
The per-Run ceiling on LLM token consumption; exceeding it fails the Run cleanly rather than running away.

**Model Tiering**:
Routing pipeline stages to stronger or cheaper models by difficulty — cheap models parse and summarize; strong models critique and synthesize.

**Daily Budgets**:
Per-user and global ceilings on Analyses started per day, protecting cost and capacity from runaway usage.
