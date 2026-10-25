"""
NyayaLens — Analysis Agents
Async node functions for the parallel analysis graph.
Each uses real LLM calls (pro tier for complex reasoning, flash for lighter tasks).
Citation discipline enforced: every CitationRecord must have source_id + exact_citation.
"""
from __future__ import annotations

import json
import os
import logging
import uuid
import asyncio
import re
from typing import Any

_sse_queue: asyncio.Queue | None = None

def set_sse_broadcast(q: asyncio.Queue) -> None:
    global _sse_queue
    _sse_queue = q

async def _broadcast(stage: str, status: str, message: str, summary: str = "") -> None:
    if _sse_queue is not None:
        event = {
            "kind": "stage" if status == "start" else "agent_complete",
            "status": status,
            "content": {"stage": stage, "message": message} if status == "start" else {"agent": stage, "summary": summary},
            "id": str(uuid.uuid4())
        }
        await _sse_queue.put(event)

from langchain_google_genai import ChatGoogleGenerativeAI
from app.services.llm import text_llm

from app.config import GOOGLE_API_KEY, MODEL_FLASH, MODEL_PRO, MODEL_SEARCH
from app.tools.indian_kanoon import research_query
from app.prompts.analysis_prompts import (
    ARGUMENT_HYPOTHESIS_PROMPT,
    LAWYER_CHAT_PROMPT,
    OPPOSITION_PROMPT,
    PACKET_COMPILER_PROMPT,
    READINESS_ANALYSIS_PROMPT,
    WITNESS_CANDIDATE_PROMPT,
)
from app.prompts.global_policy import inject_policy
from app.state import (
    ArgumentHypothesis,
    CaseState,
    CitationRecord,
    Fact,
    ReadinessSignals,
    WitnessCandidate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pro_llm() -> ChatGoogleGenerativeAI:
    return text_llm("pro")


def _flash_llm() -> ChatGoogleGenerativeAI:
    return text_llm("flash")


def _search_llm() -> ChatGoogleGenerativeAI:
    """gemini-2.5-flash — used exclusively for search query generation and keyword extraction."""
    return text_llm("search")


def _to_json(obj: Any) -> str:
    if isinstance(obj, list):
        items = []
        for item in obj:
            if isinstance(item, Fact):
                items.append({"fact_id": item.fact_id, "field": item.field, "value": item.value[:800], "evidence_type": item.evidence_type, "contradicts": item.contradicts})
            elif isinstance(item, CitationRecord):
                items.append({"source_id": item.source_id, "exact_citation": item.exact_citation, "source_type": item.source_type, "supporting_passage": item.supporting_passage[:350], "applicability_status": item.applicability_status})
            elif hasattr(item, "model_dump"):
                items.append(item.model_dump())
            else:
                items.append(item)
        return json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), ensure_ascii=False, indent=2)
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _parse_json_block(text: Any) -> Any:
    if isinstance(text, list):
        parts = []
        for part in text:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            elif hasattr(part, "text"):
                parts.append(getattr(part, "text", ""))
            else:
                parts.append(str(part))
        text = "".join(parts)
    elif not isinstance(text, str):
        text = str(text)

    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text.strip())


def _validate_citation(raw: dict) -> CitationRecord | None:
    """
    Build a CitationRecord only if mandatory fields are present.
    Missing fields are marked 'unclear' rather than invented.
    """
    source_id = raw.get("source_id", "").strip()
    exact_citation = raw.get("exact_citation", "").strip()
    if not source_id or not exact_citation:
        return None   # unusable — drop it

    return CitationRecord(
        source_id=source_id,
        source_url=raw.get("source_url"),
        exact_citation=exact_citation,
        supporting_passage=raw.get("supporting_passage", "unclear"),
        jurisdiction=raw.get("jurisdiction", "India"),
        date=raw.get("date", "unclear"),
        applicability_status=raw.get("applicability_status") if raw.get("applicability_status") in {"good_law", "superseded", "distinguishable", "unclear"} else "unclear",
        contradiction_or_limit=raw.get("contradiction_or_limit"),
        source_type=raw.get("source_type", "judgment"),
    )

# ---------------------------------------------------------------------------
# Node 1 — Precedent Research Agent  [Pro]
# ---------------------------------------------------------------------------

