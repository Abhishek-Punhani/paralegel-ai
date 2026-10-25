"""Regression coverage for persistent intake, consent, and packet evidence."""
import asyncio
import sqlite3

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graphs.checkpoints import PersistentSqliteSaver
from app.intake_engine.engine import (
    Extraction, MergeError, NewPerson, TimelineEvent, Update,
    merge, new_intake, project_profile, project_timeline, project_victim_profile,
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
    assert prompt["key"] == "how_accident_happened"
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
