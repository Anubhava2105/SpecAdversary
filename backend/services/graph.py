"""LangGraph pipeline. Custom stream writer events are forwarded to WebSockets."""
from __future__ import annotations

import asyncio
import json
import logging
import operator
import os
from typing import Annotated, Any, TypedDict
from urllib.parse import urlparse
from uuid import uuid4

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from openai import AsyncOpenAI
from pydantic import BaseModel
from tavily import AsyncTavilyClient

from db.models import Critic, Finding, FindingsResponse, ModeratorResponse, ParsedSpec, Severity
from services import panel as panel_registry
from services.llm_gateway import BudgetExceeded, completion_message, get_client, stream_completion

logger = logging.getLogger(__name__)

MAX_LLM_RETRIES = 4
LLM_TIMEOUT_SECONDS = 60
LLM_SEMAPHORE = asyncio.Semaphore(2)
TOOL_TIMEOUT_SECONDS = 12
# Two rounds of grounded searching: a third rarely changes the findings but
# adds two full serial LLM round-trips to the pipeline's critical path.
MAX_GROUNDED_TOOL_CALLS = 2
# Critics whose findings routinely assert external facts run the grounded
# tool loop (web search + citations) instead of the single-parse path.
# Tavily bills per search: this set directly bounds grounding spend.
GROUNDED_CRITICS = frozenset({Critic.competitor, Critic.security, Critic.compliance, Critic.feasibility})
CANONICAL_CONTEXT_FIELDS = (
    "problem_statement", "target_users", "core_solution",
    "technical_architecture", "business_model", "risks",
)
class GraphState(TypedDict, total=False):
    raw_spec: str
    parsed_sections: dict[str, str]
    relevant_critics: list[str]
    findings: Annotated[list[dict[str, Any]], operator.add]
    moderated_findings: list[dict[str, Any]]
    missing_context: list[str]
    revised_spec: str
    re_evaluate_finding_id: str
    existing_findings: list[dict[str, Any]]
def llm_enabled(): return bool(os.getenv("OPENAI_API_KEY"))

def compute_missing_context(parsed: ParsedSpec, llm_reported: list[str] | None = None) -> list[str]:
    """Deterministically merge the parser's report with empty canonical fields."""
    valid = set(CANONICAL_CONTEXT_FIELDS)
    source = parsed.missing_context if llm_reported is None else llm_reported
    reported = [item.strip() for item in source if item and item.strip()]
    result = [item for item in reported if item in valid]
    for field in CANONICAL_CONTEXT_FIELDS:
        if not str(getattr(parsed, field, "")).strip() and field not in result:
            result.append(field)
    return result

_SEVERITY_RANK = {"structural": 0, "significant": 1, "minor": 2}


def _finding_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    """Order by severity, tolerating unknown or missing severities.

    Provider output is untrusted: a missing/unknown severity must sort last,
    not raise KeyError and kill the run.
    """
    severity = str(item.get("severity") or "minor")
    return (_SEVERITY_RANK.get(severity, len(_SEVERITY_RANK)), str(item.get("claim") or ""), str(item.get("critique") or ""))


def _finding_identity(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("claim") or "").strip().lower(), str(item.get("critique") or "").strip().lower())


def dedupe_findings(findings: list[dict[str, Any]], *, skip_dismissed: bool = True) -> list[dict[str, Any]]:
    """Sort by severity and drop duplicate (claim, critique) pairs, preserving identity."""
    seen: set[tuple[str, str]] = set()
    retained: list[dict[str, Any]] = []
    for finding in sorted(findings, key=_finding_sort_key):
        if skip_dismissed and finding.get("dismissed"):
            continue
        key = _finding_identity(finding)
        if key not in seen:
            seen.add(key)
            retained.append(finding)
    return retained