async def precedent_research_node(state: CaseState) -> dict:
    """
    Live case law research via Indian Kanoon API.
    ONLY fetches judgments (Supreme Court / High Court).

    Statute lookup is fully handled by statute_analysis_node (parallel node).
    This node does NOT touch statutes at all.

    Flow:
      1. LLM (gemini-2.5-flash) reads case facts → generates 3-4 targeted
         judgment search queries.
      2. Each query hits Indian Kanoon (doctypes:judgments).
      3. Full text fetched for top 2 results per query.
      4. Deduplication prevents the same judgment appearing twice.
    """
    await _broadcast("precedent_research", "start", "Precedent Agent: Searching Indian Kanoon for similar MACT cases...")
    try:
        llm     = _search_llm()
        facts   = state.get("facts", [])
        flags   = state.get("fuzziness_flags", [])
        track   = state.get("accident_subtype", "not_applicable")
        law_ctx = state.get("law_version_context", "unknown")

        citations: list[CitationRecord] = []
        seen_ids: set[str] = set()

        # ── Step 1: LLM generates targeted case law search queries ──
        query_prompt = (
            "You are an expert Indian Legal Research Analyst.\n"
            "Analyze the case facts below and generate 3-4 targeted search queries "
            "to find RELEVANT Supreme Court and High Court JUDGMENTS on Indian Kanoon.\n"
            "Focus on: motor accident compensation, negligence, rash/negligent driving, "
            "MACT tribunal jurisdiction, MV Act compensation quantum, insurance liability — "
            "whatever the specific facts and accident sub-type point to.\n\n"
            f"Case Facts:\n{_to_json(facts)}\n\n"
            f"Accident Sub-type: {track}\n"
            f"Law Version Context: {law_ctx}\n"
            f"Fuzziness Flags:\n{_to_json(flags)}\n\n"
            "Return ONLY a valid JSON array of query strings. Examples:\n"
            '["motor accident compensation negligence Supreme Court India",\n'
            ' "MACT tribunal jurisdiction MV Act 166 High Court",\n'
            ' "rash negligent driving BNS section compensation"]\n'
            "Return ONLY the JSON array, no explanation."
        )

        response = await llm.ainvoke([
            ("system", inject_policy(query_prompt)),
            ("human", "Generate the case law search queries as a JSON array."),
        ])

        try:
            case_law_queries = _parse_json_block(response.content)
            if not isinstance(case_law_queries, list):
                case_law_queries = []
        except Exception:
            case_law_queries = []

        # Fallback if LLM fails
        if not case_law_queries:
            case_law_queries = [f"motor accident negligence compensation {track} Supreme Court India"]

        case_law_queries = [str(q) for q in case_law_queries if q][:4]

        logger.info("[PrecedentResearch] Generated %d judgment queries", len(case_law_queries))

        # ── Step 2: Fetch live judgments from Indian Kanoon ──
        for cq in case_law_queries:
            try:
                results = await research_query(cq, doctypes="judgments")
                for res in results:
                    sid = res.get("source_id", "")
                    if not sid or sid in seen_ids:
                        continue
                    if not res.get("exact_citation"):
                        continue
                    seen_ids.add(sid)
                    citations.append(CitationRecord(
                        source_id=sid,
                        exact_citation=res["exact_citation"],
                        source_url=res.get("source_url"),
                        supporting_passage=res.get("supporting_passage", "")[:500],
                        jurisdiction=res.get("jurisdiction", "India"),
                        date=res.get("date", ""),
                        applicability_status="unclear",
                        source_type="judgment",
                        contradiction_or_limit=res.get("contradiction_or_limit"),
                    ))
            except Exception as cq_err:
                logger.warning("[PrecedentResearch] Query '%s' failed: %s", cq, cq_err)

        logger.info("[PrecedentResearch] Retrieved %d unique live judgments", len(citations))
        await _broadcast("precedent_research", "completed", "", f"Retrieved {len(citations)} judgments")
        return {"precedents": citations, "analysis_limitations": [] if citations else ["No live precedent could be retrieved. Counsel must conduct and verify case-law research manually."]}

    except Exception as exc:
        logger.error("precedent_research_node error: %s", exc, exc_info=True)
        await _broadcast("precedent_research", "completed", "", "Failed to retrieve judgments")
        raise RuntimeError("Precedent research service failed") from exc





# ---------------------------------------------------------------------------
# Node 1b — Statute Analysis Node  [Search LLM + Local JSON DB + IK for new codes]
# ---------------------------------------------------------------------------

