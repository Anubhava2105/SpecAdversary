from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class Critic(str, Enum):
    assumption = "assumption"
    competitor = "competitor"
    economics = "economics"
    feasibility = "feasibility"
    security = "security"
    compliance = "compliance"
    marketing = "marketing"
class Severity(str, Enum):
    structural = "structural"
    significant = "significant"
    minor = "minor"
class SessionStatus(str, Enum):
    parsing = "parsing"
    critiquing = "critiquing"
    moderating = "moderating"
    synthesizing = "synthesizing"
    done = "done"
    failed = "failed"

class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    critic: Critic
    severity: Severity
    claim: str = Field(description="The precise claim or part of the spec being targeted")
    critique: str
    suggested_fix: str | None = None
    thread: list[dict[str, str]] = Field(default_factory=list, description="Conversation thread between user and critic")
    dismissed: bool = False
class FindingsResponse(BaseModel):
    """Structured-output wrapper: each critic response is Pydantic validated."""
    findings: list[Finding] = Field(default_factory=list)
class ModeratedFinding(BaseModel):
    """LLM-safe moderator shape; audit fields are restored from the source finding."""
    id: str
    critic: Critic
    severity: Severity
    claim: str
    critique: str
    suggested_fix: str | None = None
class ModeratorResponse(BaseModel):
    findings: list[ModeratedFinding] = Field(default_factory=list)
class ParsedSpec(BaseModel):
    """Canonical gatekeeper schema; legacy parser keys remain valid on input."""
    model_config = ConfigDict(populate_by_name=True)
    problem_statement: str = Field(default="", validation_alias=AliasChoices("problem_statement", "problem"))
    target_users: str = Field(default="", validation_alias=AliasChoices("target_users", "users"))
    core_solution: str = Field(default="", validation_alias=AliasChoices("core_solution", "solution"))
    technical_architecture: str = Field(default="", validation_alias=AliasChoices("technical_architecture", "tech_stack"))
    business_model: str = ""
    risks: str = ""
    missing_context: list[str] = Field(default_factory=list)


class User(SQLModel, table=True):
    """Registered user account (email/password or OAuth)."""
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    email: str = SQLField(unique=True, index=True)
    password_hash: str | None = None
    display_name: str = ""
    oauth_provider: str | None = None
    oauth_provider_id: str | None = None
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class RefreshToken(SQLModel, table=True):
    """Server-side refresh-token record enabling rotation and theft detection.

    Tokens are stored as SHA-256 hashes. Each login starts a family; rotation
    supersedes the presented token, and reuse of a superseded token revokes
    the whole family.
    """
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    family_id: UUID = SQLField(index=True)
    user_id: UUID = SQLField(foreign_key="user.id", index=True)
    token_hash: str = SQLField(unique=True, index=True)
    superseded: bool = False
    revoked: bool = False
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class SpecSession(SQLModel, table=True):
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = SQLField(default=None, foreign_key="user.id", index=True)
    raw_spec: str
    selected_critics: list[str] = SQLField(
        default_factory=lambda: ["assumption", "competitor", "economics", "feasibility"],
        sa_column=Column(JSON),
    )
    parsed_sections: dict[str, str] = SQLField(default_factory=dict, sa_column=Column(JSON))
    missing_context: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))
    findings: list[dict[str, Any]] = SQLField(default_factory=list, sa_column=Column(JSON))
    revised_spec: str | None = None
    status: SessionStatus = SessionStatus.parsing
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisRun(SQLModel, table=True):
    """One durable execution of a specification analysis."""
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    session_id: UUID = SQLField(foreign_key="specsession.id", index=True)
    status: RunStatus = RunStatus.queued
    re_evaluate_finding_id: str | None = None
    attempt: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEvent(SQLModel, table=True):
    """Append-only event history used for replay and worker/API decoupling."""
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),)
    id: int | None = SQLField(default=None, primary_key=True)
    run_id: UUID = SQLField(foreign_key="analysisrun.id", index=True)
    sequence: int
    type: str
    payload: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class DailyUsage(SQLModel, table=True):
    """One row per UTC day; used to enforce the global session budget."""
    __tablename__ = "daily_usage"
    day: str = SQLField(primary_key=True)
    sessions_created: int = 0


class RiskStatus(str, Enum):
    open = "open"
    mitigating = "mitigating"
    accepted = "accepted"
    deferred = "deferred"
    dismissed = "dismissed"
    resolved = "resolved"


class Risk(SQLModel, table=True):
    """Normalized risk entry derived from a Finding, with user-managed lifecycle fields."""
    __table_args__ = (
        UniqueConstraint("session_id", "finding_id", name="uq_risk_session_finding"),
    )
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    session_id: UUID = SQLField(foreign_key="specsession.id", index=True)
    finding_id: str | None = SQLField(default=None)
    critic: str = ""
    severity: str = ""
    claim: str = ""
    critique: str = ""
    suggested_fix: str | None = None
    confidence: int | None = SQLField(default=None)
    evidence: list[dict[str, Any]] = SQLField(default_factory=list, sa_column=Column(JSON))
    validation_plan: str | None = None
    status: str = SQLField(default=RiskStatus.open.value)
    owner_id: UUID | None = SQLField(default=None, foreign_key="user.id", index=True)
    due_date: datetime | None = SQLField(default=None, index=True)
    source_run_id: UUID | None = SQLField(default=None, foreign_key="analysisrun.id")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc)),
    )
    resolved_at: datetime | None = None


class RiskComment(SQLModel, table=True):
    """Threaded comment on a Risk entry."""
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    risk_id: UUID = SQLField(foreign_key="risk.id", index=True)
    author_id: UUID | None = SQLField(default=None, foreign_key="user.id")
    body: str = ""
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