def deterministic_moderation(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Safe no-LLM fallback: remove dismissed/duplicate findings, preserving identity."""
    return dedupe_findings(findings)

def preserve_moderated_identity(candidate: list[dict[str, Any]], originals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept only original IDs and restore immutable audit fields after LLM moderation."""
    by_id = {item["id"]: item for item in originals if not item.get("dismissed")}
    retained: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidate:
        source = by_id.get(item.get("id"))
        if source is None or source["id"] in seen:
            continue
        normalized = item.copy()
        normalized["id"] = source["id"]
        normalized["thread"] = source.get("thread", [])
        normalized["dismissed"] = source.get("dismissed", False)
        # Sources are audit data: restore the critic's citations rather than
        # trusting anything the moderator invented.
        normalized["sources"] = source.get("sources", [])
        retained.append(normalized)
        seen.add(source["id"])
    return retained


def _valid_source_url(url: Any) -> bool:
    """Conservative URL check for finding citations: parseable http(s) only.

    This catches fabricated non-URLs and wrong-scheme strings. It does NOT
    verify the URL exists or supports the claim — fetching and checking
    contents is explicitly out of scope for v1 (see ADR-0002 when written).
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        parts = urlparse(url.strip())
        return parts.scheme in ("http", "https") and bool(parts.netloc)
    except Exception:
        return False


def enforce_citations(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop grounded-critic findings with no verifiable citation.

    Critics in GROUNDED_CRITICS assert external facts through the search tool
    and must cite tool-returned URLs. A finding with zero parseable http(s)
    sources is either ungrounded or fabricated — either way it must not reach
    synthesis. Reasoning-only critics (assumption, economics, marketing,
    dissent) are untouched: their claims come from the spec itself.
    """
    grounded = {c.value for c in GROUNDED_CRITICS}
    retained: list[dict[str, Any]] = []
    for finding in findings:
        if finding.get("critic") not in grounded:
            retained.append(finding)
            continue
        sources = finding.get("sources") or []
        if any(_valid_source_url(s.get("url")) for s in sources if isinstance(s, dict)):
            retained.append(finding)
            continue
        logger.warning(
            "Citation gate dropped %s finding %s (no verifiable source)",
            finding.get("critic"), finding.get("id"),
        )
    return retained
async def _call_with_retries(label: str, failure_message: str, attempt):
    """Run an async LLM *attempt* with exponential-backoff retries.

    The shared shape behind parse/strict_parse/stream_markdown: try up to
    MAX_LLM_RETRIES + 1 times, log each failure, sleep between attempts, and
    raise a single RuntimeError chaining the last failure.
    """
    last_error: Exception | None = None
    for retry in range(MAX_LLM_RETRIES + 1):
        try:
            return await attempt()
        except BudgetExceeded:
            raise  # the run is over budget — retrying only burns more
        except Exception as exc:
            last_error = exc
            logger.exception("%s attempt %d failed: %s", label, retry + 1, exc)
            if retry < MAX_LLM_RETRIES:
                err_str = (str(exc) + " " + type(exc).__name__).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "ratelimit" in err_str or "quota" in err_str:
                    backoff = 14.0 * (retry + 1)
                    logger.warning("Rate limit / quota error in %s. Backing off for %.1fs (retry %d/%d)", label, backoff, retry + 1, MAX_LLM_RETRIES)
                    await asyncio.sleep(backoff)
                elif "503" in err_str or "unavailable" in err_str or "timeouterror" in err_str:
                    backoff = 4.0 * (retry + 1)
                    logger.warning("Service / timeout issue in %s. Backing off for %.1fs (retry %d/%d)", label, backoff, retry + 1, MAX_LLM_RETRIES)
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(0.5 * (2 ** retry))
    raise RuntimeError(failure_message) from last_error

async def parse(client: AsyncOpenAI, instructions, text, schema):
    """Chat Completions API with JSON mode for OpenRouter compatibility."""
    schema_json = json.dumps(schema.model_json_schema(), indent=2)

    async def attempt():
        raw = (await completion_message(
            client, messages=[
                {"role": "system", "content": f"{instructions}\n\nRespond with valid JSON matching this schema:\n{schema_json}"},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"}, timeout=LLM_TIMEOUT_SECONDS,
            operation="structured_parse",
        )).content
        if raw is None:
            raise RuntimeError("Model returned no content")
        try:
            return schema.model_validate_json(raw)
        except Exception:
            if "gemini" in os.environ.get("OPENAI_MODEL", "").lower():
                return schema.model_validate_json(raw.replace("```json", "").replace("```", ""))
            raise

    async with LLM_SEMAPHORE:
        return await _call_with_retries(
            "parse()", f"Structured LLM call failed after {MAX_LLM_RETRIES} retries", attempt
        )

async def strict_parse(client, instructions: str, user_input: str, schema: type[BaseModel]) -> BaseModel:
    """OpenAI JSON-schema constrained output, then Pydantic validation."""
    is_gemini = "gemini" in os.environ.get("OPENAI_MODEL", "google/gemini-2.5-flash").lower()
    response_format = {"type": "json_object"} if is_gemini else {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__.lower(), "strict": True, "schema": schema.model_json_schema()},
    }

    async def attempt():
        raw = (await completion_message(
            client,
            messages=[{"role": "system", "content": instructions}, {"role": "user", "content": user_input}],
            response_format=response_format, timeout=LLM_TIMEOUT_SECONDS, operation="strict_parse",
        )).content
        if raw is None:
            raise RuntimeError("Moderator returned no content")
        try:
            return schema.model_validate_json(raw)
        except Exception:
            if is_gemini:
                return schema.model_validate_json(raw.replace("```json", "").replace("```", ""))
            raise

    async with LLM_SEMAPHORE:
        return await _call_with_retries("strict_parse()", "Schema-constrained LLM call failed", attempt)

async def stream_markdown(instructions: str, user_input: str, writer) -> str:
    """Stream tokens via *writer* and return the accumulated full text."""
    async def attempt() -> str:
        response = await stream_completion(
            get_client(), messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_input},
            ],
            timeout=LLM_TIMEOUT_SECONDS, operation="markdown_synthesis",
        )
        accumulated = ""
        async for chunk in response:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                accumulated += delta
                writer({"type": "token", "content": delta})
        if not accumulated:
            raise RuntimeError("Model returned no content")
        return accumulated

    async with LLM_SEMAPHORE:
        return await _call_with_retries(
            "stream_markdown()", f"Markdown LLM call failed after {MAX_LLM_RETRIES} retries", attempt
        )