async def statute_analysis_node(state: CaseState) -> dict:
    """
    Identifies ALL applicable statutory provisions from the local law database.

    Flow:
      1. Build a compact "menu" — just section_number + title for each relevant act.
         Old codes (IPC/CrPC/IEA/CPC…) → sourced from local JSON files (civictech_db/).
         New codes (BNS/BNSS/BSA) → section titles listed from known ranges.
      2. LLM (gemini-2.5-flash) reads the menu + case facts → picks only what applies.
      3. For picked old-code sections → fetch full text from local JSON (0ms, no network).
      4. For picked new-code sections → fetch verbatim text from Indian Kanoon API.
      5. Return merged CitationRecords appended to state['precedents'].
    """
    await _broadcast("statute_analysis", "start", "Statute Agent: Mapping applicable MV Act sections...")
    import asyncio as _asyncio
    from app.legal_data.statute_db import (
        ACT_LABELS, LOCAL_ACTS, LIVE_ACTS,
        get_section, get_section_index, get_citation_string,
    )

    try:
        llm     = _search_llm()
        facts   = state.get("facts", [])
        track   = state.get("accident_subtype", "not_applicable")
        law_ctx = state.get("law_version_context", "unknown")
        flags   = state.get("fuzziness_flags", [])

        # ── Step 1: Build compact section menu from actual JSON DB indexes ──────
        if law_ctx == "pre_2024_codes":
            local_acts = ["IPC", "IEA", "CRPC", "CPC", "MVA", "NIA"]
            live_acts  = []
        elif law_ctx == "post_2024_codes":
            local_acts = ["CPC", "MVA", "NIA"]
            live_acts  = ["BNS", "BNSS", "BSA"]
        else:  # mixed / unknown — both
            local_acts = ["IPC", "IEA", "CRPC", "CPC", "MVA", "NIA"]
            live_acts  = ["BNS", "BNSS", "BSA"]

        menu_lines = []

        # Propose retrieval targets, then verify each against the source DB.
        # Sending the entire CPC/IPC section index exceeds provider quotas and
        # is unnecessary: no proposal becomes a citation until lookup succeeds.
        for act in local_acts:
            label = ACT_LABELS.get(act, act)
            menu_lines.append(f"{act}: {label} (section proposals will be verified in the local statute database)")

        # New codes: no local file exists. Tell LLM which acts to pick from;
        # it picks section numbers from its own knowledge.
        # Indian Kanoon API is the verification — only sections IK confirms survive.
        if live_acts:
            menu_lines.append("\n--- New codes (events on/after 01-Jul-2024) ---")
            menu_lines.append("For the acts below, identify section numbers you know are relevant.")
            menu_lines.append("Each picked section will be verified against Indian Kanoon API.")
            menu_lines.append("If IK cannot confirm it, it will be dropped. Do not guess wildly.")
            for act in live_acts:
                label = ACT_LABELS.get(act, act)
                menu_lines.append(f"  {act} ({label})")

        menu_text = "\n".join(menu_lines)

        # ── Step 2: LLM picks from menu (old codes) + identifies new code sections ──
        pick_prompt = (
            "You are an expert Indian motor accident and criminal law analyst.\n"
            "Based on the case facts, pick EVERY applicable section:\n\n"
            "For OLD codes (IPC/IEA/CRPC/CPC/NIA/MVA): propose section numbers only as retrieval targets. The actual section text will be fetched from the local statute database; failed lookups are dropped.\n"
            "For NEW codes (BNS/BNSS/BSA): identify section numbers you know apply. "
            "Each will be verified against Indian Kanoon — only confirmed sections are used.\n\n"
            f"Case Facts:\n{_to_json(facts)}\n\n"
            f"Accident Sub-type: {track}\n"
            f"Law Version Context: {law_ctx}\n"
            f"Fuzziness Flags: {_to_json(flags)}\n\n"
            f"AVAILABLE SECTIONS:\n{menu_text}\n\n"
            "Return ONLY a valid JSON array. Each element:\n"
            '{"act": "MVA", "section": "166", "reason": "one sentence why it applies"}\n'
            "Return ONLY the JSON array, no markdown, no explanation."
        )

        response = await llm.ainvoke([
            ("system", inject_policy(pick_prompt)),
            ("human", "Pick all applicable sections as a JSON array."),
        ])

        try:
            picked = _parse_json_block(response.content)
            if not isinstance(picked, list):
                picked = []
        except Exception:
            picked = []

        logger.info("[StatuteAnalysis] LLM picked %d sections for track='%s'", len(picked), track)

        # ── Step 3: Fetch full text ───────────────────────────────────────────
        statute_citations: list[CitationRecord] = []
        seen_ids: set[str] = set()

        old_picks  = [p for p in picked if isinstance(p, dict) and str(p.get("act","")).upper() in LOCAL_ACTS]
        new_picks  = [p for p in picked if isinstance(p, dict) and str(p.get("act","")).upper() in LIVE_ACTS]

        # Old codes — local JSON lookup, zero network calls
        for prov in old_picks:
            act     = str(prov.get("act", "")).strip().upper()
            section = str(prov.get("section", "")).strip()
            reason  = str(prov.get("reason", ""))
            if not act or not section:
                continue

            entry = get_section(act, section)
            if not entry:
                logger.debug("[StatuteAnalysis] %s §%s not in local DB", act, section)
                continue

            cid = f"STATUTE_{act}_{section}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            statute_citations.append(CitationRecord(
                source_id=cid,
                exact_citation=get_citation_string(act, section),
                source_url="https://indiacode.gov.in",
                supporting_passage=(
                    f"[{entry.get('section_title', '')}] "
                    f"{entry.get('section_desc', '')[:450]}"
                ),
                jurisdiction=f"India — {ACT_LABELS.get(act, act)}",
                date="Central Act",
                applicability_status="unclear",
                source_type="statute",
                contradiction_or_limit=reason,
            ))

        logger.info("[StatuteAnalysis] %d old-code sections from local JSON", len(statute_citations))

        # New codes — fetch verbatim text from Indian Kanoon API
        if new_picks:
            ik_tasks = []
            for prov in new_picks:
                act     = str(prov.get("act", "")).strip().upper()
                section = str(prov.get("section", "")).strip()
                if act and section:
                    query = f"Section {section} {ACT_LABELS.get(act, act)}"
                    ik_tasks.append((prov, query))

            ik_results = await _asyncio.gather(
                *[research_query(q, doctypes="laws") for _, q in ik_tasks],
                return_exceptions=True,
            )

            for (prov, _), result in zip(ik_tasks, ik_results):
                if isinstance(result, Exception) or not result:
                    continue
                act     = str(prov.get("act", "")).strip().upper()
                section = str(prov.get("section", "")).strip()
                reason  = str(prov.get("reason", ""))
                cid     = f"STATUTE_{act}_{section}"
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)

                # A search hit is not confirmation of the requested section.
                section_pattern = rf"\b(?:section|sec\.?)\s*{re.escape(section)}\b"
                verified = [item for item in result if re.search(section_pattern, str(item.get("exact_citation", "")), re.IGNORECASE)]
                if not verified:
                    logger.warning("No source title confirms requested %s section %s", act, section)
                    continue
                top = verified[0]
                statute_citations.append(CitationRecord(
                    source_id=cid,
                    exact_citation=get_citation_string(act, section),
                    source_url=top.get("source_url", "https://indiankanoon.org"),
                    supporting_passage=top.get("supporting_passage", "")[:450],
                    jurisdiction=f"India — {ACT_LABELS.get(act, act)}",
                    date=top.get("date", "2024"),
                    applicability_status="unclear",
                    source_type="statute",
                    contradiction_or_limit=reason,
                ))

            logger.info("[StatuteAnalysis] %d new-code sections fetched from Indian Kanoon", len(new_picks))

        # ── Step 4: Return new citations (LangGraph operator.add will append them) ──
        existing     = state.get("precedents", []) or []
        existing_ids = {c.source_id for c in existing if hasattr(c, "source_id")}
        new_only     = [c for c in statute_citations if c.source_id not in existing_ids]

        logger.info("[StatuteAnalysis] Returning %d new statutory citations", len(new_only))
        await _broadcast("statute_analysis", "completed", "", f"Mapped {len(new_only)} sections")
        return {"precedents": new_only, "analysis_limitations": [] if new_only else ["No applicable statutory provision was source-verified in this run. Counsel must verify statutory elements and the law at the event date."]}

    except Exception as exc:
        logger.error("statute_analysis_node error: %s", exc, exc_info=True)
        await _broadcast("statute_analysis", "completed", "", "Failed to map sections")
        raise RuntimeError("Statutory analysis service failed") from exc


