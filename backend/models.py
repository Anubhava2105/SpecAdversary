from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field
from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField, SQLModel

class Critic(str, Enum):
    assumption = "assumption"
    competitor = "competitor"
    economics = "economics"
    feasibility = "feasibility"
class Severity(str, Enum):
    structural = "structural"
    significant = "significant"
    minor = "minor"
class SessionStatus(str, Enum):
    parsing = "parsing"
    critiquing = "critiquing"
    synthesizing = "synthesizing"
    done = "done"
class Finding(BaseModel):
    critic: Critic
    severity: Severity
    claim: str = Field(description="The precise claim or part of the spec being targeted")
    critique: str
    suggested_fix: str | None = None
class FindingsResponse(BaseModel):
    """Structured-output wrapper: each critic response is Pydantic validated."""
    findings: list[Finding] = Field(default_factory=list)
class ParsedSpec(BaseModel):
    problem: str = ""
    users: str = ""
    solution: str = ""
    tech_stack: str = ""
    business_model: str = ""
    risks: str = ""
class SpecSession(SQLModel, table=True):
    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    raw_spec: str
    parsed_sections: dict[str, str] = SQLField(default_factory=dict, sa_column=Column(JSON))
    findings: list[dict[str, Any]] = SQLField(default_factory=list, sa_column=Column(JSON))
    revised_spec: str | None = None
    status: SessionStatus = SessionStatus.parsing
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class DailyUsage(SQLModel, table=True):
    """One row per UTC day; used to enforce the global session budget."""
    __tablename__ = "daily_usage"
    day: str = SQLField(primary_key=True)
    sessions_created: int = 0