async def competitor_completion_message(client: AsyncOpenAI, messages: list[dict[str, Any]], **kwargs: Any):
    """Request a competitor-agent completion, retrying malformed provider responses.

    Some OpenAI-compatible providers can return an HTTP-success response with
    ``choices`` set to ``None``. Treat that as a transient failure rather than
    allowing it to terminate the LangGraph run while indexing the response.
    """
    async with LLM_SEMAPHORE:
        return await completion_message(
            client, messages=messages, timeout=LLM_TIMEOUT_SECONDS,
            operation="competitor_tool_loop", retries=MAX_LLM_RETRIES, **kwargs,
        )

async def orchestrator(state):
    if state.get("re_evaluate_finding_id"):
        return {}

    writer = get_stream_writer()
    if llm_enabled():
        parsed = await parse(get_client(), "Extract the spec into the canonical fields. Preserve facts, leave unsupported fields empty, and report missing_context using canonical field names.", state["raw_spec"], ParsedSpec)
    else:
        parsed = ParsedSpec(problem_statement=state["raw_spec"][:900], core_solution=state["raw_spec"][:900])
    missing_context = compute_missing_context(parsed)
    sections = parsed.model_dump()
    sections.pop("missing_context", None)
    for section, content in sections.items(): writer({"type":"section_parsed", "section":section, "content":content})
    writer({"type": "gatekeeper", "missing_context": missing_context})
    # Use the critics the user explicitly selected for this session.
    # Unknown names are dropped (stale client data), but an empty result
    # falls back to the defaults — an empty fan-out would leave the run
    # with no critic nodes and no revised spec. The roster lives in the
    # panel registry; this stays a fallback policy, not a roster copy.
    selected = state.get("selected_critics")
    if selected:
        critics = panel_registry.filter_known(list(selected))
        if not critics:
            logger.warning("No valid critics in %r; falling back to defaults", selected)
            critics = panel_registry.default_critics()[:3]
    else:
        critics = panel_registry.default_critics()[:3]
        if sections.get("business_model", "").strip():
            critics.append("economics")
    writer({"type":"status", "status":"critiquing"})
    return {"parsed_sections":sections, "missing_context": missing_context, "relevant_critics":critics}