# ---------------------------------------------------------------------------
# Node 2 — Opposition Case Formulator  [Pro]
# ---------------------------------------------------------------------------


async def opposition_formulator_node(state: CaseState) -> dict:
    """
    Builds the strongest plausible opposing narrative.
    Always uses 'the opposing side may argue...' framing.
    Never asserts opposition claims as established fact.
    """
    try:
        llm = _pro_llm()
        facts = state.get("facts", [])
        flags = state.get("fuzziness_flags", [])
        precedents = state.get("precedents", [])
        timeline = state.get("timeline", [])

        system_prompt = inject_policy(OPPOSITION_PROMPT.format(
            facts_json=_to_json(facts),
            timeline_json=_to_json(timeline),
            fuzziness_flags=_to_json(flags),
            retrieved_citations_json=_to_json(precedents),
        ))

        response = await llm.ainvoke([
            ("system", system_prompt),
            ("human", "Build the opposition case. Return JSON with keys: hypotheses (list), strongest_attack_vector (str), client_clarifications_needed (list[str])."),
        ])

        try:
            parsed = _parse_json_block(response.content)
        except json.JSONDecodeError as exc:
            raise ValueError("Opposition argument agent returned invalid JSON") from exc

        # Retain evidence and citation references when adding hypothesis framing.
        hypotheses = parsed.get("hypotheses", [])
        sanitised = []
        for h in hypotheses:
            text = h if isinstance(h, str) else h.get("opposing_position", str(h))
            if not text.lower().startswith("the opposing side may argue"):
                text = "The opposing side may argue: " + text
            if isinstance(h, dict):
                h = {**h, "opposing_position": text}
                valid_sources = {c.source_id for c in precedents}
                h["legal_authority_refs"] = [ref for ref in h.get("legal_authority_refs", []) if isinstance(ref, dict) and ref.get("source_id") in valid_sources]
                sanitised.append(h)
            else:
                sanitised.append({"opposing_position": text, "legal_authority_refs": []})
        parsed["hypotheses"] = sanitised

        return {"opposition_case": parsed}

    except Exception as exc:
        logger.error("opposition_formulator_node error: %s", exc, exc_info=True)
        raise RuntimeError("Opposition argument analysis failed") from exc


