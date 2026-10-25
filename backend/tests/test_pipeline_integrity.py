"""Regression coverage for persistent intake, consent, and packet evidence."""
import asyncio
import sqlite3

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graphs.checkpoints import PersistentSqliteSaver
from app.intake_engine.engine import (
    Extraction, MergeError, NewPerson, TimelineEvent, Update,
    merge, new_intake, process_turn, project_profile, project_timeline, project_victim_profile,
)
from app.state import CaseState, CitationRecord, ConsentRecord, Fact


def test_explicit_accident_date_does_not_depend_on_model_paraphrase():
    from app.intake_engine.extractor import explicit_accident_date
    assert explicit_accident_date("The accident happened on 12 October 2026 at 9 AM.", "was_driving") == ("2026-10-12", "12 October 2026")
    assert explicit_accident_date("My birthday is 12 October 1992.", "dob") is None
    assert explicit_accident_date("The accident was either 10 October 2026 or 12 October 2026.", "accident_datetime") is None


def test_persistent_graph_can_resume_after_rebuilding(tmp_path):
    from app.graphs.intake_graph import build_intake_graph

    path = str(tmp_path / "intake.db")
    first = PersistentSqliteSaver(sqlite3.connect(path, check_same_thread=False))
    graph = build_intake_graph(first)
    config = {"configurable": {"thread_id": "persistent-client"}}
    asyncio.run(graph.ainvoke({"thread_id": "persistent-client", "language": "en", "messages": [], "facts": [], "documents": [], "fuzziness_flags": [], "consent": ConsentRecord()}, config))
    prompt = graph.get_state(config).tasks[0].interrupts[0].value
    assert prompt["key"] == "consultation_reason"
    second = PersistentSqliteSaver(sqlite3.connect(path, check_same_thread=False))
    restored = build_intake_graph(second)
    assert restored.get_state(config).tasks[0].interrupts[0].value == prompt
    assert restored.get_state(config).values["thread_id"] == "persistent-client"
    first.conn.close()
    second.conn.close()


def test_graphs_do_not_share_checkpoints():
    from app.graphs.intake_graph import intake_graph
    from app.graphs.analysis_graph import analysis_graph
    assert intake_graph.checkpointer is not analysis_graph.checkpointer
    assert intake_graph.checkpointer.conn is not analysis_graph.checkpointer.conn