BRIEFS = {
 Critic.assumption:"""You are the Assumption Hunter, one of four adversarial reviewers auditing a product/technical spec. Your only job is to find claims the author is treating as fact when they are actually unverified assumptions.

For each assumption, set `claim` to a quote or close paraphrase of the specific claim. In `critique`, explain why it is risky to assume it and exactly what breaks if it is false. In `suggested_fix`, propose the cheapest pre-build validation: a small experiment, user-interview question, technical spike, or similar test. Do not rewrite the specification.

Only report load-bearing assumptions. Ignore cosmetic or trivial assumptions. Do not flag a claim where the spec already gives evidence or reasoning for it: hunt unstated leaps rather than disagreeing with stated logic. Classify severity as `structural` when the whole product depends on it, `significant` when a major feature depends on it, and `minor` for a smaller meaningful risk.

Return between 2 and 6 findings, unless the spec is unusually well-grounded, in which case return fewer rather than inventing assumptions. Be concrete; never use generic critiques. Every finding's critic must be `assumption`.""",
 Critic.competitor:"""You are the Competitor Simulator, one of four adversarial reviewers auditing a product/technical spec. Role-play as a rival team that has decided to build a competing version of this exact product today. Write every critique from that competitor's first-person point of view.

For each competitive angle, use `claim` to name the specific feature, positioning choice, pricing/business-model element, or technical choice under attack. In `critique`, explain in first person how we would build something cheaper, faster, simpler, or better differentiated, and why that would win users away. Be genuinely adversarial and specific; never merely say that someone could copy it. In `suggested_fix`, leave the competitor role and recommend the defensible moat, differentiation, or execution advantage that would neutralize this exact threat.

Ground attacks in the actual specification. Do not invent a competitor that ignores what is distinctive about the idea. When the spec has a genuine hard-to-copy advantage, such as proprietary data, distribution, or technical depth, acknowledge it, then find the sharpest remaining angle. Classify severity as `structural` if this threat could kill the product entirely, `significant` if it materially erodes the advantage, and `minor` if it is a nuisance rather than existential. Return between 2 and 5 findings. Every finding's critic must be `competitor`.""",
 Critic.economics:"""You are the Economics Stress-Tester, one of four adversarial reviewers auditing a product/technical spec. Pressure-test its business and economic assumptions: unit economics, cost structure, pricing, and behavior under scale.

For each issue, use `claim` to identify the exact explicit or implied economic assumption or number. In `critique`, show concretely how it likely breaks: margin compression at scale, an unaccounted-for cost such as LLM API spend, storage, or support, pricing that conflicts with willingness to pay, or growth that excludes CAC. In `suggested_fix`, give a more defensible number, model, or mitigation for that one issue, not a complete business plan.

If the specification has no business model, pricing, or cost information at all, return exactly one `structural` finding stating that economics have not been addressed; do not invent numbers to critique. Prefer testing implied economics, such as an LLM call per user session with no stated cost per session, rather than demanding a financial model the spec never intended to include. Classify severity as `structural` when economics fail at any scale, `significant` when they work initially but not at scale (or vice versa), and `minor` for refinements rather than breaks. Return between 1 and 4 findings. Every finding's critic must be `economics`.""",
 Critic.feasibility:"""You are the Feasibility Auditor, one of four adversarial reviewers auditing a product/technical spec. Find the technical risks the author is glossing over, given the stated tech stack and timeline.

For every risk, use `claim` to name the specific technical component, integration, or claim under scrutiny. In `critique`, explain concretely what is harder than stated: a fragile integration, scaling cliff, infrastructure task treated as a one-liner that is really multi-day work, or an unacknowledged dependency between components. In `suggested_fix`, propose only the smallest de-risking step, such as a spike, proof of concept, or fallback plan; do not propose a full redesign.

Weight each finding against a stated timeline when one exists: a risk acceptable in a six-month build can be structural in a one-week build. Never report generic concerns such as 'this could have bugs'; name the exact technical mechanism. Classify severity as `structural` when it makes the stated timeline or architecture infeasible, `significant` when it causes material delay or rework, and `minor` for rough edges. Return between 2 and 5 findings. Every finding's critic must be `feasibility`.""",
 Critic.security:"""You are the Security Auditor, one of the adversarial reviewers auditing a product/technical spec. Hunt for security vulnerabilities the author is glossing over: auth gaps, injection points, data exposure, insecure defaults, missing rate limits, and supply-chain risks.

For each issue, set `claim` to the specific feature, integration, or claim under scrutiny. In `critique`, explain concretely what an attacker could do and the blast radius. In `suggested_fix`, propose the smallest concrete mitigation (e.g., a specific auth scheme, input validation rule, or encryption step); do not propose a full security program. Classify severity as `structural` when it enables a critical breach, `significant` when it causes meaningful exposure, and `minor` for hardening gaps. Return between 2 and 5 findings. Every finding's critic must be `security`.""",
 Critic.compliance:"""You are the Compliance Reviewer, one of the adversarial reviewers auditing a product/technical spec. Pressure-test regulatory and policy exposure: GDPR/CCPA data handling, industry-specific rules (HIPAA, SOC 2, PCI-DSS), accessibility, and required disclosures.

For each issue, set `claim` to the specific data practice, feature, or claim under scrutiny. In `critique`, explain the concrete regulatory or legal risk and what triggers it. In `suggested_fix`, propose the smallest compliance step (e.g., a consent flow, retention policy, or audit log); do not write a full compliance program. Classify severity as `structural` when it creates unshippable legal risk, `significant` when it blocks a major market, and `minor` for paperwork gaps. Return between 2 and 4 findings. Every finding's critic must be `compliance`.""",
 Critic.marketing:"""You are the Marketing Skeptic, one of the adversarial reviewers auditing a product/technical spec. Attack the positioning, messaging, and go-to-market assumptions: vague value props, unproven demand, channel mismatches, and claims that won't survive contact with real buyers.

For each issue, set `claim` to the specific positioning, audience, or GTM claim under attack. In `critique`, explain why a real buyer would not convert and what's missing. In `suggested_fix`, propose the smallest concrete fix (e.g., a sharper message, a validation interview, a narrower beachhead). Classify severity as `structural` when the core value prop does not land, `significant` when it limits adoption, and `minor` for polish. Return between 2 and 5 findings. Every finding's critic must be `marketing`.""",
 Critic.dissent:"""You are the Dissenting Critic, the final reviewer before synthesis. The findings below already survived moderation — your job is to attack THEM, not the raw spec. Find what the panel still got wrong: surviving holes the synthesis would gloss over, findings that are overstated or rest on shaky logic, contradictions between findings the moderator missed, and important risks no critic raised.

 For each issue, set `claim` to the specific validated finding or gap under attack (quote it). In `critique`, explain concretely why the finding is wrong, weak, or insufficient and what breaks if synthesis trusts it. In `suggested_fix`, give the correction or the missing safeguard. Return between 2 and 4 NEW findings only — never restate an existing finding as your own. Do not invent missing facts. Every finding's critic must be `dissent`.""",
}
async def critic(state, kind):
    writer, sections = get_stream_writer(), state["parsed_sections"]
    if llm_enabled():
        count_rule = (
            "Follow the Assumption Hunter count rule exactly."
            if kind is Critic.assumption
            else "Return between 2 and 5 findings." if kind is Critic.competitor
            else "Follow the Economics Stress-Tester count and missing-economics rules exactly." if kind is Critic.economics
            else "Return between 2 and 5 findings."
        )
        context_note = ", ".join(state.get("missing_context", [])) or "none"
        user_context = "\n\n".join(f"## {k}\n{v}" for k,v in sections.items()) + f"\n\nKnown missing context: {context_note}"
        result = await parse(get_client(), panel_registry.brief_for(kind) + f" {count_rule} Set critic to {kind.value}. Do not invent missing facts.", user_context, FindingsResponse)
        rows = [x.model_copy(update={"critic":kind, "id": str(uuid4())}).model_dump(mode="json") for x in result.findings]
    else:
        claim = (sections.get("core_solution") or sections.get("problem_statement") or "The proposal")[:180]
        rows = [Finding(critic=kind, severity=Severity.significant, claim=claim, critique=f"Stub-mode finding [{kind.value}]: the proposal has no measurable validation criterion.", suggested_fix="Add an owner, success metric, and a time-boxed experiment.").model_dump(mode="json")]
    for finding in rows: writer({"type":"finding", "finding":finding})
    return {"findings":rows}