OPPOSITION_ANALYSIS_PROMPT = """You are a senior Indian MACT defense advocate analyzing the OPPOSITION's case.

You have the client's facts, timeline, and the FIR/charges pressed against them.

Your job:
1. Evaluate ONLY charges explicitly recorded in the supplied facts/FIR. Assess which elements are supported, challengeable, or not established. Never label a charge fabricated or determine guilt.
2. Find the opposition's STRONGEST arguments (what the insurance company / other party will argue)
3. Find the opposition's WEAK POINTS (what can be challenged)
4. List every fact where the client hesitated, contradicted themselves, or gave unclear info — these are investigation targets for the lawyer
5. List what critical evidence is MISSING that hurts our case

Return ONLY valid JSON:
{{
  "charges_analysis": [
    {{"section": "exact section stated in the FIR", "description": "...", "validity": "supported|challengeable|not_established", "reasoning": "...", "fact_refs": [], "legal_authority_refs": [], "challenge_strategy": "..."}}
  ],
  "opposition_strong_points": ["string list"],
  "opposition_weak_points": ["string list"],  
  "client_hesitation_flags": ["facts where client was unclear or contradicted themselves"],
  "missing_critical_evidence": ["what evidence is absent that opposition will exploit"],
  "investigation_targets": ["specific lawyer investigation tasks"]
}}

Facts: {facts_json}
Timeline: {timeline_json}
FIR/Charges: {charges_info}
Fuzziness flags: {flags_json}
Retrieved authorities: {citations_json}

If no exact charge is supplied, return charges_analysis=[] and list obtaining the FIR as an investigation target. Do not infer charge numbers from the accident narrative. Every legal_authority_ref must be a supplied source_id.
"""

async def opposition_analysis_node(state: CaseState) -> dict:
    await _broadcast("opposition_analysis", "start", "Opposition Agent: Analyzing validity of pressed charges...")
    
    try:
        llm = _pro_llm()
        facts = state.get("facts", [])
        flags = state.get("fuzziness_flags", [])
        timeline = state.get("timeline", [])
        
        charges_info = [f.model_dump() for f in facts if f.field in {"fir_charges_and_sections", "charges_pressed", "fir_sections"}]
        
        system_prompt = inject_policy(OPPOSITION_ANALYSIS_PROMPT.format(
            facts_json=_to_json(facts),
            timeline_json=_to_json(timeline),
            charges_info=charges_info,
            flags_json=_to_json(flags),
            citations_json=_to_json(state.get("precedents", [])),
        ))

        response = await llm.ainvoke([
            ("system", system_prompt),
            ("human", "Return ONLY the requested JSON."),
        ])

        try:
            parsed = _parse_json_block(response.content)
        except json.JSONDecodeError as exc:
            raise ValueError("Opposition agent returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Opposition analysis must be an object")
        if not charges_info:
            parsed["charges_analysis"] = []
            parsed.setdefault("investigation_targets", []).append("Obtain the FIR and verify the exact sections, persons accused, and status of proceedings.")
        
        num_charges = len(parsed.get("charges_analysis", []))
        num_weak_points = len(parsed.get("opposition_weak_points", []))
        await _broadcast("opposition_analysis", "completed", "", f"Analyzed {num_charges} charges, found {num_weak_points} opposition weak points")
        
        await _broadcast("opposition_analysis", "completed", "", "Opposition Agent: Finished analyzing charges.")
        return {"opposition_analysis_dict": parsed}

    except Exception as exc:
        logger.error("opposition_analysis_node error: %s", exc, exc_info=True)
        await _broadcast("opposition_analysis", "completed", "", "Failed to analyze opposition case.")
        raise RuntimeError("Opposition charge analysis failed") from exc


# ---------------------------------------------------------------------------
# Node 3 — Witness Candidate Agent  [Flash]
# ---------------------------------------------------------------------------

