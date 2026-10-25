"""
Motor-accident (claimant side) question bank.

Design (ported from Nyaya-Lens-2.0): the *code* decides what to ask next; the LLM
only extracts facts. Every key that appears in MOTOR_ACCIDENT_FIELDS is a key here,
so downstream readiness/completeness scoring keeps working. Extra keys (suffix noted
below) exist only to gate follow-ups.

Question text is fixed Hinglish (text_hi) / English (text_en) so the voice agent can
speak it verbatim and the stored transcript always matches what the client heard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

CLARIFY_CAP = 2  # max asks per field before we move on and leave it for the lawyer


@dataclass(frozen=True)
class Question:
    key: str
    stage: str            # interview_stage label exposed to the UI
    text_hi: str
    text_en: str
    kind: str = "text"    # text | bool | date
    parent: Optional[str] = None
    person: bool = False
    # Extra applicability rule over the *global* fields dict; None means always.
    gate: Optional[Callable[[dict], bool]] = None


def _val(fields: dict, key: str) -> str:
    f = fields.get(key) or {}
    v = f.get("value")
    return str(v).lower() if v is not None else ""


_NON_EARNING = (
    "student", "vidyarthi", "homemaker", "housewife", "grihini", "ghar",
    "retired", "pension", "unemployed", "bekaar", "berozgar", "child", "bachcha",
)


def _earning(fields: dict) -> bool:
    occ = _val(fields, "occupation")
    return bool(occ) and not any(tok in occ for tok in _NON_EARNING)


def _date_unresolved(fields: dict) -> bool:
    return (fields.get("accident_datetime") or {}).get("status") != "answered"


Q = Question
QUESTIONS: list[Question] = [
    # Welcome first; never open by assuming the client has already told a story.
    Q("consultation_reason", "engage",
      "नमस्ते! मैं न्याया हूँ, आपके वकील की AI पैरालीगल सहायक। मैं आपकी बात सुनकर घटना का क्रम, संबंधित लोगों की जानकारी और ज़रूरी दस्तावेज़ आपके वकील के लिए व्यवस्थित करूँगी। आज आपको किस मामले में मदद चाहिए?",
      "Hello! I’m Nyaya, your advocate’s AI paralegal assistant. I’ll listen to you and help organize the incident, the people involved, and relevant documents for your advocate. What would you like help with today?"),
    Q("full_name", "engage",
      "सबसे पहले, मैं आपको किस नाम से बुला सकती हूँ? कृपया अपना पूरा नाम बताइए।",
      "First, what should I call you? Please tell me your full name."),
    Q("client_role", "engage",
      "इस मामले में आपकी क्या भूमिका है—आप खुद घायल हुए हैं, किसी घायल व्यक्ति के परिवार से हैं, वाहन चला रहे थे, या किसी और तरह जुड़े हैं?",
      "How are you involved in this matter—as the injured person, a family member, a driver, or in another role?"),
    # ── Narrative ──────────────────────────────────────────────────────────
    Q("how_accident_happened", "narrative",
      "समझ गई। अब आराम से अपनी बात शुरू से बताइए—हादसे से पहले आप कहाँ थे, क्या हुआ और उसके बाद क्या हुआ। कोई बात याद नहीं हो तो अंदाज़ा लगाने की ज़रूरत नहीं है।",
      "I understand. Please take your time and describe what happened, starting before the accident and continuing through what happened afterwards. You do not need to guess anything you cannot remember."),
    # ── Mechanics / liability ──────────────────────────────────────────────
    Q("accident_datetime", "timeline_liability",
      "Yeh haadsa kis tareekh ko hua tha? Saal ke saath bataiye, aur yaad ho to samay bhi.",
      "On what date did the accident happen? Please include the year, and the time if you remember.", kind="date"),
    Q("accident_location", "timeline_liability",
      "Haadsa kahan hua tha? Shehar, sadak aur aas-paas ka koi landmark bataiye.",
      "Where did it happen? Please give the city, road and a nearby landmark."),
    Q("vehicle_details", "timeline_liability",
      "Haadse ke samay aap kis vehicle mein ya kis tarah sadak par the? Vehicle ka type aur number bataiye.",
      "At the time, what vehicle were you in or how were you on the road? Please give the vehicle type and number."),
    Q("was_driving", "timeline_liability",
      "Kya haadse ke samay aap khud vehicle chala rahe the?",
      "Were you driving the vehicle yourself at the time?", kind="bool"),
    Q("other_party_vehicle_and_identity", "timeline_liability",
      "Doosri taraf kaun sa vehicle tha? Uska number ya driver ki koi jaankari yaad hai?",
      "What was the other vehicle? Do you remember its number or anything about its driver?"),
    Q("departure_and_route", "timeline_liability",
      "हादसे से पहले आप कहाँ से निकले और किस रास्ते से कहाँ जा रहे थे?",
      "Before the accident, where did you set out from and what route were you taking?"),
    Q("road_and_visibility", "timeline_liability",
      "हादसे की जगह सड़क, रोशनी और मौसम की स्थिति कैसी थी?",
      "What were the road, lighting and weather conditions at the scene?"),
    Q("vehicle_positions_and_movement", "timeline_liability",
      "टक्कर से ठीक पहले दोनों वाहन किस दिशा में और किस लेन में जा रहे थे?",
      "Immediately before impact, in which directions and lanes were the vehicles moving?"),
    Q("traffic_controls_and_priority", "timeline_liability",
      "उस जगह ट्रैफिक सिग्नल, चौराहा या रास्ता देने का कोई संकेत था तो आपने क्या देखा?",
      "What did you observe about traffic lights, crossings or give-way signs at that location?"),
    Q("speed_and_observation", "timeline_liability",
      "अपनी और दूसरे वाहन की रफ़्तार के बारे में आपको क्या सीधे याद है? अंदाज़ा हो तो बता दीजिए।",
      "What do you directly remember about your speed and the other vehicle's speed? Please say if either is an estimate."),
    Q("impact_and_avoidance", "timeline_liability",
      "टक्कर वाहन के किस हिस्से पर लगी और उससे ठीक पहले क्या हुआ?",
      "Which parts of the vehicles made contact, and what happened immediately before impact?"),
    Q("people_involved", "timeline_liability",
      "Is haadse mein kaun-kaun ghayal hua ya shaamil tha? Har vyakti ka naam ya rishta bataiye.",
      "Who was injured or involved in the accident? Please give each person's name or relationship."),
    Q("immediate_actions_taken", "timeline_liability",
      "Haadse ke turant baad kya-kya kiya gaya? Jaise police ko bulaya, aspatal le gaye, ya kisi ko khabar ki.",
      "What was done right after the accident? For example calling police, going to hospital, or informing someone."),
    Q("witnesses_available", "timeline_liability",
      "Kya kisi ne haadsa dekha ya madad ki?",
      "Did anyone see the accident or help afterwards?", kind="bool"),
    Q("witness_details", "timeline_liability",
      "Unka naam ya contact aur unhone kya dekha, yeh bataiye.",
      "What are their names or contacts, and what did they see?", parent="witnesses_available"),
    Q("property_or_vehicle_damage", "timeline_liability",
      "Vehicle ya saman ko kitna nuksan hua? Koi repair estimate ya bill hai?",
      "How much damage was done to the vehicle or property? Is there a repair estimate or bill?"),
    # ── Injuries (per injured person) ──────────────────────────────────────
    Q("injuries_and_medical_treatment", "timeline_liability",
      "{person} ko kaun si chotein aayi aur ilaaj kahan hua?",
      "What injuries did {person} suffer and where was the treatment?", person=True),
    Q("medical_bills_available", "timeline_liability",
      "{person} ke ilaaj ke bills ya medical records kya-kya available hain?",
      "What medical bills or records are available for {person}?", person=True),
    Q("victim_full_name", "quantum_profiling",
      "{person} का पूरा नाम क्या है, जैसा उनके दस्तावेज़ों में लिखा है?",
      "What is {person}'s full name as it appears on their records?", person=True),
    Q("victim_relationship_to_client", "quantum_profiling",
      "{person} का आपसे क्या रिश्ता है? अगर आप वही व्यक्ति हैं तो बता दीजिए।",
      "How is {person} related to you? Please tell me if you are that person.", person=True),
    Q("victim_outcome", "quantum_profiling",
      "{person} की अभी क्या स्थिति है—इलाज चल रहा है, स्वस्थ हो रहे हैं, या इस हादसे में उनकी मृत्यु हुई?",
      "What is {person}'s current situation—receiving treatment, recovering, or did they die as a result of the accident?", person=True),
    Q("victim_age_and_dob", "quantum_profiling",
      "{person} की उम्र या जन्मतिथि क्या है?",
      "What is {person}'s age or date of birth?", person=True),
    Q("victim_occupation_and_employer", "quantum_profiling",
      "हादसे से पहले {person} क्या काम करते थे?",
      "What work did {person} do before the accident?", person=True),
    Q("victim_income_and_proof", "quantum_profiling",
      "{person} की महीने की आय और उसका उपलब्ध प्रमाण क्या है?",
      "What was {person}'s monthly income and what proof is available?", person=True),
    Q("victim_income_proof", "quantum_profiling",
      "{person} की आय का कौन सा प्रमाण मिल सकता है, जैसे वेतन पर्ची, बैंक स्टेटमेंट या ITR?",
      "What proof of {person}'s income is available, such as salary slips, bank statements or tax returns?", person=True),
    Q("victim_dependents", "quantum_profiling",
      "{person} पर आर्थिक रूप से कौन-कौन निर्भर हैं? उनके रिश्ते और उम्र बताइए।",
      "Who depends financially on {person}? Please describe their relationships and ages.", person=True),
    Q("victim_treatment_timeline", "quantum_profiling",
      "{person} का किस अस्पताल में कब इलाज, भर्ती, ऑपरेशन या डिस्चार्ज हुआ? जो तारीखें याद हों वे बताइए।",
      "Where and when was {person} treated, admitted, operated on or discharged? Please give the dates you remember.", person=True),
    Q("victim_medical_expenses", "quantum_profiling",
      "{person} के इलाज, दवाइयों, आने-जाने और देखभाल पर अब तक लगभग कितना खर्च हुआ है?",
      "Approximately how much has been spent on {person}'s treatment, medicines, travel and care?", person=True),
    Q("victim_pre_existing_conditions", "quantum_profiling",
      "हादसे से पहले {person} को कोई ऐसी बीमारी या पुरानी चोट थी जो इस चोट से संबंधित हो?",
      "Did {person} have any pre-existing illness or injury relevant to the current injuries?", person=True),
    Q("victim_disability_assessment", "quantum_profiling",
      "क्या डॉक्टर या मेडिकल बोर्ड ने {person} की स्थायी विकलांगता का आकलन या प्रमाणपत्र दिया है?",
      "Has a doctor or medical board assessed or certified any permanent disability for {person}?", person=True),
    Q("victim_functional_impact", "quantum_profiling",
      "चोटों से {person} के काम और रोज़मर्रा के जीवन पर क्या असर पड़ा है?",
      "How have the injuries affected {person}'s work and everyday activities?", person=True),
    Q("victim_income_loss", "quantum_profiling",
      "हादसे के कारण {person} कितने दिन काम नहीं कर सके और कितनी आमदनी का नुकसान हुआ?",
      "How much work has {person} missed, and what income has been lost because of the accident?", person=True),
    # ── Police / regulatory ────────────────────────────────────────────────
    Q("police_reported", "regulatory",
      "Kya is haadse ki police ko report ki gayi?",
      "Was the accident reported to the police?", kind="bool"),
    Q("fir_or_police_report_status", "regulatory",
      "FIR darj hui? Thane ka naam, FIR number aur saal bataiye.",
      "Was an FIR registered? Please give the police station, FIR number and year.", parent="police_reported"),
    Q("fir_charges_and_sections", "regulatory",
      "FIR mein aapke khilaaf ya kisi doosre vyakti ke khilaaf kaunse kanooni sections ya charges likhe hain? Agar section number yaad na ho, FIR ki photo upload kar sakte hain.",
      "Which legal sections or charges does the FIR record against you or anyone else? If you do not remember the section numbers, you may upload a photo of the FIR.", parent="police_reported"),
    Q("insurance_and_documents_available", "regulatory",
      "Vehicle ke kaunse kagaz aapke paas hain — RC, insurance, driving licence?",
      "Which vehicle documents do you have — RC, insurance, driving licence?"),
    Q("limitation_check", "regulatory",
      "Yeh haadsa lagbhag kitne mahine pehle hua tha?",
      "Roughly how many months ago did the accident happen?", gate=_date_unresolved),
    # ── Client / victim profile (Sarla Verma / Pranay Sethi inputs) ────────
    Q("contact_phone", "quantum_profiling",
      "आपके वकील आपसे किस फोन नंबर पर संपर्क कर सकते हैं? साझा करना सहज न हो तो मना कर सकते हैं।",
      "What phone number can your advocate use to contact you? You may decline if you prefer."),
    Q("residential_location", "quantum_profiling",
      "आप अभी किस शहर और इलाके में रहते हैं?",
      "Which city and area do you currently live in?"),
    Q("age", "quantum_profiling",
      "आपकी अपनी उम्र कितनी है?",
      "What is your own age?"),
    Q("dob", "quantum_profiling",
      "Janm tithi yaad hai?", "Do you remember the date of birth?", gate=lambda f: (f.get("age") or {}).get("status") != "answered"),
    Q("education_qualification", "quantum_profiling",
      "Padhai kitni ki hai?", "How far did you study?"),
    Q("occupation", "quantum_profiling",
      "Kaam-dhandha kya karte hain?", "What work do you do?"),
    Q("employment_type", "quantum_profiling",
      "Naukri permanent hai, apna kaam hai, ya dihadi?",
      "Is the job permanent, self-employed, or daily wage?", parent="occupation", gate=_earning),
    Q("employer_name", "quantum_profiling",
      "Kis employer ya company mein kaam karte hain?",
      "Which employer or company do you work for?", parent="occupation", gate=_earning),
    Q("monthly_income", "quantum_profiling",
      "Mahine ki kamai lagbhag kitni hai?", "What is the approximate monthly income?",
      parent="occupation", gate=_earning),
    Q("income_proof_type", "quantum_profiling",
      "Income ka koi saboot hai — ITR, salary slip ya bank statement?",
      "Is there proof of income — ITR, salary slip or bank statement?", parent="monthly_income"),
    Q("dependents", "quantum_profiling",
      "Aap par kitne log nirbhar hain? Parivaar mein kaun-kaun hai?",
      "How many people depend on you? Who is in the family?"),
    Q("pre_existing_conditions", "quantum_profiling",
      "Haadse se pehle koi bimari ya purani chot thi?",
      "Was there any illness or old injury before the accident?"),
    Q("disability_percentage", "quantum_profiling",
      "Doctor ne koi disability certificate ya percentage bataya hai?",
      "Has a doctor given a disability certificate or percentage?"),
    Q("functional_disability_impact", "quantum_profiling",
      "Chot ki wajah se kaam ya roz ki zindagi par kya asar pada hai?",
      "How have the injuries affected work or daily life?", parent="disability_percentage"),
    # ── Defence audit ──────────────────────────────────────────────────────
    Q("driving_license_number", "defense_audit",
      "Aapke driving licence ka number yaad hai?",
      "Do you remember your driving licence number?", parent="was_driving"),
    Q("driving_license_validity", "defense_audit",
      "Haadse ke din licence valid tha?",
      "Was the licence valid on the day of the accident?", parent="was_driving"),
    Q("criminal_history", "defense_audit",
      "Kya aapke khilaf koi challan ya police case pending hai ya pehle raha hai?",
      "Is there any challan or police case pending or in the past against you?"),
    Q("helmet_or_seatbelt", "defense_audit",
      "हादसे के समय आपके लिए लागू हेलमेट या सीटबेल्ट पहनी गई थी?",
      "Was the applicable helmet or seatbelt being worn at the time?"),
    Q("intoxication_allegations", "defense_audit",
      "क्या पुलिस या अस्पताल के रिकॉर्ड में शराब या किसी नशे का आरोप लिखा है?",
      "Do the police or hospital records mention an allegation of alcohol or substance use?"),
    Q("available_camera_or_photos", "defense_audit",
      "क्या हादसे की तस्वीर, CCTV या डैशकैम की कोई रिकॉर्डिंग उपलब्ध है?",
      "Are photographs, CCTV or dashcam recordings of the accident available?"),
]

INDEX: dict[str, Question] = {q.key: q for q in QUESTIONS}
GLOBAL_KEYS = [q.key for q in QUESTIONS if not q.person]
PERSON_KEYS = [q.key for q in QUESTIONS if q.person]
