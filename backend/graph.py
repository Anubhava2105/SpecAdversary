"""LangGraph pipeline. Custom stream writer events are forwarded to WebSockets."""
from __future__ import annotations
import asyncio, json, logging, operator, os

logger = logging.getLogger(__name__)
from typing import Annotated, Any, TypedDict
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from openai import AsyncOpenAI
from models import Critic, Finding, FindingsResponse, ParsedSpec, Severity

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")
MAX_LLM_RETRIES = 2
class GraphState(TypedDict, total=False):
    raw_spec: str
    parsed_sections: dict[str, str]
    relevant_critics: list[str]
    findings: Annotated[list[dict[str, Any]], operator.add]
    revised_spec: str
def llm_enabled(): return bool(os.getenv("OPENAI_API_KEY"))
async def parse(client, instructions, text, schema):
    """Chat Completions API with JSON mode for OpenRouter compatibility."""
    last_error = None
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    for retry in range(MAX_LLM_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": f"{instructions}\n\nRespond with valid JSON matching this schema:\n{schema_json}"},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            if raw is None:
                raise RuntimeError("Model returned no content")
            return schema.model_validate_json(raw)
        except Exception as exc:
            logger.exception("parse() attempt %d failed: %s", retry + 1, exc)
            last_error = exc
            if retry < MAX_LLM_RETRIES:
                await asyncio.sleep(0.5 * (2 ** retry))
    raise RuntimeError(f"Structured LLM call failed after {MAX_LLM_RETRIES} retries") from last_error

async def stream_markdown(instructions: str, user_input: str, writer) -> str:
    """Stream tokens via *writer* and return the accumulated full text."""
    last_error = None
    for retry in range(MAX_LLM_RETRIES + 1):
        try:
            response = await AsyncOpenAI(max_retries=0).chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_input},
                ],
                stream=True,
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
        except Exception as exc:
            logger.exception("stream_markdown() attempt %d failed: %s", retry + 1, exc)
            last_error = exc
            if retry < MAX_LLM_RETRIES:
                await asyncio.sleep(0.5 * (2 ** retry))
    raise RuntimeError(f"Markdown LLM call failed after {MAX_LLM_RETRIES} retries") from last_error

async def orchestrator(state):
    writer = get_stream_writer()
    if llm_enabled():
        parsed = await parse(AsyncOpenAI(max_retries=0), "Extract this spec into the requested fields. Preserve facts; leave missing fields empty.", state["raw_spec"], ParsedSpec)
    else:
        parsed = ParsedSpec(problem=state["raw_spec"][:900], solution=state["raw_spec"][:900])
    sections = parsed.model_dump()
    for section, content in sections.items(): writer({"type":"section_parsed", "section":section, "content":content})
    # Dynamically select critics based on the parsed sections.
    # For example, skip "economics" if there's no business_model section.
    critics = ["assumption", "competitor", "feasibility"]
    if sections.get("business_model", "").strip():
        critics.append("economics")
    writer({"type":"status", "status":"critiquing"})
    return {"parsed_sections":sections, "relevant_critics":critics}

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
        result = await parse(AsyncOpenAI(max_retries=0), BRIEFS[kind] + f" {count_rule} Set critic to {kind.value}. Do not invent missing facts.", "\n\n".join(f"## {k}\n{v}" for k,v in sections.items()), FindingsResponse)
        rows = [x.model_copy(update={"critic":kind}).model_dump(mode="json") for x in result.findings]
    else:
        claim = (sections.get("solution") or sections.get("problem") or "The proposal")[:180]
        rows = [Finding(critic=kind, severity=Severity.significant, claim=claim, critique="Stub-mode finding: the proposal has no measurable validation criterion.", suggested_fix="Add an owner, success metric, and a time-boxed experiment.").model_dump(mode="json")]
    for finding in rows: writer({"type":"finding", "finding":finding})
    return {"findings":rows}
async def assumption_hunter(s): return await critic(s,Critic.assumption)
async def competitor_simulator(s): return await critic(s,Critic.competitor)
async def economics_stress_tester(s): return await critic(s,Critic.economics)
async def feasibility_auditor(s): return await critic(s,Critic.feasibility)
def fan_out(s):
    mapping={"assumption":"assumption_hunter","competitor":"competitor_simulator","economics":"economics_stress_tester","feasibility":"feasibility_auditor"}
    return [Send(mapping[x],s) for x in s["relevant_critics"]]
async def synthesizer(state):
    writer=get_stream_writer(); writer({"type":"status","status":"synthesizing"})
    rank={"structural":0,"significant":1,"minor":2}; seen=set(); unique=[]
    for f in sorted(state.get("findings",[]),key=lambda x:rank[x["severity"]]):
        key=(f["claim"].strip().lower(),f["critique"].strip().lower())
        if key not in seen: seen.add(key); unique.append(f)
    if llm_enabled():
        prompt="Original spec:\n"+state["raw_spec"]+"\n\nValidated findings:\n"+"\n".join(f"- [{x['severity']}] {x['critique']} Fix: {x.get('suggested_fix') or 'n/a'}" for x in unique)
        revised=await stream_markdown("Rewrite the product spec as markdown. Address all structural and as many significant findings as reasonably fit. Do not mention critics.", prompt, writer)
    else: revised=state["raw_spec"]+"\n\n## Validation & Risk Controls\n"+"\n".join(f"- {x['suggested_fix']}" for x in unique)
    return {"findings":unique,"revised_spec":revised}
def build_graph():
    g=StateGraph(GraphState)
    for name, node in [("orchestrator",orchestrator),("assumption_hunter",assumption_hunter),("competitor_simulator",competitor_simulator),("economics_stress_tester",economics_stress_tester),("feasibility_auditor",feasibility_auditor),("synthesizer",synthesizer)]: g.add_node(name,node)
    g.add_edge(START,"orchestrator")
    # `Send` handles dynamic routing. To fan-in, we just add explicit edges
    # from each potential dynamic target back to the synthesizer.
    g.add_conditional_edges("orchestrator",fan_out)
    for critic_node in ["assumption_hunter", "competitor_simulator", "economics_stress_tester", "feasibility_auditor"]:
        g.add_edge(critic_node, "synthesizer")
    g.add_edge("synthesizer",END); return g.compile()
spec_graph=build_graph()