async def witness_candidate_node(state: CaseState) -> dict:
    """
    Surfaces entities with plausible first-hand knowledge.
    Explicitly forbidden from ranking by loyalty or inferring credibility
    from demographic attributes.
    """
    try:
        llm = _flash_llm()
        entity_graph = state.get("entity_graph", {"nodes": [], "edges": []})
        facts = state.get("facts", [])

        system_prompt = inject_policy(WITNESS_CANDIDATE_PROMPT.format(
            entity_graph_json=json.dumps(entity_graph, ensure_ascii=False),
            facts_json=_to_json(facts),
        ))

        response = await llm.ainvoke([("system", system_prompt)])

        try:
            raw_candidates = _parse_json_block(response.content)
            if not isinstance(raw_candidates, list):
                raw_candidates = raw_candidates.get("candidates", [])
        except json.JSONDecodeError as exc:
            raise ValueError("Witness agent returned invalid JSON") from exc

        candidates: list[WitnessCandidate] = []
        known_fact_ids = {fact.fact_id for fact in facts}
        for raw in raw_candidates:
            # Validate: reject any candidate with a "strength" or "supports_client" field
            if "strength" in raw or "supports_client" in raw or "loyalty" in raw:
                logger.warning("Rejecting witness candidate with forbidden ranking field: %s", raw.keys())
                continue
            supporting_refs = [ref for ref in raw.get("supporting_fact_refs", []) if ref in known_fact_ids]
            if not supporting_refs:
                continue
            try:
                candidates.append(WitnessCandidate(
                    entity_id=raw.get("entity_id", f"E-{uuid.uuid4().hex[:8]}"),
                    name_or_description=raw.get("name_or_description", "Unknown"),
                    possible_first_hand_knowledge=raw.get("possible_first_hand_knowledge", ""),
                    supporting_fact_refs=supporting_refs,
                    independence_or_bias_indicators=raw.get("independence_or_bias_indicators"),
                    availability=raw.get("availability", "unknown"),
                    lawyer_verification_question=raw.get("lawyer_verification_question", ""),
                ))
            except Exception as parse_err:
                logger.warning("Could not parse witness candidate: %s", parse_err)

        return {"witness_candidates": candidates}

    except Exception as exc:
        logger.error("witness_candidate_node error: %s", exc, exc_info=True)
        raise RuntimeError("Witness analysis service failed") from exc


# ---------------------------------------------------------------------------
# Node 4 — Argument Hypothesis Builder  [Pro]
# ---------------------------------------------------------------------------

async def argument_builder_node(state: CaseState) -> dict:
    """
    Builds client-side argument hypotheses using ONLY confirmed facts and
    citations already retrieved this run. No parametric memory citations.
    """
    await _broadcast("argument_builder", "start", "Arguments Agent: Building compensation calculation and liability arguments...")
    try:
        llm = _pro_llm()
        facts = state.get("facts", [])
        precedents = state.get("precedents", [])
        opposition = state.get("opposition_case") or {}

        # Only use confirmed or unconfirmed CLIENT_STATED / DOCUMENT_EXTRACTED facts
        usable_facts = [
            f for f in facts
            if f.evidence_type in ("CLIENT_STATED", "DOCUMENT_EXTRACTED")
        ]

        # Build a set of valid source_ids from retrieved precedents
        retrieved_sources = {c.source_id: c for c in precedents}
        valid_source_ids = set(retrieved_sources)

        system_prompt = inject_policy(ARGUMENT_HYPOTHESIS_PROMPT.format(
            facts_json=_to_json(usable_facts),
            retrieved_citations_json=_to_json(precedents),
            opposition_hypotheses_json=json.dumps(
                opposition.get("hypotheses", []), ensure_ascii=False
            ),
        ))

        response = await llm.ainvoke([
            ("system", system_prompt),
            ("human", "Build argument hypotheses. Return JSON list of ArgumentHypothesis objects."),
        ])

        try:
            raw_args = _parse_json_block(response.content)
            if not isinstance(raw_args, list):
                raw_args = raw_args.get("arguments", [])
        except json.JSONDecodeError as exc:
            raise ValueError("Argument agent returned invalid JSON") from exc

        arguments: list[ArgumentHypothesis] = []
        for raw in raw_args:
            # Validate citations — only allow those from retrieved precedents
            raw_citations = raw.get("supporting_citations", [])
            validated_citations: list[CitationRecord] = []
            for rc in raw_citations:
                sid = rc.get("source_id", "")
                if sid in valid_source_ids:
                    validated_citations.append(retrieved_sources[sid])
                else:
                    logger.warning(
                        "Argument builder tried to use citation not in retrieved set: %s — stripped.", sid
                    )

            # Reject any win-probability framing
            confidence = raw.get("confidence_status", "partial")
            if confidence not in ("supported", "partial", "unsupported"):
                confidence = "partial"
            if not validated_citations:
                confidence = "unsupported"

            try:
                arguments.append(ArgumentHypothesis(
                    proposition=raw.get("proposition", ""),
                    supporting_fact_refs=raw.get("supporting_fact_refs", []),
                    supporting_citations=validated_citations,
                    missing_evidence=raw.get("missing_evidence", []),
                    strongest_counterargument=raw.get("strongest_counterargument", ""),
                    confidence_status=confidence,
                ))
            except Exception as parse_err:
                logger.warning("Could not parse argument hypothesis: %s", parse_err)

        await _broadcast("argument_builder", "completed", "", f"Built {len(arguments)} arguments")
        return {"arguments": arguments}

    except Exception as exc:
        logger.error("argument_builder_node error: %s", exc, exc_info=True)
        await _broadcast("argument_builder", "completed", "", "Failed to build arguments")
        raise RuntimeError("Client argument analysis failed") from exc


# ---------------------------------------------------------------------------
# Node 5 — Readiness & Evidence-Gap Analysis  [Flash]
# ---------------------------------------------------------------------------

