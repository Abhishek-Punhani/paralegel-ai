"""Opt-in real-provider smoke scenario; creates and deletes its own case.

Run from backend/: .venv/bin/python scripts/verify_live.py [BASE_URL]
Uses the local JWT_SECRET for its own test owner. It never creates product
fixtures or substitutes provider responses. Raw test answers are synthetic
inputs sent through the real intake, speech, research and analysis services.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

ANSWERS = {
    "departure_and_route": "I left my home in Lajpat Nagar at 8:40 AM and was travelling to my workplace in Nehru Place by the main road.",
    "road_and_visibility": "The road was dry and it was clear daylight with normal visibility.",
    "vehicle_positions_and_movement": "I was going straight in the left lane. The white car came from the road on my right.",
    "traffic_controls_and_priority": "I directly saw a green light for my lane, but I could not see the other driver's signal.",
    "speed_and_observation": "My speed was around 35 kilometres per hour; I cannot reliably estimate the car's speed.",
    "impact_and_avoidance": "I applied the brakes when the car entered the crossing. Its front hit the right side of my motorcycle.",
    "people_involved": "I, Ramesh Kumar, was the only injured person. Shopkeeper Suresh was a witness and was not injured.",
    "medical_bills_available": "AIIMS discharge summary, X-ray and treatment bills of 42000 rupees are available.",
    "victim_age_and_dob": "The injured person is me, Ramesh Kumar, age 34, born on 15 March 1992.",
    "victim_occupation_and_employer": "I am the injured person, and I work as an electrician at Metro Services.",
    "victim_income_and_proof": "The injured person is me. My monthly salary is 28000 rupees, supported by salary slips and bank credits.",
    "victim_relationship_to_client": "I am that injured person myself.",
    "witnesses_available": "Yes, Suresh saw the collision and helped me.",
    "witness_details": "Shopkeeper Suresh saw the vehicles collide and called the ambulance. I can obtain his number from the shop, but do not have it now.",
    "property_or_vehicle_damage": "The motorcycle's right side and fuel tank were damaged. The repair estimate is 18000 rupees.",
    "police_reported": "Yes, the accident was reported to Lajpat Nagar police station that day.",
    "fir_or_police_report_status": "FIR number 241 of 2026 is registered at Lajpat Nagar police station.",
    "fir_charges_and_sections": "The FIR records BNS 281 and 125 against the car driver. There are no charges against me.",
    "insurance_and_documents_available": "I have my valid driving licence, RC, third party insurance policy, FIR and hospital records. I will upload them later.",
    "full_name": "My full name is Ramesh Kumar.",
    "age": "I am 34 years old.",
    "education_qualification": "I completed ITI training after Class 12.",
    "occupation": "I am an electrician working for Metro Services.",
    "employment_type": "I am a permanent salaried employee.",
    "employer_name": "My employer is Metro Services.",
    "monthly_income": "My monthly salary is 28000 rupees.",
    "income_proof_type": "I have salary slips and bank statements showing the salary credits.",
    "dependents": "My wife and two children depend on my income.",
    "pre_existing_conditions": "I had no prior illness or injury affecting my right leg.",
    "disability_percentage": "No permanent disability assessment has been completed yet.",
    "functional_disability_impact": "I cannot stand for long or climb ladders and have missed three weeks of work.",
    "driving_license_number": "I do not remember the licence number; it is on the licence I will upload.",
    "driving_license_validity": "My licence was valid on the accident date and authorizes motorcycles.",
    "criminal_history": "There is no pending or previous police case against me.",
    "helmet_or_seatbelt": "I was wearing my helmet with the strap fastened.",
    "intoxication_allegations": "There is no allegation of alcohol or drugs in the hospital or police record as far as I know.",
    "available_camera_or_photos": "Suresh says a nearby shop might have CCTV, but I have not obtained it or watched any recording.",
    "accident_location": "The collision happened at the main crossing in Lajpat Nagar, Delhi.",
    "vehicle_details": "I was riding my Honda motorcycle DL3SAB1234.",
    "was_driving": "Yes, I was driving my motorcycle.",
    "other_party_vehicle_and_identity": "The other vehicle was a white Maruti Swift DL1CAB7788. I do not know the driver's name.",
    "immediate_actions_taken": "Suresh called an ambulance at 9:10 AM. I reached AIIMS at 9:40 AM and reported to the police at 4 PM that day.",
}


def signed_token(owner: str) -> str:
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    raw = f"{encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode({'lawyerId': owner, 'exp': int(time.time()) + 3600})}"
    sig = hmac.new(os.environ["JWT_SECRET"].encode(), raw.encode(), hashlib.sha256).digest()
    return raw + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


async def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    owner = "verification-" + uuid.uuid4().hex
    async with httpx.AsyncClient(base_url=base, timeout=150, headers={"Authorization": "Bearer " + signed_token(owner)}) as client:
        response = await client.post("/api/session/create", json={"language": "en", "lawyer_name": "Live verification", "lawyer_id": owner})
        response.raise_for_status()
        session = response.json()["thread_id"]
        print("Created isolated live verification case:", session, flush=True)
        try:
            response = await client.post(f"/api/voice/{session}/start", json={"language": "en"})
            response.raise_for_status()
            reply = response.json()
            assert reply.get("audio_base64"), reply
            narrative = "My name is Ramesh Kumar, age 34. On 10 October 2026 at 9 AM my motorcycle DL3SAB1234 was hit by a white car DL1CAB7788 at Lajpat Nagar crossing, Delhi. I was in the left lane going straight with a green light. The car came from the road on my right. My right leg fractured. Shopkeeper Suresh called an ambulance at 9:10 AM. I reached AIIMS at 9:40 AM. Police registered FIR 241/2026 under BNS sections 281 and 125 against the car driver, not me."
            seen_conflict = False
            inserted_conflict = False
            for turn in range(65):
                print("Question", turn, reply.get("question_key") or reply.get("consent_step"), reply.get("spoken_response"), flush=True)
                assert not any(phrase in reply.get("spoken_response", "").lower() for phrase in ("aur bataiye", "aur batayiye", "tell me more"))
                if reply.get("complete"):
                    break
                key = reply.get("question_key")
                if turn == 0:
                    answer = narrative
                elif not inserted_conflict and key != "accident_datetime":
                    answer = "The accident happened on 12 October 2026 at 9 AM."
                    inserted_conflict = True
                elif key == "accident_datetime":
                    answer = "I need to correct my earlier statement: the accident was on 10 October 2026 at 9 AM. I checked the hospital admission record."
                elif reply.get("consent_step"):
                    answer = "Yes, I agree to this step and authorize it."
                else:
                    answer = ANSWERS.get(key, "I do not know or remember that information.")
                response = await client.post(f"/api/voice/{session}/turn", data={"language": "en", "text": answer})
                if response.status_code == 503 and response.json().get("requires_retry"):
                    response = await client.post(f"/api/voice/{session}/retry", json={"language": "en"})
                response.raise_for_status()
                reply = response.json()
                state_response = await client.get(f"/api/session/{session}")
                state_response.raise_for_status()
                state = state_response.json()["state"]
                seen_conflict |= any(flag["flag_type"] == "contradiction" and any("accident_datetime" in ref for ref in flag.get("fact_refs", [])) for flag in state.get("fuzziness_flags", []))
            else:
                raise AssertionError("Interview failed to finish within its bounded question bank")
            assert seen_conflict, "The contradictory date was not flagged"
            assert reply["complete"], reply
            assert len(state.get("timeline", [])) >= 3
            assert state.get("client_profile") and state.get("victim_profile")
            print("Interview completed with", len(state["facts"]), "facts,", len(state["timeline"]), "timeline events; contradiction detection passed", flush=True)
            response = await client.post(f"/api/session/{session}/accept-case")
            response.raise_for_status()
            async with client.stream("GET", f"/api/notifications/analysis/stream?session_id={session}", timeout=420) as events:
                events.raise_for_status()
                async for line in events.aiter_lines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        print("Analysis", event.get("event"), event.get("status"), event.get("content", {}).get("message", ""), flush=True)
                        if event.get("event") == "analysis_error":
                            raise AssertionError(event)
                        if event.get("event") == "analysis_complete":
                            break
            response = await client.get(f"/api/session/{session}/packet")
            response.raise_for_status()
            packet = response.json()["json"]
            assert set(("initial_details", "opposition_case", "precedents", "fuzziness_and_gaps", "law_sections", "our_arguments", "win_probability")) <= set(packet)
            print("Seven-section packet ready:", len(packet["precedents"]), "judgments,", len(packet["law_sections"]), "statutes", flush=True)
            response = await client.post(f"/api/session/{session}/chat", json={"question": "What missing evidence should counsel investigate first? Cite only the case packet."})
            response.raise_for_status()
            assert response.json().get("answer")
            print("Live packet follow-up chat passed", flush=True)
        finally:
            response = await client.delete(f"/api/session/{session}")
            print("Verification case cleanup:", response.status_code, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