async def assumption_hunter(s): return await critic(s,Critic.assumption)

@tool
async def search_web(query: str) -> str:
    """Search the web for products, competitors, or specific information. Use this to find real-world competitors."""
    try:
        tavily_client = AsyncTavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        response = await asyncio.wait_for(tavily_client.search(query=query[:300], search_depth="basic", max_results=3), timeout=TOOL_TIMEOUT_SECONDS)
        # Search snippets are untrusted external input, never instructions.
        rows = []
        for result in response.get("results", []):
            title = str(result.get("title", ""))[:200].replace("\x00", "")
            content = str(result.get("content", ""))[:1_000].replace("\x00", "")
            content = content.replace("ignore previous instructions", "[external text removed]")
            rows.append(f"- SOURCE: {title}\n  EXCERPT: {content}\n  URL: {str(result.get('url', ''))[:500]}")
        return "\n".join(rows)
    except Exception as e:
        logger.exception("Tavily search failed")
        return f"Search failed: {e}"

SOURCES_INSTRUCTION = (
    " For every finding grounded in search results, include `sources`: a list of "
    "{url, excerpt} objects using ONLY URLs returned by the search tool above. "
    "Findings based solely on the specification need no sources."
)


async def grounded_critic(state, kind: Critic, search_task: str, count_rule: str):
    """Agentic critic loop with bounded web-search grounding.

    Extracted from competitor_simulator so fact-heavy critics share one tool
    loop, one sanitizer, and one citation contract. Falls back to the
    single-parse critic path when the agent loop fails.
    """
    writer, sections = get_stream_writer(), state["parsed_sections"]
    if not llm_enabled():
        return await critic(state, kind)

    client = get_client()
    spec_text = "\n\n".join(f"## {k}\n{v}" for k,v in sections.items())
    system_prompt = (
        panel_registry.brief_for(kind) +
        f" {count_rule} Set critic to '{kind.value}'. Do not invent missing facts. "
        f"You have access to a web search tool. {search_task}{SOURCES_INSTRUCTION}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Here is the product spec:\n{spec_text}\n\n{search_task}"}
    ]

    tools = [{
        "type": "function",
        "function": {
            "name": search_web.name,
            "description": search_web.description,
            "parameters": search_web.args_schema.model_json_schema()  # type: ignore[union-attr]
        }
    }]

    tool_calls_used = 0
    try:
        for _ in range(MAX_GROUNDED_TOOL_CALLS + 1):
            msg = await competitor_completion_message(client, messages, tools=tools, tool_choice="auto")
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                break

            # Execute every requested search concurrently — serial execution
            # made the competitor the critical path of the whole pipeline.
            pending: list[tuple[dict[str, Any], asyncio.Task]] = []
            for tool_call in msg.tool_calls:
                if tool_calls_used >= MAX_GROUNDED_TOOL_CALLS:
                    # Send a placeholder result so the model doesn't see a dangling tool call
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": tool_call.function.name,
                        "content": "Tool call limit reached. Summarise with the data you already have.",
                    })
                    continue
                if tool_call.function.name == search_web.name:
                    args = json.loads(tool_call.function.arguments)
                    query = args.get('query', '')
                    writer({"type": "status", "status": f"searching: {query}"})
                    pending.append((tool_call, asyncio.create_task(search_web.ainvoke(args))))
                    tool_calls_used += 1
                else:
                    # A hallucinated tool name still needs an answer, or the
                    # next provider call rejects the dangling tool call.
                    logger.warning("Ignoring unknown tool call: %s", tool_call.function.name)
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": tool_call.function.name,
                        "content": "Unknown tool. Continue without calling it.",
                    })

            for tool_call, task in pending:
                result = await task
                messages.append({
                    "tool_call_id": tool_call.id,  # type: ignore[attr-defined]
                    "role": "tool",
                    "name": search_web.name,
                    "content": result,
                })

        schema_json = json.dumps(FindingsResponse.model_json_schema(), indent=2)
        messages.append({
            "role": "user",
            "content": f"Now that you have gathered information, output your final findings as valid JSON matching this schema:\n{schema_json}"
        })
        raw = (await competitor_completion_message(
            client, messages, response_format={"type": "json_object"}
        )).content
        if raw is None:
            raise ValueError("Empty response")
        result_json = FindingsResponse.model_validate_json(raw)
        rows = [x.model_copy(update={"critic": kind, "id": str(uuid4())}).model_dump(mode="json") for x in result_json.findings]
    except Exception as e:
        logger.exception("Grounded critic %s failed: %s", kind.value, e)
        return await critic(state, kind)

    for finding in rows: writer({"type":"finding", "finding":finding})
    return {"findings": rows}