_FORBIDDEN_FIELDS = {"win_probability", "win_chance", "success_rate", "odds", "likelihood_of_success"}


async def readiness_analysis_node(state: CaseState) -> dict:
    """
    Factor-level readiness assessment only. No win probability, ever.
    Validated by checking LLM output for forbidden field names.
    """
    await _broadcast("readiness_analysis", "start", "Readiness Agent: Scoring case completeness...")
    try:
        llm = _flash_llm()
        facts = state.get("facts", [])
        flags = state.get("fuzziness_flags", [])
        precedents = state.get("precedents", [])

        from app.legal_data.Motor_accident_schema import MOTOR_ACCIDENT_FIELDS
        schema_field_names = [f["field_name"] for f in MOTOR_ACCIDENT_FIELDS]

        system_prompt = inject_policy(READINESS_ANALYSIS_PROMPT.format(
            facts_json=_to_json(facts),
            fuzziness_flags=_to_json(flags),
            retrieved_citations_json=_to_json(precedents),
            property_schema_fields=json.dumps(schema_field_names),
        ))

        response = await llm.ainvoke([
            ("system", system_prompt),
            ("human", "Return ReadinessSignals JSON. Keys: evidence_completeness (float), evidence_completeness_reason, precedent_alignment, precedent_alignment_reason, open_fuzziness_load (int), open_fuzziness_details, documentary_corroboration (float), documentary_corroboration_reason, lawyer_summary. NO win probability field."),
        ])

        try:
            parsed = _parse_json_block(response.content)
        except json.JSONDecodeError:
            parsed = {}

        # Reject any win-probability field
        for forbidden in _FORBIDDEN_FIELDS:
            if forbidden in parsed:
                del parsed[forbidden]
                logger.warning("Readiness node stripped forbidden field: %s", forbidden)

        # Compute defaults from state for any missing fields
        filled_fields = {f.field for f in facts}
        schema_fields = set(schema_field_names)
        completeness = len(filled_fields & schema_fields) / max(len(schema_fields), 1)
        open_high_flags = [f for f in flags if not f.resolved and f.severity in ("high", "medium")]
        doc_facts = [f for f in facts if f.evidence_type == "DOCUMENT_EXTRACTED"]
        doc_corr = len(doc_facts) / max(len(facts), 1)

        signals = ReadinessSignals(
            evidence_completeness=parsed.get("evidence_completeness", round(completeness, 2)),
            evidence_completeness_reason=parsed.get(
                "evidence_completeness_reason",
                f"{len(filled_fields & schema_fields)} of {len(schema_fields)} schema fields filled"
            ),
            precedent_alignment=parsed.get("precedent_alignment", "none" if not precedents else "unclear"),
            precedent_alignment_reason=parsed.get(
                "precedent_alignment_reason",
                f"{len(precedents)} judgments retrieved"
            ),
            open_fuzziness_load=parsed.get("open_fuzziness_load", len(open_high_flags)),
            open_fuzziness_details=parsed.get(
                "open_fuzziness_details",
                f"{len(open_high_flags)} medium/high severity unresolved flags"
            ),
            documentary_corroboration=parsed.get("documentary_corroboration", round(doc_corr, 2)),
            documentary_corroboration_reason=parsed.get(
                "documentary_corroboration_reason",
                f"{len(doc_facts)} document-extracted facts of {len(facts)} total"
            ),
            lawyer_summary=parsed.get(
                "lawyer_summary",
                "Review the evidence completeness and open flags before filing."
            ),
        )

        await _broadcast("readiness_analysis", "completed", "", "Scored case completeness")
        return {"readiness_signals": signals}

    except Exception as exc:
        logger.error("readiness_analysis_node error: %s", exc, exc_info=True)
        await _broadcast("readiness_analysis", "completed", "", "Failed to score case completeness")
        raise RuntimeError("Readiness analysis service failed") from exc


# ---------------------------------------------------------------------------
# Node 6 — Packet Compiler  [Flash]
# ---------------------------------------------------------------------------