def test_completed_intake_enters_all_four_confirmation_steps(monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from app.agents import intake_agents
    from app.graphs.intake_graph import build_intake_graph

    async def yes(*_args):
        return "yes", "Explicit permission"

    monkeypatch.setattr(intake_agents, "_judge_consent", yes)
    monkeypatch.setattr(intake_agents, "_flash_llm", lambda: object())
    intake = new_intake()
    for field in intake["fields"].values():
        field["status"] = "unknown"
    graph = build_intake_graph(MemorySaver())
    config = {"configurable": {"thread_id": "consent-client"}}

    async def flow():
        await graph.ainvoke({"thread_id": "consent-client", "language": "en", "messages": [], "facts": [], "documents": [], "fuzziness_flags": [], "consent": ConsentRecord(), "handoff_status": "pending", "intake_engine_state": intake}, config)
        for expected in ("recipient", "contents", "attachments", "permission"):
            value = graph.get_state(config).tasks[0].interrupts[0].value
            assert value["consent_step"] == expected
            await graph.ainvoke(Command(resume="Yes, I agree"), config)
        final = graph.get_state(config)
        assert final.next == ()
        assert final.values["intake_phase"] == "complete"
        assert final.values["handoff_status"] == "confirmed"
        assert final.values["consent"].timestamp

    asyncio.run(flow())


def test_chronology_requires_quotes_and_preserves_real_order():
    text = "I left at 9. The crash was at 10. The hospital admitted me at 11."
    extraction = Extraction(timeline_events=[
        TimelineEvent(event="Hospital admission", quote="hospital admitted me at 11", date="11:00", sequence=3, certainty="exact"),
        TimelineEvent(event="Departure", quote="I left at 9", date="09:00", sequence=1, certainty="exact"),
        TimelineEvent(event="Crash", quote="crash was at 10", date="10:00", sequence=2, certainty="exact"),
    ])
    intake = merge(new_intake(), extraction, "turn-1", text)
    timeline = project_timeline(intake)
    assert [event["event"] for event in timeline] == ["Departure", "Crash", "Hospital admission"]
    assert all(event["source_ref"] == "turn-1" for event in timeline)
    with pytest.raises(MergeError):
        merge(intake, Extraction(timeline_events=[TimelineEvent(event="Invented", quote="never said")]), "turn-2", text)


def test_client_and_victim_profiles_are_not_conflated():
    text = "I am Ramesh, 45. My daughter Sita is 12."
    extraction = Extraction(
        people=[NewPerson(id="p1", label="daughter Sita", quote="daughter Sita")],
        updates=[
            Update(field="full_name", value="Ramesh", status="answered", quote="Ramesh"),
            Update(field="age", value="45", status="answered", quote="45"),
            Update(field="victim_age_and_dob", person_id="p1", value="12", status="answered", quote="Sita is 12"),
        ],
    )
    intake = merge(new_intake(), extraction, "turn-profile", text)
    assert project_profile(intake)["age"] == 45
    victim = project_victim_profile(intake)["people"][0]
    assert victim["fields"]["victim_age_and_dob"]["value"] == "12"


def test_explicit_self_profile_reuses_grounded_facts_with_provenance():
    text = (
        "I am Ramesh, age 34, an electrician earning 28000 monthly. "
        "I have salary slips, support my wife and child, had no previous injury, "
        "have 20 percent disability, and cannot climb ladders."
    )
    values = {
        "full_name": ("Ramesh", "Ramesh"),
        "age": ("34", "34"),
        "occupation": ("electrician", "electrician"),
        "monthly_income": ("28000", "28000"),
        "income_proof_type": ("salary slips", "salary slips"),
        "dependents": ("wife and child", "wife and child"),
        "pre_existing_conditions": ("no previous injury", "no previous injury"),
        "disability_percentage": ("20", "20 percent disability"),
        "functional_disability_impact": ("cannot climb ladders", "cannot climb ladders"),
    }
    intake = process_turn(new_intake(), Extraction(
        people=[NewPerson(id="p1", label="Ramesh", quote="Ramesh")],
        updates=[Update(field=key, value=value, quote=quote, status="answered") for key, (value, quote) in values.items()],
    ), "profile-turn", text, None)
    assert intake["people"]["p1"]["fields"].get("victim_full_name", {}).get("value") is None

    answer = "I am the injured person."
    intake = process_turn(intake, Extraction(updates=[Update(
        field="victim_relationship_to_client", person_id="p1", value="self", quote="I am the injured person", status="answered",
    )]), "identity-turn", answer, None)
    mappings = {
        "full_name": "victim_full_name", "age": "victim_age_and_dob",
        "occupation": "victim_occupation_and_employer", "monthly_income": "victim_income_and_proof",
        "income_proof_type": "victim_income_proof", "dependents": "victim_dependents",
        "pre_existing_conditions": "victim_pre_existing_conditions",
        "disability_percentage": "victim_disability_assessment",
        "functional_disability_impact": "victim_functional_impact",
    }
    for source, target in mappings.items():
        original = intake["fields"][source]
        copied = intake["people"]["p1"]["fields"][target]
        assert copied == original
        assert copied is not original
        assert copied["history"] is not original["history"]
        assert copied["source"] == "profile-turn"
        assert copied["quote"] in text


def test_client_profile_never_bleeds_into_daughter_profile():
    text = "I am Ramesh, 45. My daughter Sita is 12."
    intake = process_turn(new_intake(), Extraction(
        people=[NewPerson(id="p1", label="daughter Sita", quote="daughter Sita")],
        updates=[
            Update(field="full_name", value="Ramesh", status="answered", quote="Ramesh"),
            Update(field="age", value="45", status="answered", quote="45"),
            Update(field="victim_age_and_dob", person_id="p1", value="12", status="answered", quote="Sita is 12"),
            Update(field="victim_relationship_to_client", person_id="p1", value="daughter", status="answered", quote="My daughter Sita"),
        ],
    ), "family-turn", text, None)
    assert project_profile(intake)["full_name"] == "Ramesh"
    victim = project_victim_profile(intake)["people"][0]["fields"]
    assert victim["victim_age_and_dob"]["value"] == "12"
    assert "victim_full_name" not in victim


def test_self_profile_reuse_preserves_victim_unknowns_and_independent_facts():
    text = "I am Ramesh and earn 28000. I am the injured person. I do not want to provide victim income proof."
    intake = process_turn(new_intake(), Extraction(
        people=[NewPerson(id="p1", label="Ramesh", quote="Ramesh")],
        updates=[
            Update(field="monthly_income", value="28000", status="answered", quote="28000"),
            Update(field="victim_relationship_to_client", person_id="p1", value="self", status="answered", quote="I am the injured person"),
            Update(field="victim_income_and_proof", person_id="p1", value=None, status="declined", quote="I do not want to provide victim income proof"),
        ],
    ), "private-turn", text, None)
    victim_income = intake["people"]["p1"]["fields"]["victim_income_and_proof"]
    assert victim_income["status"] == "declined"
    assert victim_income["value"] is None


def test_packet_contains_actual_citations_and_all_seven_sections():
    from app.agents.analysis_agents import packet_compiler_node

    statute = CitationRecord(source_id="STATUTE_MVA_166", exact_citation="Motor Vehicles Act, section 166", supporting_passage="Source text", jurisdiction="India", date="1988", applicability_status="unclear", source_type="statute")
    judgment = CitationRecord(source_id="IK-123", exact_citation="Retrieved case", supporting_passage="Retrieved passage", jurisdiction="India", date="2020", applicability_status="unclear")
    fact = Fact(fact_id="F1", field="how_accident_happened", value="A car struck the client's bicycle.", evidence_type="CLIENT_STATED", source_ref="turn-1", confidence=.8, status="unconfirmed", contradicts=[])
    result = asyncio.run(packet_compiler_node({"facts": [fact], "precedents": [statute, judgment], "fuzziness_flags": [], "timeline": [], "documents": [], "arguments": [], "witness_candidates": [], "opposition_case": {}, "opposition_analysis_dict": {"charges_analysis": []}}))
    packet = result["lawyer_packet_json"]
    assert packet["law_sections"] == [statute.model_dump()]
    assert packet["precedents"] == [judgment.model_dump()]
    assert packet["initial_details"]["incident_narrative"] == fact.value
    assert packet["win_probability"]["score"] is None
    assert result["lawyer_packet_markdown"].count("\n## ") == 7


def test_document_prompt_does_not_mark_missing_file_uploaded():
    from langgraph.checkpoint.memory import MemorySaver
    from app.agents.intake_agents import document_request_node
    from app.state import DocumentRecord

    graph_builder = StateGraph(CaseState)
    graph_builder.add_node("request", document_request_node)
    graph_builder.add_edge(START, "request")
    graph_builder.add_edge("request", END)
    graph = graph_builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "document-client"}}
    doc = DocumentRecord(doc_id="DOC-actual", doc_type="fir_copy", upload_status="requested")

    async def flow():
        await graph.ainvoke({"documents": [doc], "language": "en", "messages": []}, config)
        await graph.ainvoke(Command(resume="I will upload it later"), config)
        state = graph.get_state(config).values
        assert state["documents"][0].upload_status == "requested"
        assert state["document_requests_notified"] == ["DOC-actual"]

    asyncio.run(flow())