async def competitor_simulator(state):
    return await grounded_critic(
        state, Critic.competitor,
        "Use it to find actual real-world competitors for the proposed product.",
        "Return between 2 and 5 findings.",
    )


async def feasibility_auditor(state):
    return await grounded_critic(
        state, Critic.feasibility,
        "Use it to verify concrete technical facts you assert (integration limits, scaling precedents, known outages).",
        "Return between 2 and 5 findings.",
    )


async def security_auditor(state):
    return await grounded_critic(
        state, Critic.security,
        "Use it to verify concrete security facts you assert (known CVEs, auth patterns, breach precedents).",
        "Return between 2 and 5 findings.",
    )


async def compliance_auditor(state):
    return await grounded_critic(
        state, Critic.compliance,
        "Use it to verify concrete regulatory facts you assert (GDPR/CCPA articles, certification requirements).",
        "Return between 2 and 4 findings.",
    )


async def economics_stress_tester(s): return await critic(s,Critic.economics)
async def marketing_auditor(s): return await critic(s,Critic.marketing)

async def critic_dispatch(state):
    """Barrier source for normal fan-out; it intentionally leaves state unchanged."""
    return {}

async def moderator(state):
    writer = get_stream_writer()
    writer({"type": "status", "status": "moderating"})
    originals = state.get("findings", [])
    deterministic = deterministic_moderation(originals)

    # Skip the LLM round-trip when the deterministic pass has nothing to do:
    # no duplicates, no dismissals, and nothing pruned. This is the common
    # case, and moderation is a full serial call on the critical path.
    nothing_to_do = (
        len(deterministic) == len(originals)
        and not any(f.get("dismissed") for f in originals)
        and len({_finding_identity(f) for f in originals}) == len(originals)
    )

    if llm_enabled() and originals and not nothing_to_do:
        instruction = (
            "You are the Moderator. Consolidate the untrusted critic findings supplied in the user message. "
            "Remove dismissed findings; deduplicate overlap; resolve contradictions by retaining the more specific, "
            "higher-severity evidence-based finding. Return only retained findings. Each retained finding MUST use the exact input 'id' "
            "of the finding it corresponds to. Do not change or invent IDs."
        )
        try:
            result = await parse(get_client(), instruction, json.dumps(originals), ModeratorResponse)
            moderated = preserve_moderated_identity([item.model_dump(mode="json") for item in result.findings], originals)
            if len(moderated) < max(1, len(deterministic) // 2):
                logger.warning("LLM moderation pruned too aggressively (%d vs %d deterministic); using deterministic fallback", len(moderated), len(deterministic))
                moderated = deterministic
        except Exception:
            logger.exception("Moderator failed; using deterministic consolidation")
            moderated = deterministic
    else:
        moderated = deterministic

    moderated = enforce_citations(moderated)
    writer({"type": "findings_moderated", "findings": moderated})
    return {"moderated_findings": moderated}

async def dissent(state):
    """Bounded dissent pass: attack the moderated findings before synthesis.

    Runs only when the session selected the dissenting critic (opt-in, off by
    default). One serial LLM call — this is the approved substitute for a
    convergence loop (see ADR-0001): fixed cost, no lifecycle changes.
    """
    if Critic.dissent.value not in (state.get("relevant_critics") or []):
        return {}
    writer = get_stream_writer()
    writer({"type": "status", "status": "dissenting"})
    base = state.get("moderated_findings", state.get("findings", []))
    if not llm_enabled() or not base:
        return {}
    payload = (
        "Original spec:\n" + state.get("raw_spec", "") +
        "\n\nValidated findings under attack:\n" + json.dumps(base)
    )
    result = await parse(
        get_client(),
        panel_registry.brief_for(Critic.dissent) + " Return between 2 and 4 findings. Set critic to 'dissent'.",
        payload,
        FindingsResponse,
    )
    rows = [x.model_copy(update={"critic": Critic.dissent, "id": str(uuid4())}).model_dump(mode="json") for x in result.findings]
    for finding in rows:
        writer({"type": "finding", "finding": finding})
    return {"moderated_findings": base + rows}


async def re_evaluate(state):
    writer = get_stream_writer()
    fid = state["re_evaluate_finding_id"]
    existing_findings = state.get("existing_findings", [])
    target = next((f for f in existing_findings if f.get("id") == fid), None)

    if not target:
        return {"findings": existing_findings}

    writer({"type": "status", "status": "re-evaluating finding..."})

    if llm_enabled():
        client = get_client()
        system_prompt = (
            f"You are the {target.get('critic')} reviewer. The user has replied to your finding. "
            "Review the conversation and update the finding. You may change the severity, critique, or suggested_fix. "
            "If you agree with the user and the finding is no longer valid, set `dismissed: true`. "
            "Otherwise `dismissed: false`."
        )

        thread_text = ""
        for msg in target.get("thread", []) or []:
            if not isinstance(msg, dict):
                continue
            thread_text += f"{str(msg.get('role', 'unknown')).upper()}:\n{msg.get('content', '')}\n\n"

        prompt_text = f"Original spec:\n{state.get('raw_spec')}\n\nOriginal finding:\n{json.dumps(target, indent=2)}\n\nConversation:\n{thread_text}"

        result = await parse(client, system_prompt, prompt_text, Finding)
        updated = result.model_dump(mode="json")
        updated["id"] = fid
        updated["thread"] = target.get("thread", [])
    else:
        updated = target.copy()
        updated["critique"] = "Stub-mode: updated critique."
        updated["thread"] = target.get("thread", [])

    new_findings = []
    for f in existing_findings:
        if f.get("id") == fid:
            new_findings.append(updated)
            writer({"type": "finding", "finding": updated})
        else:
            new_findings.append(f)

    return {"findings": new_findings}

def fan_out(s):
    if s.get("re_evaluate_finding_id"):
        return [Send("re_evaluate", s)]
    mapping={"assumption":"assumption_hunter","competitor":"competitor_simulator","economics":"economics_stress_tester","feasibility":"feasibility_auditor","security":"security_auditor","compliance":"compliance_auditor","marketing":"marketing_auditor"}
    sends = []
    for x in s.get("relevant_critics") or []:
        if x == Critic.dissent.value:
            # Post-moderation node with its own edge; not part of fan-out.
            continue
        node = mapping.get(x)
        if node is None:
            logger.warning("Skipping unknown critic in fan-out: %r", x)
            continue
        sends.append(Send(node, s))
    return sends
async def synthesizer(state):
    writer=get_stream_writer(); writer({"type":"status","status":"synthesizing"})
    unique = dedupe_findings(state.get("moderated_findings", state.get("findings",[])), skip_dismissed=False)
    if llm_enabled():
        prompt="Original spec:\n"+state["raw_spec"]+"\n\nValidated findings:\n"+"\n".join(f"- [{x.get('severity', 'significant')}] {x.get('critique', '')} Fix: {x.get('suggested_fix') or 'n/a'}" for x in unique)
        revised=await stream_markdown("Rewrite the product spec as markdown. Address all structural and as many significant findings as reasonably fit. Do not mention critics.", prompt, writer)
    else: revised=state["raw_spec"]+"\n\n## Validation & Risk Controls\n"+"\n".join(f"- {x.get('suggested_fix', '')}" for x in unique)
    return {"findings":unique,"revised_spec":revised}
def build_graph():
    g=StateGraph(GraphState)
    for name, node in [("orchestrator",orchestrator),("critic_dispatch",critic_dispatch),("assumption_hunter",assumption_hunter),("competitor_simulator",competitor_simulator),("economics_stress_tester",economics_stress_tester),("feasibility_auditor",feasibility_auditor),("security_auditor",security_auditor),("compliance_auditor",compliance_auditor),("marketing_auditor",marketing_auditor),("moderator",moderator),("dissent",dissent),("re_evaluate",re_evaluate),("synthesizer",synthesizer)]: g.add_node(name,node)
    g.add_edge(START,"orchestrator")
    def route_orchestrator(state):
        return "re_evaluate" if state.get("re_evaluate_finding_id") else "critic_dispatch"
    g.add_conditional_edges("orchestrator", route_orchestrator)
    g.add_conditional_edges("critic_dispatch", fan_out)
    for critic_node in ["assumption_hunter", "competitor_simulator", "economics_stress_tester", "feasibility_auditor", "security_auditor", "compliance_auditor", "marketing_auditor"]:
        g.add_edge(critic_node, "moderator")
    # Dissent is a no-op passthrough unless the session opted in; reply flows
    # (re_evaluate) bypass it exactly like they bypass moderation.
    g.add_edge("moderator", "dissent")
    g.add_edge("dissent", "synthesizer")
    # re_evaluate → synthesizer intentionally bypasses moderator: it updates a
    # single finding in-place, and re-running full moderation could incorrectly
    # dismiss the just-updated finding or discard unrelated findings.
    g.add_edge("re_evaluate", "synthesizer")
    g.add_edge("synthesizer",END); return g.compile()
spec_graph=build_graph()