async def packet_compiler_node(state: CaseState) -> dict:
    """Compile actual graph outputs into the fixed seven-section packet.

    Citation and evidence records are copied from the validated graph state,
    never regenerated by a language model during formatting.
    """
    await _broadcast("packet_compiler", "start", "Packet Compiler: Drafting final lawyer case packet...")
    def serial(value):
        if hasattr(value, "model_dump"):
            return serial(value.model_dump())
        if isinstance(value, dict):
            return {key: serial(item) for key, item in value.items()}
        if isinstance(value, list):
            return [serial(item) for item in value]
        return value

    facts = serial(state.get("facts", []))
    sources = serial(state.get("precedents", []))
    flags = [flag for flag in serial(state.get("fuzziness_flags", [])) if not flag.get("resolved")]
    readiness = serial(state.get("readiness_signals"))
    opposition = {**(state.get("opposition_case") or {}), **(state.get("opposition_analysis_dict") or {})}
    investigation_targets = [{
        "target_id": flag["flag_id"], "severity": flag["severity"],
        "task": flag["neutral_clarifying_question"], "reason": flag["explanation"],
        "fact_refs": flag["fact_refs"],
    } for flag in flags]
    for index, task in enumerate(opposition.get("investigation_targets", [])):
        investigation_targets.append({"target_id": f"opposition-{index + 1}", "task": task, "reason": "Opposition analysis requires lawyer verification", "fact_refs": []})
    narrative = "\n\n".join(fact["value"] for fact in facts if fact["field"] == "how_accident_happened")
    packet = {
        "initial_details": {
            "incident_narrative": narrative or "The incident account has not been established.",
            "chronological_timeline": serial(state.get("timeline", [])),
            "client_profile": serial(state.get("client_profile") or {}),
            "victim_profile": serial(state.get("victim_profile") or {}),
            "facts": facts,
            "documents": serial(state.get("documents", [])),
        },
        "opposition_case": serial(opposition),
        "precedents": [source for source in sources if source.get("source_type") != "statute"],
        "fuzziness_and_gaps": {"flags": flags, "investigation_targets": investigation_targets, "analysis_limitations": state.get("analysis_limitations", [])},
        "law_sections": [source for source in sources if source.get("source_type") == "statute" or source.get("source_id", "").startswith("STATUTE_")],
        "our_arguments": {"arguments": serial(state.get("arguments", [])), "witness_candidates": serial(state.get("witness_candidates", []))},
        "win_probability": {
            "score": None,
            "label": "Requires lawyer assessment",
            "reasoning": (readiness or {}).get("lawyer_summary", "The evidence and retrieved authorities require individual lawyer review."),
            "caveat": "A numerical outcome probability cannot be established from an intake interview. Evidence-readiness factors are not win probabilities.",
            "readiness_signals": readiness,
        },
    }
    sections = [
        ("Initial Details (Incident, Timeline, Profiles)", "initial_details"),
        ("Opposition Side's Case (Charges validity, opposing strong points)", "opposition_case"),
        ("Precedents (Analysis of similar past proceedings)", "precedents"),
        ("Fuzziness & Missing Clarity (Areas requiring manual lawyer investigation)", "fuzziness_and_gaps"),
        ("Relevant Law Sections", "law_sections"),
        ("Strong Points & Arguments (Our side)", "our_arguments"),
        ("Win Probability Assessment", "win_probability"),
    ]

    def render(value, level=3):
        if value in (None, "", [], {}):
            return "Not established in the current case record.\n"
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                title = key.replace("_", " ").title()
                parts.append(f"{'#' * min(level, 6)} {title}\n\n{render(item, level + 1)}")
            return "\n".join(parts)
        if isinstance(value, list):
            return "\n\n".join(render(item, level) if isinstance(item, (dict, list)) else f"- {item}" for item in value) + "\n"
        return f"{value}\n"

    markdown = "# NyayaLens — Confidential Lawyer Review Packet\n\n" + "\n".join(
        f"## {title}\n\n{render(packet[key])}" for title, key in sections
    )
    packet["whatsapp_summary"] = (
        f"Client interview: {len(facts)} recorded facts, {len(state.get('timeline', []))} timeline entries, "
        f"{len(flags)} unresolved issues and {len(sources)} retrieved legal sources. "
        f"{(readiness or {}).get('lawyer_summary', 'Please review the packet and investigation targets before deciding next steps.')}"
    )
    await _broadcast("packet_compiler", "completed", "", "Compiled case packet from validated evidence and analysis")
    return {"lawyer_packet_markdown": markdown, "lawyer_packet_json": packet, "investigation_targets": investigation_targets}


# ---------------------------------------------------------------------------
# Standalone — Lawyer Follow-Up Chat  [Flash]
# Used directly from the API layer, not in the graph
# ---------------------------------------------------------------------------

async def lawyer_chat(question: str, packet_json: dict, thread_id: str) -> dict:
    """
    Answers a lawyer's follow-up question grounded in the case packet.
    Same citation discipline as every other agent.
    """
    try:
        llm = _flash_llm()
        system_prompt = inject_policy(LAWYER_CHAT_PROMPT.format(
            case_thread_id=thread_id,
            lawyer_packet_json=json.dumps(packet_json, ensure_ascii=False, indent=2),
        ))
        response = await llm.ainvoke([
            ("system", system_prompt),
            ("human", question),
        ])
        text = response.content
        if isinstance(text, list):
            text = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in text)
        sources = packet_json.get("precedents", []) + packet_json.get("law_sections", [])
        return {
            "answer": text,
            "citations_used": [source for source in sources if source.get("source_id", "") in text or source.get("exact_citation", "") in text],
        }
    except Exception as exc:
        logger.error("lawyer_chat error: %s", exc, exc_info=True)
        raise RuntimeError("Case follow-up service is temporarily unavailable") from exc
