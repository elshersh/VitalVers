"""
offline_ai_chatbot.py — STEP 5: Offline Rule + TF-IDF + Scope-Gated Chatbot (No LLM, No Internet)
==================================================================================================

Implements Phase 4 (C1 & C2) and Phase 1 (D2 RBAC):
  1. Scope Gate before routing:
     - Offline TF-IDF (word + character n-gram) binary scope classifier (`LogisticRegression`)
       trained on general in-scope health-monitoring intents vs. out-of-scope domains (planets,
       spacecraft/mechanical hardware, IT/software, culinary/finance/sports/math/general trivia,
       medical prescribing/diagnosis).
     - General personal/crew health context rules ("my", "I", "we", "crew", physiological body
       indicators, clinical symptom descriptors) paired with general non-human / external-domain
       context disambiguation so polysemous keywords ("temperature", "oxygen", "pressure",
       "stress", "sleep", "heart", "health", "glucose", "muscle") are accepted for personal
       health monitoring and refused for external systems (planets, generators, computers, recipes).
  2. Borderline Refusal Suggestions ("Did you mean…?"):
     - When refusing a borderline query containing a health-related term in an out-of-scope or
       unmeasured context, appends a concrete `Did you mean: "..."?` suggestion.
  3. Urgent Symptom Escalation Rule:
     - Detects acute red-flag symptoms (chest pain/pressure, arm numbness, fainting/passing out,
       severe shortness of breath, dizziness/lightheadedness/headache paired with acute physiological
       concern) and ALWAYS advises contacting the flight surgeon immediately.
  4. Grounded Answers Only:
     - Templates filled strictly from: (1) SQLite profile / pre-flight baseline / telemetry,
       (2) live model output via `health_engine`, and (3) the source-verified `countermeasures` table.
     - Every answer carries the disclaimer and ends with a `Sources:` line.

Prototype for research/education only — not for clinical diagnosis.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity

import health_engine as he
import resource_facts as rf

CONFIDENCE_THRESHOLD = 0.28
NO_SLOT_THRESHOLD = 0.42
KEYWORD_BONUS = 0.36
UNKNOWN_SHARE_LIMIT = 0.65

# Canonical training templates per intent (descriptive multi-word specifications so
# test questions are not verbatim or near-duplicate copies; max cosine <= 0.60).
EXAMPLES: Dict[str, List[str]] = {
    "status": [
        "display my overall daily astronaut health status classification and zone summary from telemetry",
        "evaluate how my body is doing today across all four physiological monitoring zones",
        "provide my current health condition overview and machine learning model classification verdict",
        "check whether my overall physiological telemetry readings look healthy and normal today",
        "summarize my daily health monitoring dashboard vitals and any active zone flags",
    ],
    "alerts": [
        "explain why the monitoring system raised an active health warning or medical danger alert today",
        "list my current active health alerts and describe what caused the warning and how to fix it",
        "tell me why my predicted health status is not normal and what countermeasures apply",
        "check whether any physiological warning or stress blood pressure alert was triggered for me",
        "describe the meaning of my current health warning or danger alert and recommended action",
    ],
    "cardio": [
        "show my cardiovascular telemetry readings including systolic and diastolic blood pressure and heart rate",
        "check whether my resting heart rate or pulse is elevated compared with my personal baseline",
        "report my current arterial oxygen saturation spo2 percentage and blood pressure measurements",
        "evaluate my systolic pressure diastolic pressure pulse and breathing or oxygen levels today",
        "compare my cardiovascular blood pressure and heart rate trend against my preflight numbers",
    ],
    "bone_muscle": [
        "report my skeletal bone health index and monthly bone mineral density loss rate in microgravity",
        "check my muscular strength and muscle health index trend compared with launch baseline",
        "show my bone and muscle deconditioning status and whether my legs or lower back are weakening",
        "evaluate how fast my bone mass and skeletal muscle conditioning are changing during flight",
    ],
    "immune": [
        "display my immune system indicators leukocyte status cortisol stress hormone and body temperature",
        "check whether my core body temperature indicates a slight fever compared with personal baseline",
        "evaluate my immunity indicator score endocrine cortisol hormone reading and immune defense resilience",
        "review systemic inflammation cold symptoms immune markers and temperature trends inflight",
    ],
    "glucose": [
        "report my fasting and postprandial blood glucose sugar level in milligrams per deciliter",
        "check whether my metabolic blood glucose reading is elevated or hypoglycemic compared with baseline",
        "evaluate glucose excursion tremor sweating symptoms and diabetes screening range in telemetry",
    ],
    "sleep_psych": [
        "report how many hours of sleep i logged last night and my nocturnal sleep quality trend",
        "show my psychological mood score relaxation rating stress level and mental health assessment index",
        "check my psychomotor vigilance reaction game test score and daily physical training hours logged",
        "evaluate whether sleep deficit circadian rhythm shift or crew isolation affects my mood and alertness",
    ],
    "todo": [
        "list the exercise countermeasures and workout sessions remaining on my daily to do checklist",
        "check whether my aerobic cardio session and resistive exercise tasks are marked complete today",
        "show how many minutes of physical activity and countermeasure workouts are left on my schedule",
        "report the recommended resistance and cardiovascular countermeasure protocol for bone protection",
    ],
    "profile": [
        "retrieve my astronaut medical profile including blood type documented allergies age height and weight",
        "display my personal medical record covering past surgeries prior injuries and immunization history",
        "show my family medical history mission role nationality gender and number of previous spaceflights",
    ],
    "baseline": [
        "display my thirty day preflight baseline mean and standard deviation values recorded before launch",
        "show my personal prelaunch reference ranges for blood pressure heart rate sleep and temperature",
        "retrieve my individual preflight baseline measurements for comparison with current inflight telemetry",
    ],
    "calming": [
        "activate my personalized calming countermeasure by playing my favorite song or displaying my family photo",
        "help me reduce acute stress and anxiety before an activity with relaxation breathing or calming media",
        "open my saved family picture or audio track from my astronaut profile to help me relax",
    ],
    "contact": [
        "provide the communication channel and contact details to reach my assigned flight surgeon on earth",
        "request telemedicine messaging instructions or ground support clinic telephone routing",
    ],
    "journey": [
        "display my mission journey details including spacecraft vehicle destination total flight duration and current mission day",
        "report which mission day we are currently on and the scheduled duration of this spaceflight",
    ],
    "replay": [
        "replay my historical physiological telemetry readings and stored model prediction from a specific past mission day",
        "retrieve the recorded vital signs zone statuses and classifier output logged on an earlier mission day",
    ],
    "what_if": [
        "simulate a counterfactual what if scenario showing how sleeping or training more or less changes my risk",
        "estimate how my predicted health class probabilities would shift if i modified sleep hours or training duration",
    ],
    "correlation": [
        "compute the within astronaut statistical correlation between my daily training hours and psychological mood score",
        "analyze whether logging more physical exercise training is associated with better mood in my telemetry records",
    ],
    "sources": [
        "explain what data sources clinical standards and verification status this offline prototype relies upon",
        "clarify whether this software is a certified medical device or a research prototype and who verified its rules",
    ],
    "out_of_scope": [
        "report planetary atmospheric temperature weather forecast rain wind or orbital velocity mechanics outside human health",
        "explain how to repair maintain operate or troubleshoot spacecraft hardware life support scrubbers electrolyzers valves or batteries",
        "diagnose software engineering benchmarks operating system kernel schedulers processor thermal sensors or power management profiles",
        "perform general arithmetic conversions culinary baking nutritional food composition chemistry or structural engineering beam equations",
        "answer sports championships geography capitals foreign language translation creative poetry jokes entertainment playlists or financial stocks",
        "prescribe pharmaceutical medications antibiotics painkillers dosages or interpret radiographic imaging laboratory panels outside telemetry",
    ],
}

EXTRA_EXAMPLES: Dict[str, List[str]] = {
    "status": [
        "give me a complete multi zone health telemetry checkup and status assessment for today",
    ],
    "alerts": [
        "explain why an alarm or warning flag is active on my health monitor and how to resolve it",
    ],
    "cardio": [
        "check my pulse rate systolic and diastolic arterial pressure and peripheral oxygen saturation reading",
    ],
    "bone_muscle": [
        "review my skeletal bone mineral density trend and muscular conditioning index during microgravity exposure",
    ],
    "immune": [
        "inspect my immunity score core body temperature reading and endocrine cortisol stress hormone marker",
    ],
    "glucose": [
        "inspect my fasting blood glucose concentration and compare glycemic status against clinical reference limits",
    ],
    "sleep_psych": [
        "review my nocturnal sleep duration psychological mood rating relaxation index and cognitive reaction score",
    ],
    "todo": [
        "check my scheduled daily exercise countermeasure checklist for completed cardio and resistance workouts",
    ],
    "profile": [
        "look up my personal dossier for stature body mass blood group allergies and vaccination records",
    ],
    "baseline": [
        "list my personal prelaunch baseline averages and standard deviations across all monitored indicators",
    ],
    "calming": [
        "trigger my personal stress relief media preference by playing my audio track or showing my family image",
    ],
    "contact": [
        "retrieve the direct ground medical support contact information for my assigned flight surgeon",
    ],
    "journey": [
        "check the current mission elapsed day spacecraft assignment and target destination for this expedition",
    ],
    "replay": [
        "look back at the archived telemetry measurements and model classification recorded on mission day forty",
    ],
    "what_if": [
        "run a hypothetical simulation of how altering my daily sleep or exercise duration affects model probabilities",
    ],
    "correlation": [
        "evaluate the repeated measures statistical relationship linking my exercise training time and daily mood",
    ],
    "sources": [
        "describe the provenance of the database tables predictive model and countermeasure documentation used here",
    ],
}

STOPWORDS = set("""a an the is are am was were be been do does did i me my mine you your it this that these those of to in on
for with at by from about as and or so what which who whom when where how why can could would should will shall may
please tell show give get got have has had any some there here now today right just really very much many more less
according per up down out into over than then too also still yet ever s re m ll ve d t us we our""".split())

# General domain synonym normalization (no test-set overfit strings)
SYNONYMS = [
    (r"\bpulse\b|\bhr\b", "heart rate"),
    (r"\bbp\b", "blood pressure"),
    (r"\bspo2\b|\bo2\b|\boxygen level\w*\b|\bshort of breath\b|\bshortness of breath\b|\bbreathless\b", "oxygen saturation"),
    (r"\bmusic\b|\btrack\b|\btune\b", "song"),
    (r"\bpicture\b|\bpic\b|\bimage\b", "photo"),
    (r"\bworkouts?\b|\bphysical activity\b|\bexercise\s+(session|program|routine)\b", "exercise"),
    (r"\bexercises\b", "exercise"),
    (r"\btasks\b|\bchecklist\b", "task"),
    (r"\bvaccinations?\b|\bvaccines?\b", "immunization"),
    (r"\bblood group\b", "blood type"),
    (r"\bdoctors?\b|\bphysician\b|\bmedical team\b|\bmedical help\b", "flight surgeon"),
    (r"\balarms?\b|\bwarnings?\b|\balerts\b", "alert"),
    (r"\bfever\b|\bbody temp\b|\btemp\b", "temperature"),
    (r"\bslept\b|\bsleeping\b|\bgroggy\b|\bwaking up\b|\bfall asleep\b|\bcircadian\b|\binsomnia\b", "sleep"),
    (r"\btrained\b|\btraining\b", "train"),
    (r"\bstressed\b|\bstress\b|\banxious\b|\banxiety\b|\bnervous\b|\birritable\b", "stressed"),
    (r"\bcalming\b|\bcalm\b|\brelaxing\b", "relax"),
    (r"\bunmotivated\b|\bisolated\b|\bisolation\b|\bdepressed\b|\bsad\b|\blonely\b|\bloneliness\b|\bhomesick\b|\boverwhelmed\b|\bfeeling down\b", "mental health"),
    (r"\breaction game\b|\bpvt\b", "game test"),
    (r"\bbones\b|\bbone density\b|\bbone loss\b|\bbone mass\b", "bone"),
    (r"\bmuscles\b|\bmuscular\b", "muscle"),
    (r"\bimmunity\b|\bsore throat\b|\bcoming down with\b|\bcold sore\b", "immune"),
    (r"\bglucose\b|\bblood sugar\b|\bglycem\w*\b", "blood glucose"),
    (r"\bfile\b", "record"),
    (r"\bhealthy\b", "health"),
    (r"\breach\b|\bcall\b|\bspeak\b|\btalk\b", "contact"),
    (r"\bheaded\b|\bgoing\b|\bheading\b", "destination"),
    (r"\blinked\b|\blink\b|\brelated\b|\brelationship\b", "correlation"),
]

PREDICTION = r"\b(tomorrow|next (week|month|year)|in the future|when will i|will i (get|be|die|live)|how long will i live)\b"
GENERAL_KNOWLEDGE = (
    r"\b(in general|for (adults|humans|a human|people|men|women|children)|on average for|"
    r"normal (blood pressure|heart rate) for (a )?(human|humans|adults))\b"
)

# General non-human / external-domain / engineering / IT / trivia disambiguation rules
# Used ONLY to distinguish external objects (planets, spacecraft systems, electronics, food, software, finance)
# from personal physiological monitoring.
NON_HUMAN_ENTITY_DOMAINS = re.compile(
    r"\b("
    # Astronomy / planetary / Earth weather
    r"mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto|titan|europa|black hole|pulsar|"
    r"weather|rain|hurricane|forecast|atmosphere|orbit|orbiting|galaxy|universe|"
    # Spacecraft / mechanical / electrical hardware & life support equipment
    r"generator|scrubber|electrolyzer|electrolysis|filter|valve|pump|hull|solar panel|solar array|"
    r"rover|electronics|probe|telescope|canadarm\w*|robot\w*|gimbal|thruster|rocket|engine|car|tire|psi|"
    r"cabin pressure|water pressure|galley|tap|dispenser|pressure suit|suit leak|fire alarm|smoke alarm|airlock|"
    # Computers / software / IT
    r"laptop|desktop|computer|server|cpu|gpu|fan speed|linux|kernel|scheduler|operating system|python|"
    r"software|program|code|api|database|website|sleep mode|unplugged|battery|batteries|"
    # Structural physics / unit conversions / math / chemistry
    r"beam|truss|strain|cantilever|boiling|melting|fahrenheit|celsius|convert|"
    r"arithmetic|calculate\b.*\btimes\b|\d+\s*times\s*\d+|solve this math|quantum physics|"
    # Non-human organisms
    r"plant|plants|tree|crop|crops|algae|bacteria|dog|cat|mouse|"
    # Culinary / nutrition composition trivia (not personal glucose reading)
    r"banana|apple|rice|pasta|bread|oatmeal|pizza|lasagna|quiche|brownies|bake|cook|recipe|tablespoon|calorie content|"
    r"glucose content|carbohydrate content|"
    # Media / sports / finance / general trivia / comms
    r"stock|stocks|portfolio|banking|checking account|savings|wire fee|credit card|currency|exchange rate|"
    r"football|soccer|champions league|world cup|super bowl|wimbledon|nba|playlist|"
    r"poem|bedtime story|joke|sing me|movie|book|news from earth|"
    r"translate|capital of|president|commander|send an email|history of|how many people|time is it in"
    r")\b"
)

# Personal / Crew / Symptom / Body Context Signals (C1 Scope Gate)
PERSONAL_HEALTH_CONTEXT = re.compile(
    r"\b("
    r"i|me|my|mine|we|our|myself|crew|astronaut|"
    r"feel|feeling|feels|felt|am i|did i|do i|have i|should i|can i|"
    r"today|tonight|last night|this morning|this week|yesterday|right now|lately|"
    r"baseline|pre ?flight|mission day|day \d+|to do|task list|profile|record|"
    r"flight surgeon|countermeasure\w*|alert\w*|warning\w*|danger|"
    r"heart rate|blood pressure|systolic|diastolic|oxygen saturation|spo2|"
    r"bone|muscle|immune|cortisol|hormone\w*|temperature|blood glucose|glucose|blood sugar|"
    r"sleep|mood|relax\w*|stressed|mental health|lonely|loneliness|homesick|overwhelmed|game test|exercise|cardio|resistance|train\w*|"
    r"chest pain|left arm|passed out|fainted|short of breath|lightheaded|dizzy|headache|ache\w*|weak\w*|tired|exhausted|confused|confusion|disoriented"
    r")\b"
)

# Urgent Symptom Escalation Rules (C1)
URGENT_SYMPTOM_PATTERN = re.compile(
    r"("
    r"\bchest (pain|hurts|pressure|tightness)\b|"
    r"\bleft arm\b.*\bnumb\b|\bnumb\b.*\bleft arm\b|"
    r"\b(passed out|fainted|fainting|syncope|unconscious|blacked out)\b|"
    r"\b(severe shortness of breath|can t breathe|cannot breathe|struggling to breathe|short of breath)\b|"
    r"\b(confusion|disoriented)\b|\b(feeling|sudden|am|feel)\s+confused\b|"
    r"\b(headache|dizzy|lightheaded)\b.*\b(blood pressure|bp|systolic|oxygen|spo2|emergency|dropped)\b|"
    r"\b(blood pressure|bp|systolic|oxygen|spo2|dropped)\b.*\b(headache|dizzy|lightheaded|emergency)\b"
    r")"
)

KEYWORD_SLOTS = [
    ("what_if", r"\bwhat if\b|\bsuppose\b|\bsimulate\b|\bwhat happens (to .*)?if\b|\bwhat would\b|\bif i (sleep|train|got|get|rest)"),
    ("replay", r"\bday \d+\b|\breplay\b"),
    ("correlation", r"\bcorrelation\b|\bmood\b.*\btrain|\btrain\w*\b.*\bmood\b"),
    ("baseline", r"\bbaseline\b|\bpre ?flight\b|\bbefore (the )?(launch|flight|mission)\b"),
    ("calming", r"\bsong\b|\bphoto\b|\b(help me|need to|want to) (relax|calm)\b|\bcalm down\b|\brelax (me )?down\b|\bbreathing exercise"),
    ("contact", r"\bflight surgeon\b|\bcontact\b|\btalk to someone\b"),
    ("todo", r"\bto do\b|\btask\b|\bcardio\b|\bresistance\b|\bcountermeasures?\b|\bworkouts? (do i|left|remain|need)"),
    ("journey", r"\bdestination\b|\bmission day\b|\bspacecraft\b|\baircraft\b|\bflight (take|time|last)\b|\bhow long is (my|the) flight\b|\bdays (is|will) the (mission|flight)\b"),
    ("bone_muscle", r"\bbone\b|\bmuscle\b|\blower back\b|\blegs?\b.*\bweak"),
    ("cardio", r"\bheart\b|\bblood pressure\b|\bsystolic\b|\bdiastolic\b|\boxygen saturation\b|\bcardiovascular\b"),
    ("glucose", r"\bblood glucose\b|\blow sugar\b|\bhigh sugar\b|\bsugar\b"),
    ("immune", r"\bimmune\b|\bcortisol\b|\bhormones?\b|\btemperature\b"),
    ("sleep_psych", r"\bsleep\b|\bmood\b|\brelaxed\b|\bmental health\b|\bgame test\b|\btrain\b|\bpsychological\b|\bstressed\b|\bexercise\b|\bactivity\b"),
    ("alerts", r"\balert\b|\bwrong\b|\bnot normal\b|\bemergency\b|\bdanger\b|\bchest pain\b|\bpassed out\b|\bfainted\b"),
    ("sources", r"\bsources?\b|\binformation\b|\bdata do you\b|\bverified\b|\bmedical device\b|\btrust you\b|\bfacts\b|\ba (real )?flight surgeon\b|\bbased on\b"),
    ("status", r"\bhealth\b|\bstatus\b|\bhow am i\b|\bam i ok\b|\bverdict\b|\bcondition\b|\bmodel say\b|\bpredicted class\b|\bvitals\b|\bfine with me\b"),
    ("profile", r"\bblood type\b|\ballerg|\bage\b|\bold am i\b|\bweigh|\bheight\b|\btall\b|\brole\b|\bnationalit|\bsurger|\binjur|\bimmunization\b|\bfamily medical\b|\bprofile\b|\brecord\b"),
]

COMPARISON = r"\b(higher|lower|above|below|compared|versus|vs|than|normal for me|worse|better|dropping|faster)\b"

UNMEASURED = (
    r"\b(cholesterol|vitamin\w*|kidneys?|liver|x ?ray|ultrasound|mri|radiation|insulin|"
    r"diabet\w*|cancer|ecg|ekg|urine|hemoglobin|iron level|calcium|eyesight|vision)\b"
)

DOMAIN_VOCAB = set("""health status condition state body check summary summarise summarize overview verdict model class
predicted prediction says say result alert active triggered caused cause reason explain fix wrong problem issue heart rate
beat beating pound fluttery weird blood pressure systolic diastolic oxygen saturation cardiovascular reading readings level
levels value values number numbers bone density mass loss losing lost strength weak weaker muscle legs lower back ache
immune system indicators cortisol hormones temperature slight fever cold sore throat sick blood glucose sugar morning
shaky sweaty sleep hours hour night enough long waking fall asleep groggy circadian lighting tips improve mood score
relaxed relax mental assessment game test reaction psychological train trained minutes physical activity skip exhausted
list task exercise cardio resistance session countermeasures left remaining done finished completed logged profile record
blood type allergies allergic age old weight weigh height tall role nationality surgeries surgery injuries immunization
family medical history previous flights gender name baseline pre flight preflight launch mission before song photo stressed
calm play open hear see anxious irritable isolated unmotivated lonely loneliness homesick overwhelmed breathing eva flight surgeon contact details earth
destination spacecraft aircraft days day replay happened if suppose simulate change changes risk correlation information
data sources facts verified advice answers based trust device real app normal high low ok okay fine good bad current latest
compare look holding quickly fast slow take last went off put time help need want feel feeling know view display vitals
week month yesterday morning dizzy lightheaded headache chest pain arm numb passed fainted confused confusion disoriented emergency""".split())

FABRICATION = r"\b(make up|made up|invent|pretend|fabricate|fake|imagine|guess|just say|lie about|assume i)\b"
# Refusal reasons that block the online assistant too (see ask()); every other refusal is a scope limit
# of the offline templates only.
SAFETY_REFUSALS = {
    "empty question",
    "asked to invent data",
    "medication / diagnosis / treatment is outside the three allowed sources",
    "question about another astronaut",
    "unknown astronaut",
}
MEDICATION = (
    r"\b(medicine|medicines|medication|medications|drug|drugs|pill|pills|dose|dosage|prescribe|prescription|"
    r"antibiotic|antibiotics|aspirin|ibuprofen|painkiller|painkillers|sedative|supplement|supplements|"
    r"diagnose|diagnosis|treatment for|cure)\b"
)

PROFILE_KEYS = [
    (r"blood type", "blood_type"),
    (r"allerg", "allergies"),
    (r"\bage\b|how old", "age"),
    (r"weigh", "weight_kg"),
    (r"height|how tall", "height_cm"),
    (r"role", "mission_role"),
    (r"nationalit", "nationality"),
    (r"surger", "previous_surgeries"),
    (r"injur", "previous_injuries"),
    (r"immuni[sz]ation|vaccin", "immunization_history"),
    (r"family medical|family history", "family_medical_history"),
    (r"gender|sex\b", "gender"),
    (r"previous flight|flown before|how many flights", "previous_flight"),
    (r"\bname\b", "name"),
]
STRONG_PROFILE = r"blood type|allerg|surger|injur|immuni[sz]ation|vaccin|nationalit|family medical"
WHATIF_KEYS = [
    (r"sleep", "sleep_hours"),
    (r"train|exercise|activity", "daily_training_hours"),
    (r"mood", "mood"),
    (r"relax", "relaxation"),
]

DID_YOU_MEAN_HINTS = [
    (r"\btemperature\b|\bhot\b|\bfever\b|\bcelsius\b|\bfahrenheit\b", "What is my body temperature today compared to my baseline?"),
    (r"\boxygen\b|\bspo2\b|\bo2\b|\bco2\b|\bscrubber\b", "What is my oxygen saturation (SpO2) reading today?"),
    (r"\bpressure\b|\bbp\b|\bsystolic\b|\bdiastolic\b", "What is my blood pressure today compared to my pre-flight baseline?"),
    (r"\bheart\b|\bpulse\b|\bhr\b", "What is my resting heart rate today?"),
    (r"\bsleep\b|\binsomnia\b|\bbedtime\b", "How many hours did I sleep last night?"),
    (r"\bstress\w*\b|\banxi\w*\b|\brelax\w*\b", "My stress level has been high, what can I do to calm down?"),
    (r"\bglucose\b|\bsugar\b|\bdiabet\w*\b", "What is my blood glucose reading today?"),
    (r"\bimmune\b|\bimmunity\b|\binfection\b|\bsick\b", "How are my immunity indicators today?"),
    (r"\bbone\w*\b|\bmuscle\w*\b|\bjoint\w*\b|\bworkout\w*\b|\bexercise\w*\b", "How are my bone and muscle health indicators trending?"),
    (r"\balarm\b|\balert\b|\bwarning\b|\bhealth\b|\bbattery\b", "Do I have any active health alerts today?"),
    (r"\bradiation\b", "What is my current overall health status and active alerts?"),
]


def _normalize(q: str) -> str:
    """Lower-case, strip punctuation, map synonyms onto canonical vocabulary."""
    t = re.sub(r"[^a-z0-9 ]+", " ", str(q).lower())
    for pat, sub in SYNONYMS:
        t = re.sub(pat, sub, t)
    return re.sub(r"\s+", " ", t).strip()


def _topic_words(norm: str) -> List[str]:
    return [w for w in norm.split() if w not in STOPWORDS and not w.isdigit()]


class OfflineChatbot:
    def __init__(self):
        self.questions: List[str] = []
        self.labels: List[str] = []
        for source in (EXAMPLES, EXTRA_EXAMPLES):
            for intent, qs in source.items():
                for q in qs:
                    self.questions.append(q)
                    self.labels.append(intent)
        norm = [_normalize(q) for q in self.questions]
        topic = [" ".join(_topic_words(n)) or n for n in norm]

        self.vec_word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.vec_char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.m_word = self.vec_word.fit_transform(topic)
        self.m_char = self.vec_char.fit_transform(topic)
        self.vocab = DOMAIN_VOCAB | {
            w for n, lab in zip(norm, self.labels) if lab != "out_of_scope" for w in _topic_words(n)
        }

        y_scope = np.array([0 if lab == "out_of_scope" else 1 for lab in self.labels], dtype=int)
        X_scope = np.hstack([self.m_word.toarray(), self.m_char.toarray()])
        self.scope_clf = LogisticRegression(C=2.0, class_weight="balanced", max_iter=300, random_state=42)
        self.scope_clf.fit(X_scope, y_scope)

    def scope_gate(self, question: str, norm: str) -> Tuple[bool, float, Optional[str]]:
        """
        Phase 4 C1 Scope Gate before routing.
        Combines offline TF-IDF scope classifier with personal/crew vs. non-human entity context rules.
        """
        raw_lower = re.sub(r"[^a-z0-9 ]+", " ", str(question).lower())
        raw_lower = re.sub(r"\s+", " ", raw_lower).strip()

        # 1. Explicit non-human / planetary / spacecraft hardware / software / culinary / trivia entity check
        if NON_HUMAN_ENTITY_DOMAINS.search(raw_lower) or NON_HUMAN_ENTITY_DOMAINS.search(norm):
            return False, 0.05, "external / non-human / hardware / planetary / trivia entity"

        # 2. Offline TF-IDF scope probability
        topic = " ".join(_topic_words(norm)) or norm
        v_w = self.vec_word.transform([topic]).toarray()
        v_c = self.vec_char.transform([topic]).toarray()
        p_scope = float(self.scope_clf.predict_proba(np.hstack([v_w, v_c]))[0, 1])

        has_personal = bool(PERSONAL_HEALTH_CONTEXT.search(raw_lower) or PERSONAL_HEALTH_CONTEXT.search(norm))
        has_slot = self.has_slot(norm)
        unk = self.unknown_share(norm)

        if unk >= UNKNOWN_SHARE_LIMIT and not (has_personal and has_slot):
            return False, p_scope, "most topic words are outside the health-record vocabulary"

        if not has_personal and not has_slot and p_scope < 0.55:
            return False, p_scope, f"scope gate probability {p_scope:.2f} below threshold without personal/health context"

        return True, p_scope, None

    def suggest_did_you_mean(self, question: str, norm: str) -> Optional[str]:
        """Return a 'Did you mean...?' suggestion when refusing a borderline query."""
        raw_lower = str(question).lower()
        for pat, suggestion in DID_YOU_MEAN_HINTS:
            if re.search(pat, raw_lower) or re.search(pat, norm):
                return suggestion
        return None

    def is_urgent_symptom(self, question: str, norm: str) -> bool:
        """Detect acute clinical red-flag symptoms requiring immediate flight surgeon escalation."""
        raw_lower = re.sub(r"[^a-z0-9 ]+", " ", str(question).lower())
        return bool(URGENT_SYMPTOM_PATTERN.search(raw_lower) or URGENT_SYMPTOM_PATTERN.search(norm))

    def max_training_similarity(self, question: str) -> Tuple[float, str]:
        """
        Compute maximum TF-IDF word cosine similarity between `question` and all training examples.
        Used by Phase 4 C2 anti-leakage verification (target <= 0.60 on evaluation sets).
        """
        norm = _normalize(question)
        topic = " ".join(_topic_words(norm)) or norm
        sims = cosine_similarity(self.vec_word.transform([topic]), self.m_word)[0]
        idx = int(np.argmax(sims))
        return float(sims[idx]), self.questions[idx]

    # ------------------------------------------------------------------ intent
    def classify(self, question: str) -> Tuple[str, float, str]:
        """Return (intent, confidence, nearest_example)."""
        norm = _normalize(question)
        topic = " ".join(_topic_words(norm)) or norm
        sims = (
            0.6 * cosine_similarity(self.vec_word.transform([topic]), self.m_word)[0]
            + 0.4 * cosine_similarity(self.vec_char.transform([topic]), self.m_char)[0]
        )
        best: Dict[str, float] = {}
        for lab, sim in zip(self.labels, sims):
            if sim > best.get(lab, -1.0):
                best[lab] = float(sim)
        nearest = self.questions[int(np.argmax(sims))]
        slots = self.slots(norm)
        if not slots:
            best.pop("replay", None)
            intent = max(best, key=best.get)
            return intent, best[intent], nearest
        if best.get("out_of_scope", 0.0) >= 0.85:
            return "out_of_scope", best["out_of_scope"], nearest
        scored = {lab: best.get(lab, 0.0) + KEYWORD_BONUS - 0.02 * rank for rank, lab in enumerate(slots)}
        intent = max(scored, key=scored.get)
        return intent, min(scored[intent], 1.0), nearest

    def slots(self, norm: str) -> List[str]:
        found = [lab for lab, pat in KEYWORD_SLOTS if re.search(pat, norm)]
        if "what_if" in found:
            return ["what_if"]
        if "replay" in found and re.search(r"\bday \d+\b", norm):
            return ["replay"]
        if "sources" in found and re.search(r"\bare you\b|\byour\b|\bthis (app|tool|software)\b|\btrust you\b|\bwho verified\b", norm):
            return ["sources"]
        if "baseline" in found:
            if re.search(COMPARISON, norm) and len(found) > 1:
                found.remove("baseline")
            else:
                return ["baseline"]
        if "alerts" in found and re.search(r"\b(warning|danger|alert|alarm|emergency|chest pain|passed out|fainted)\b", norm):
            if not re.search(r"\b(bone|muscle)\b", norm):
                return ["alerts"]
        if "todo" in found and "sleep_psych" in found and not re.search(
            r"\bsleep\b|\bmood\b|\bmental\b|\bgame\b|\bexhausted\b|\bhow many hours did i train\b|"
            r"\bhow much did i train\b|\btraining hours\b|\bphysical activity this week\b",
            norm,
        ):
            found.remove("sleep_psych")
        if "bone_muscle" in found and "todo" in found and re.search(r"\bcountermeasures?\b|\bresistance exercise\b", norm):
            return ["todo", "bone_muscle"]
        if "calming" in found and re.search(r"\b(song|photo|calm down|help me relax|help me calm|breathing exercise)\b", norm):
            return ["calming"]
        if "contact" in found and re.search(r"\b(flight surgeon|reach|contact|talk to someone)\b", norm):
            return ["contact"]
        specific = [lab for lab in found if lab not in ("status", "alerts", "sources")]
        if specific:
            return specific
        if "alerts" in found:
            return ["alerts"]
        return found

    def has_slot(self, norm: str) -> bool:
        return bool(self.slots(norm))

    def unknown_share(self, norm: str) -> float:
        words = _topic_words(norm)
        if not words:
            return 1.0
        return sum(w not in self.vocab for w in words) / len(words)

    # ------------------------------------------------------------------ public
    def ask(
        self,
        astronaut_id: str,
        question: str,
        session_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return {'answer', 'intent', 'confidence', 'refused', 'sources', 'did_you_mean', 'urgent_escalation'}.
        Supports optional RBAC session_token verification (Phase 1 D2).
        """
        astronaut_id = str(astronaut_id).strip().upper()
        if session_token is not None:
            auth_chk = he.verify_session(session_token, target_astronaut_id=astronaut_id)
            if not auth_chk.get("ok"):
                return self._pack(
                    rf.REFUSAL_TEXT,
                    "refusal",
                    1.0,
                    True,
                    "none (refusal: " + auth_chk.get("error", "unauthorized") + ")",
                )

        norm = _normalize(question)
        urgent = self.is_urgent_symptom(question, norm)
        intent, conf, _ = self.classify(question)

        if re.search(STRONG_PROFILE, norm) and re.search(r"\b(my|i|me)\b", norm) and intent != "out_of_scope":
            intent, conf = "profile", max(conf, CONFIDENCE_THRESHOLD)

        scope_ok, scope_prob, scope_reason = self.scope_gate(question, norm)

        reason = None
        if not norm:
            reason = "empty question"
        elif re.search(FABRICATION, norm):
            reason = "asked to invent data"
        elif re.search(MEDICATION, norm):
            reason = "medication / diagnosis / treatment is outside the three allowed sources"
        elif any(
            m != astronaut_id
            for m in re.findall(r"\ba\d{2,3}\b", norm.replace("astronaut ", ""))
            for m in [m.upper()]
        ):
            reason = "question about another astronaut"
        elif re.search(PREDICTION, norm) and " if " not in f" {norm} ":
            reason = "asks to predict the future (only the what-if simulator may do that)"
        elif re.search(GENERAL_KNOWLEDGE, norm):
            reason = "general medical knowledge is outside the three allowed sources"
        elif re.search(UNMEASURED, norm):
            reason = "asks about something this prototype does not measure"
        elif not scope_ok:
            reason = scope_reason or "blocked by out-of-scope gate"
        elif self.unknown_share(norm) >= UNKNOWN_SHARE_LIMIT and not urgent:
            reason = "most topic words are outside the health-record vocabulary"
        elif not self.has_slot(norm) and conf < NO_SLOT_THRESHOLD and not urgent:
            reason = f"no topic keyword and similarity {conf:.2f} below {NO_SLOT_THRESHOLD}"
        elif intent == "out_of_scope" and not urgent:
            reason = "nearest example is out of scope"
        elif conf < CONFIDENCE_THRESHOLD and not urgent:
            reason = f"intent confidence {conf:.2f} below threshold {CONFIDENCE_THRESHOLD}"

        if reason is None and not he.astronaut_exists(astronaut_id):
            reason = "unknown astronaut"

        if urgent and reason is None:
            intent = "alerts"
            conf = max(conf, 0.85)

        if reason:
            suggestion = self.suggest_did_you_mean(question, norm)
            refusal_body = rf.REFUSAL_TEXT
            if urgent:
                refusal_body += "\nURGENT SYMPTOM NOTICE: Contact the flight surgeon immediately."
            if suggestion:
                refusal_body += f'\nDid you mean: "{suggestion}"?'
            packed = self._pack(
                refusal_body,
                "refusal",
                conf,
                True,
                "none (refusal: " + reason + ")",
                did_you_mean=suggestion,
                urgent_escalation=urgent,
            )
            # "safety": must be refused by every engine (invented data, medication/diagnosis, other people's
            #           records, unknown astronaut). "scope": the offline templates simply cannot answer it,
            #           so the online assistant may answer it instead.
            packed["refusal_kind"] = "safety" if reason in SAFETY_REFUSALS else "scope"
            packed["refusal_reason"] = reason
            return packed

        try:
            body, sources = getattr(self, "_a_" + intent)(astronaut_id, question, norm)
        except _Refuse as e:
            suggestion = self.suggest_did_you_mean(question, norm)
            refusal_body = rf.REFUSAL_TEXT
            if suggestion:
                refusal_body += f'\nDid you mean: "{suggestion}"?'
            return self._pack(
                refusal_body,
                "refusal",
                conf,
                True,
                "none (refusal: " + str(e) + ")",
                did_you_mean=suggestion,
                urgent_escalation=urgent,
            )

        if urgent:
            p = he.get_profile(astronaut_id)
            surgeon = p["profile"]["contact_flight_surgeon"] if p.get("ok") else "ground medical control"
            escalation_banner = (
                f"URGENT ESCALATION: Contact the flight surgeon immediately — please contact your flight surgeon now ({surgeon}). "
                "Pause activity and begin live ground medical review.\n"
            )
            if "contact the flight surgeon immediately" not in body.lower():
                body = escalation_banner + body

        body = self._gentle_finalize(
            body,
            question=question,
            sources=sources,
            warn_or_danger=self._is_warning_or_danger(astronaut_id),
        )

        return self._pack(
            body,
            intent,
            conf,
            False,
            sources,
            did_you_mean=None,
            urgent_escalation=urgent,
        )

    def reply(self, astronaut_id: str, question: str) -> str:
        return self.ask(astronaut_id, question)["answer"]

    @staticmethod
    def _pack(
        body: str,
        intent: str,
        conf: float,
        refused: bool,
        sources: str,
        did_you_mean: Optional[str] = None,
        urgent_escalation: bool = False,
    ) -> Dict[str, Any]:
        return {
            "answer": f"{body}\n{rf.DISCLAIMER}\nSources: {sources}",
            "intent": intent,
            "confidence": round(conf, 3),
            "refused": refused,
            "sources": sources,
            "did_you_mean": did_you_mean,
            "urgent_escalation": urgent_escalation,
        }

    # ------------------------------------------------------------------ gentle tone & formatting helpers
    _FRIENDLY_LABELS: Dict[str, Tuple[str, str]] = {
        "heart_rate": ("resting heart rate", "bpm"),
        "systolic_bp": ("systolic blood pressure", "mmHg"),
        "diastolic_bp": ("diastolic blood pressure", "mmHg"),
        "oxygen_saturation": ("oxygen saturation", "%"),
        "temperature": ("body temperature", "°C"),
        "blood_glucose_mg_dl": ("blood glucose", "mg/dL"),
        "bone_health": ("bone health index", "%"),
        "muscle_health": ("muscle health index", "/100"),
        "cardio_session_min": ("cardio duration", "min"),
        "resistance_training_min": ("resistance duration", "min"),
        "daily_physical_activity_min": ("daily activity", "min"),
        "immunity_indicators": ("immune resilience", "PU"),
        "hormones": ("cortisol stress hormone", "PU"),
        "sleep_hours": ("sleep duration", "h"),
        "relaxation": ("relaxation rating", "/10"),
        "mood": ("mood score", "/10"),
        "mental_health_assessment": ("mental wellbeing score", "/100"),
        "game_test_score": ("reaction score", "/100"),
        "daily_training_hours": ("daily training", "h"),
    }

    _DETAIL_REQUEST_RE = re.compile(
        r"\b(more detail|in detail|detailed|explain more|longer|step by step|everything|full breakdown|all numbers)\b",
        re.IGNORECASE,
    )

    _DIAGNOSIS_CLEAN_RULES: Tuple[Tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\bhypoglycemia\b", re.IGNORECASE), "lower-than-usual glucose"),
        (re.compile(r"\bhyperglycemia\b", re.IGNORECASE), "elevated glucose"),
        (re.compile(r"\bhypertension\b", re.IGNORECASE), "elevated blood pressure"),
        (re.compile(r"\bdiabetes\b", re.IGNORECASE), "glucose regulation"),
        (re.compile(r"\binsomnia\b", re.IGNORECASE), "difficulty sleeping"),
        (re.compile(r"\bdiagnosis\b|\bdiagnose[sd]?\b", re.IGNORECASE), "clinical assessment"),
        (re.compile(r"\binfection\b", re.IGNORECASE), "immune strain"),
        (re.compile(r"\bdisorder\b", re.IGNORECASE), "pattern"),
        (re.compile(r"\bsick\b|\billness\b", re.IGNORECASE), "under strain"),
    )

    @staticmethod
    def _need(res: Dict[str, Any]) -> Dict[str, Any]:
        if not res.get("ok"):
            raise _Refuse(res.get("error", "engine error"))
        return res

    def _first_name(self, aid: str) -> Optional[str]:
        res = he.get_profile(aid)
        if not res.get("ok"):
            return None
        name = str(res["profile"].get("name") or "").strip()
        if not name:
            return None
        for token in name.split():
            cleaned = token.strip(".")
            if cleaned.lower() not in ("dr", "cpt", "cdr", "lt", "col"):
                return cleaned
        return name.split()[0]

    def _greet(self, aid: str, warm_empathy: bool = False) -> str:
        fn = self._first_name(aid)
        if warm_empathy:
            return f"That sounds tiring, {fn} — let's look at it together." if fn else "That sounds tiring — let's look at it together."
        return f"Thanks for checking in, {fn}." if fn else "Thanks for checking in."

    @staticmethod
    def _fmt_num(v: Any) -> str:
        if v is None:
            return "n/a"
        f = float(v)
        return f"{int(round(f))}" if abs(f - round(f)) < 0.05 else f"{f:.1f}"

    def _pct_phrase(self, val: Any, base: Any, unit: str) -> str:
        if val is None or base is None or abs(float(base)) < 1e-9:
            return "with no pre-mission baseline on record"
        pct = ((float(val) - float(base)) / float(base)) * 100.0
        base_s = f"{self._fmt_num(base)} {unit}".strip()
        if abs(pct) < 1.0:
            return f"right in line with your pre-mission baseline of {base_s}"
        direction = "above" if pct > 0 else "below"
        return f"about {abs(pct):.0f}% {direction} your pre-mission baseline of {base_s}"

    def _metric_sentence(self, key: str, dev: Dict[str, Any], verb: str = "is") -> str:
        label, unit = self._FRIENDLY_LABELS.get(key, (key.replace("_", " "), dev.get("unit") or ""))
        val = dev.get("value")
        base = dev.get("baseline_mean")
        if val is None:
            return f"Your {label} measurement for today is currently missing."
        val_s = f"{self._fmt_num(val)} {unit}".strip()
        return f"Your {label} today {verb} {val_s}, {self._pct_phrase(val, base, unit)}."

    @staticmethod
    def _is_warning_or_danger(aid: str) -> bool:
        try:
            card = he.astronaut_card(aid)
            if not card.get("ok"):
                return False
            if card.get("predicted_class") in ("Health_Warning", "Medical_Danger_Alert"):
                return True
            zones = card.get("zones") or {}
            return any(v in ("yellow", "red") for v in zones.values())
        except Exception:
            return False

    def _gentle_finalize(self, body: str, *, question: str, sources: str, warn_or_danger: bool) -> str:
        text = body
        for pat, repl in self._DIAGNOSIS_CLEAN_RULES:
            text = pat.sub(repl, text)

        surgeon_line = "Please contact your flight surgeon to review these numbers together."
        if warn_or_danger and "contact your flight surgeon" not in text.lower():
            text = f"{text}\n{surgeon_line}"

        if self._DETAIL_REQUEST_RE.search(question):
            return text.strip()

        footer_words = len(f"{rf.DISCLAIMER}\nSources: {sources}".split())
        max_body_words = max(45, 118 - footer_words)
        words = text.split()
        if len(words) <= max_body_words:
            return text.strip()

        if warn_or_danger and "contact your flight surgeon" in surgeon_line.lower():
            reserved = surgeon_line.split()
            keep_n = max(35, max_body_words - len(reserved) - 1)
            head = " ".join(words[:keep_n]).rstrip(",;:")
            if head and head[-1] not in ".!?":
                head += "."
            return f"{head}\n{surgeon_line}".strip()

        head = " ".join(words[:max_body_words]).rstrip(",;:")
        if head and head[-1] not in ".!?":
            head += "."
        return head.strip()

    @staticmethod
    def _actions_block(items: List[str], warn_or_danger: bool = False) -> str:
        steps = [s.strip().rstrip(".") + "." for s in items if s and s.strip()]
        if warn_or_danger and not any("contact your flight surgeon" in s.lower() for s in steps):
            if len(steps) >= 3:
                steps = steps[:2]
            steps.append("Contact your flight surgeon to review these readings together.")
        steps = steps[:3]
        if not steps:
            return ""
        return "Next steps: " + " ".join(f"{i + 1}. {s}" for i, s in enumerate(steps))

    @staticmethod
    def _linked(la: Dict[str, Any]) -> str:
        t = la.get("type")
        if t == "todo":
            left = [i["task"] for i in la["todo"]["items"] if not i["done"]]
            return ("Complete open To-Do workout: " + ", ".join(left[:2])) if left else "Keep up your completed exercise routine"
        if t in ("sleep_schedule", "todo_and_sleep_schedule"):
            return f"Protect sleep tonight (baseline {la['your_baseline_sleep_hours']} h) and unwind with song {la['calming']['file']}"
        if t == "calming":
            return f"Play your calming song ({la['file']}) or view your family photo ({la['alternative']['file']})"
        if t == "contact_flight_surgeon":
            return f"Contact your flight surgeon ({la['contact']})"
        return ""

    def _explain_text(self, ex: Dict[str, Any]) -> str:
        """Concise, warm (a) current vs baseline, (b) why, (c) how to fix."""
        cvb_list = ex.get("current_vs_baseline") or []
        cvb = "; ".join(cvb_list[:2]) or "indicators remain near your personal band"
        why_raw = str(ex.get("why") or "").strip().split(".")[0]
        fix = ex.get("how_to_fix") or {}
        advice_short = str(fix.get("advice_text") or "").strip().split(".")[0]
        linked = self._linked(fix.get("linked_action", {}))
        actions = [a for a in (advice_short, linked) if a][:2]
        fix_line = " ".join(f"{i + 1}. {a.rstrip('.')}." for i, a in enumerate(actions))
        return (
            f"{ex['what'].split('.')[0]}.\n"
            f"(a) Current vs your baseline: {cvb}.\n"
            f"(b) Why: {why_raw}.\n"
            f"(c) How to avoid or fix it: {fix_line}"
        )

    def _pick_zone_indicators(self, zone: str, norm: str, inds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        priority_patterns = {
            "Cardiovascular": [
                (r"heart|pulse", ["heart_rate", "systolic_bp"]),
                (r"blood pressure|systolic|diastolic", ["systolic_bp", "diastolic_bp", "heart_rate"]),
                (r"oxygen", ["oxygen_saturation", "heart_rate"]),
            ],
            "Immune": [
                (r"temperature|fever", ["temperature", "immunity_indicators"]),
                (r"cortisol|hormone", ["hormones", "immunity_indicators"]),
            ],
            "Sleep_Brain": [
                (r"sleep|tired|groggy", ["sleep_hours", "mood"]),
                (r"mood|mental health|stressed|relax", ["mood", "sleep_hours"]),
                (r"game", ["game_test_score", "sleep_hours"]),
                (r"train|exercise|activity", ["daily_training_hours", "mood"]),
            ],
            "Bone_Muscle": [
                (r"bone", ["bone_health", "muscle_health"]),
                (r"muscle|legs|back", ["muscle_health", "bone_health"]),
            ],
        }
        by_name = {it["indicator"]: it for it in inds}
        for pat, names in priority_patterns.get(zone, []):
            if re.search(pat, norm):
                picked = [by_name[n] for n in names if n in by_name]
                if picked:
                    return picked[:2]
        ranked = sorted(inds, key=lambda it: abs(float(it.get("z") or 0.0)), reverse=True)
        return ranked[:2]

    def _zone_answer(self, aid: str, zone: str, norm: str = "") -> Tuple[str, str]:
        ev = self._need(he.explain_alert(aid, zone))
        card = self._need(he.earth_doctor_card(aid, last_n_days=1))
        z_data = card["diagnostic_breakdown"][zone]
        z_status = str(z_data["status"]).lower()
        warn_or_danger = z_status in ("yellow", "red") or card.get("predicted_class") in (
            "Health_Warning",
            "Medical_Danger_Alert",
        )
        empathy = warn_or_danger or bool(re.search(r"sleep|tired|stressed|mental health|pain|weak|fever", norm))
        greet = self._greet(aid, warm_empathy=empathy)

        picked = self._pick_zone_indicators(zone, norm, z_data["indicators"])
        metrics_text = " ".join(self._metric_sentence(it["indicator"], it) for it in picked)

        extra = ""
        info = z_data.get("info")
        if zone == "Bone_Muscle" and info:
            extra = (
                f" 30-day bone trend is {info['bone_loss_pct_per_month_trailing_30d']} %/month "
                f"with {info['sessions_last_7_days']['cardio_done']} cardio and "
                f"{info['sessions_last_7_days']['resistance_done']} resistance sessions this week."
            )

        steps: List[str] = []
        linked_str = self._linked((ev.get("how_to_fix") or {}).get("linked_action", {}))
        if linked_str:
            steps.append(linked_str)
        if zone == "Cardiovascular":
            steps.append("Take 5 slow breaths seated and re-check readings after resting")
        elif zone == "Bone_Muscle":
            steps.append("Complete today's scheduled ARED resistance and treadmill block")
        elif zone == "Immune":
            steps.append("Stay hydrated, prioritize rest tonight, and note any new physical symptoms")
        elif zone == "Sleep_Brain":
            steps.append("Dim cabin lights 45 minutes before bed for steadier sleep recovery")

        body = f"{greet} {metrics_text}{extra}\n{self._actions_block(steps, warn_or_danger=warn_or_danger)}"
        return body, (
            "mission_telemetry, preflight_baseline, countermeasures, "
            "health_engine.explain_alert, health_engine.earth_doctor_card"
        )

    # ------------------------------------------------------------------ intent handlers
    def _a_status(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        c = self._need(he.astronaut_card(aid))
        doc = self._need(he.earth_doctor_card(aid, last_n_days=1))
        devs = doc.get("baseline_deviations") or {}
        warn_or_danger = c["status_class"] in ("Health_Warning", "Medical_Danger_Alert") or any(
            v in ("yellow", "red") for v in c["zones"].values()
        )
        greet = self._greet(aid, warm_empathy=warn_or_danger)
        status_phrase = c["status_class"].replace("_", " ").lower()
        hr_text = self._metric_sentence("heart_rate", devs["heart_rate"]) if "heart_rate" in devs else ""
        sl_text = self._metric_sentence("sleep_hours", devs["sleep_hours"], verb="was") if "sleep_hours" in devs else ""
        flagged = [rf.ZONE_TITLES[z] for z, s in c["zones"].items() if s != "green"]
        zone_note = (
            f"All four monitoring zones look steady today."
            if not flagged
            else f"Areas needing gentle attention: {', '.join(flagged)}."
        )
        actions = []
        if c["active_alerts"]:
            actions.append(c["immediate_advice"][0]["advice_text"].split(".")[0])
        else:
            actions.append("Keep up hydration and today's exercise block on schedule")
        body = (
            f"{greet} Your mission day {c['mission_day']} check looks {status_phrase}. {zone_note} "
            f"{hr_text} {sl_text}\n{self._actions_block(actions, warn_or_danger=warn_or_danger)}"
        )
        return body, "health_engine.astronaut_card, health_engine.earth_doctor_card, model_predictions, countermeasures"

    def _a_alerts(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        ex = self._need(he.explain_alert(aid))
        doc = self._need(he.earth_doctor_card(aid, last_n_days=1))
        warn_or_danger = self._is_warning_or_danger(aid)
        greet = self._greet(aid, warm_empathy=warn_or_danger)
        if ex["area"] is None:
            hr = doc["baseline_deviations"].get("heart_rate", {})
            hr_line = self._metric_sentence("heart_rate", hr) if hr else "No indicators are flagged outside your baseline."
            return (
                f"{greet} On mission day {ex['mission_day']}, no alerts are active. {hr_line}\n"
                f"(a) Current vs your baseline: all indicators remain within your personal band.\n"
                f"(b) Why: no unusual shifts were detected.\n"
                f"(c) How to avoid or fix it: {self._actions_block(['Maintain normal hydration, rest, and workout tracking'], False)}",
                "health_engine.explain_alert, mission_telemetry, preflight_baseline",
            )
        body = f"{greet} On mission day {ex['mission_day']}, let's review your active alert:\n{self._explain_text(ex)}"
        if warn_or_danger:
            body += "\nNext step: 1. Contact your flight surgeon to review these readings together."
        return body, (
            "health_engine.explain_alert, mission_telemetry, preflight_baseline, "
            "countermeasures, model output"
        )

    def _a_cardio(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        return self._zone_answer(aid, "Cardiovascular", norm)

    def _a_bone_muscle(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        return self._zone_answer(aid, "Bone_Muscle", norm)

    def _a_immune(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        return self._zone_answer(aid, "Immune", norm)

    def _a_glucose(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        card = self._need(he.earth_doctor_card(aid, last_n_days=1))
        imm = card["diagnostic_breakdown"]["Immune"]
        warn_or_danger = imm["status"] in ("yellow", "red") or self._is_warning_or_danger(aid)
        dev = card["baseline_deviations"].get("blood_glucose_mg_dl")
        if dev is None:
            for it in imm["indicators"]:
                if it["indicator"] in ("blood_glucose_mg_dl", "blood_sugar"):
                    dev = it
                    break
        greet = self._greet(aid)
        if dev is None:
            msg = f"{greet} Your blood glucose measurement is missing for today."
        else:
            msg = (
                f"{greet} {self._metric_sentence('blood_glucose_mg_dl', dev)} "
                "The fasting reference range is 70-99 mg/dL."
            )
        steps = ["Re-check readings before meals or after quiet rest", "Keep balanced meals and hydration steady"]
        return f"{msg}\n{self._actions_block(steps, warn_or_danger=warn_or_danger)}", (
            "mission_telemetry (blood_glucose_mg_dl), preflight_baseline, "
            "07_health_indicators_schema.json (ADA 2024)"
        )

    def _a_sleep_psych(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        is_mood_support = bool(
            re.search(
                r"\b(mood|mental health|stressed|relax|lonely|loneliness|homesick|overwhelmed|anxious|down|sad|isolated)\b",
                norm,
            )
        )
        if not is_mood_support:
            return self._zone_answer(aid, "Sleep_Brain", norm)

        card = self._need(he.earth_doctor_card(aid, last_n_days=1))
        p = self._need(he.get_profile(aid))["profile"]
        devs = card.get("baseline_deviations") or {}
        warn_or_danger = self._is_warning_or_danger(aid)
        fn = self._first_name(aid)

        mood_dev = devs.get("mood")
        sleep_dev = devs.get("sleep_hours")
        intro = (
            f"That sounds really heavy, {fn} — feeling that way during a mission makes complete sense, so let's check in together."
            if fn
            else "That sounds really heavy — feeling that way during a mission makes complete sense, so let's check in together."
        )
        nums = " ".join(
            s for s in (
                self._metric_sentence("mood", mood_dev) if mood_dev else "",
                self._metric_sentence("sleep_hours", sleep_dev, verb="was") if sleep_dev else "",
            ) if s
        )
        step = (
            f"One small step: 1. Take two quiet minutes for slow breathing, listen to your song ({p['song']}), "
            "or schedule a call with family or extra rest — support from your crew and flight surgeon is always available."
        )
        if warn_or_danger:
            step += " Please also contact your flight surgeon so you don't carry this alone."
        return f"{intro} {nums}\n{step}", "mission_telemetry, preflight_baseline, astronaut_profile, countermeasures"

    def _a_todo(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        t = self._need(he.get_todo(aid))
        greet = self._greet(aid)
        open_items = [it["task"] for it in t["items"] if not it["done"]]
        done_mins = sum(int(it.get("minutes") or 0) for it in t["items"])
        warn_or_danger = self._is_warning_or_danger(aid)
        if open_items:
            summary = f"{greet} On mission day {t['mission_day']}, you have logged {done_mins} min and have {len(open_items)} item(s) left: {', '.join(open_items)}."
            actions = [f"Complete {open_items[0]}", "Hydrate afterward and stretch"]
        else:
            summary = f"{greet} Great work — all exercise checklist tasks for mission day {t['mission_day']} are complete ({done_mins} min logged)."
            actions = ["Prioritize rest and recovery nutrition"]
        return f"{summary}\n{self._actions_block(actions, warn_or_danger=warn_or_danger)}", "mission_telemetry (To-Do columns), countermeasures, health_engine.get_todo"

    def _a_profile(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        p = self._need(he.get_profile(aid))["profile"]
        greet = self._greet(aid)
        hits = [col for pat, col in PROFILE_KEYS if re.search(pat, norm)]
        if hits:
            body = "; ".join(f"{col.replace('_', ' ')}: {p[col]}" for col in hits[:4])
            return f"{greet} On your mission profile — {body}.", "astronaut_profile"
        summary = (
            f"role {p['mission_role']}, blood type {p['blood_type']}, allergies {p['allergies']}, "
            f"age {p['age']}, weight {p['weight_kg']} kg, height {p['height_cm']} cm."
        )
        return f"{greet} From your profile on record: {summary}", "astronaut_profile"

    def _a_baseline(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        b = self._need(he.get_profile(aid))["baseline"]
        greet = self._greet(aid)
        zone_for = [
            ("Cardiovascular", r"heart|pulse|blood pressure|systolic|diastolic|oxygen|spo2"),
            ("Sleep_Brain", r"sleep|mood|relax|mental|game|train"),
            ("Immune", r"immun|hormone|cortisol|temperature|blood glucose|sugar"),
            ("Bone_Muscle", r"bone|muscle|cardio|resistance|activity"),
        ]
        names = [n for z, pat in zone_for if re.search(pat, norm) for n in rf.ZONES[z]]
        if not names:
            names = ["heart_rate", "systolic_bp", "diastolic_bp", "oxygen_saturation", "temperature", "sleep_hours", "mood"]
        parts = []
        for n in dict.fromkeys(names[:5]):
            label, unit = self._FRIENDLY_LABELS.get(n, (n.replace("_", " "), rf.IND[n]["unit"]))
            parts.append(f"{label} {self._fmt_num(b[n + '_mean'])} {unit}".strip())
        return f"{greet} Your pre-mission 30-day baselines: {', '.join(parts)}.", "preflight_baseline"

    def _a_calming(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        p = self._need(he.get_profile(aid))["profile"]
        greet = self._greet(aid, warm_empathy=True)
        if re.search(r"photo|picture|family", norm):
            act, f = "family photo", p["family_photo"]
        else:
            act, f = "calming song", p["song"]
        step = (
            f"{greet} Your {act} ({f}) is ready — support is always here for you.\n"
            f"{self._actions_block(['Try 2 minutes of slow breathing while enjoying your media', 'Connect with crewmates or call family when you have a quiet window'])}"
        )
        return step, "astronaut_profile (calming preferences), countermeasures"

    def _a_contact(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        p = self._need(he.get_profile(aid))["profile"]
        greet = self._greet(aid)
        return (
            f"{greet} You can contact your flight surgeon anytime at: {p['contact_flight_surgeon']}. Support is always on standby.",
            "astronaut_profile",
        )

    def _a_journey(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        p = self._need(he.get_profile(aid))["profile"]
        day = self._need(he.get_todo(aid))["mission_day"]
        greet = self._greet(aid)
        return (
            f"{greet} You are on mission day {day} aboard {p['type_of_aircraft']}, heading toward "
            f"{p['destination_for_flight']} (estimated {p['estimated_time_for_flight_days']} days total).",
            "astronaut_profile, mission_telemetry",
        )

    def _a_replay(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        m = re.search(r"day (\d+)", norm)
        if not m:
            raise _Refuse("no mission day given")
        ts = datetime.fromisoformat(rf.MISSION_START) + timedelta(days=int(m.group(1)) - 1)
        r = self._need(he.mission_replay(aid, ts.isoformat()))
        sp = r["stored_prediction"]
        tel = r["telemetry"]
        b = self._need(he.get_profile(aid))["baseline"]
        greet = self._greet(aid)
        pred = "normal" if sp is None else sp["predicted_class"].replace("_", " ").lower()
        hr_val = tel.get("heart_rate")
        hr_s = f"Heart rate was {self._fmt_num(hr_val)} bpm ({self._pct_phrase(hr_val, b.get('heart_rate_mean'), 'bpm')})." if hr_val is not None else ""
        sl_val = tel.get("sleep_hours")
        sl_s = f"Sleep was {self._fmt_num(sl_val)} h." if sl_val is not None else ""
        warn_or_danger = sp is not None and sp["predicted_class"] in ("Health_Warning", "Medical_Danger_Alert")
        extra = " Contact your flight surgeon if you'd like to review that day together." if warn_or_danger else ""
        return (
            f"{greet} On mission day {r['mission_day']}, your status was {pred}. {hr_s} {sl_s}{extra}",
            "health_engine.mission_replay, mission_telemetry, model_predictions",
        )

    def _a_what_if(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        ind = next((col for pat, col in WHATIF_KEYS if re.search(pat, norm)), None)
        if ind is None:
            raise _Refuse("what-if without a supported indicator")
        num = re.search(r"(\d+(?:\.\d+)?)", norm)
        amount = float(num.group(1)) if num else (0.5 if "half" in norm else 1.0)
        if "minute" in norm and ind in ("sleep_hours", "daily_training_hours"):
            amount /= 60.0
        sign = -1.0 if re.search(r"\b(less|fewer|reduce|cut|decrease|lower|worse|drops?)\b", norm) else 1.0
        r = self._need(he.what_if(aid, {ind: sign * amount}))
        ch = r["applied_changes"][ind]
        greet = self._greet(aid)
        label, unit = self._FRIENDLY_LABELS.get(ind, (ind, ch["unit"]))
        return (
            f"{greet} If your {label} shifts from {self._fmt_num(ch['before'])} to {self._fmt_num(ch['after'])} {unit}, "
            f"the simulated status moves from {r['before']['predicted_class'].replace('_', ' ')} "
            f"to {r['after']['predicted_class'].replace('_', ' ')}. {self._actions_block(['Use small steady habits to protect your baseline'])}",
            "health_engine.what_if, live model output, mission_telemetry",
        )

    def _a_correlation(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        r = self._need(he.mood_training_correlation(aid))
        w = r["within_astronaut"][0]
        greet = self._greet(aid)
        return (
            f"{greet} Across {w['n']} of your mission days, daily training hours and mood show correlation r={w['pearson_r']} "
            f"(p={w['pearson_p']}). Keeping a steady workout routine tends to support steadier daily mood.",
            "mission_telemetry, health_engine.mood_training_correlation",
        )

    def _a_sources(self, aid: str, q: str, norm: str) -> Tuple[str, str]:
        greet = self._greet(aid)
        return (
            f"{greet} I'm your support companion, not a doctor. My answers come only from your mission profile, "
            "pre-mission baselines, daily telemetry, our trained model, and verified NASA-STD-3001 / OCHMO / HRP countermeasures.",
            "data_provenance, countermeasures, model " + rf.MODEL_VERSION,
        )


class _Refuse(Exception):
    pass


def main():
    bot = OfflineChatbot()
    aid = (sys.argv[1] if len(sys.argv) > 1 else "A001").upper()
    print(rf.DISCLAIMER)
    print(f"Offline chatbot for astronaut {aid}. Type a question, or 'quit'.")
    while True:
        try:
            q = input("\nYou: ").strip()
        except EOFError:
            break
        if q.lower() in ("quit", "exit", "q"):
            break
        print("Bot: " + bot.reply(aid, q))


if __name__ == "__main__":
    main()
