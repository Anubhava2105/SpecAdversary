from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField, SQLModel

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


class DailyUsage(SQLModel, table=True):
    """One row per UTC day; used to enforce the global session budget."""
    __tablename__ = "daily_usage"
    day: str = SQLField(primary_key=True)
    sessions_created: int = 0
