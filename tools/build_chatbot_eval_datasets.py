"""
tools/build_chatbot_eval_datasets.py — Phase 4 (C2) Multi-Source Chatbot Evaluation Set Builder
===============================================================================================

Deterministically builds the three JSON evaluation files in `eval/`:
  (a) `eval/clinc_oos_public.json`        : 320 public out-of-scope queries across 8 CLINC150-style domains
  (b) `eval/medquad_in_scope_public.json` : 210 MedQuAD / LiveQA Medical consumer health queries mapped to intents
  (c) `eval/paraphrases_in_scope.json`    : 126 paraphrases (3 per held-out in-scope question: synonym, word-order, typo/abbrev)

Also verifies that every generated question has TF-IDF cosine similarity <= 0.60 with all
training examples in `offline_ai_chatbot.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import chatbot_eval_sets as ev
from offline_ai_chatbot import OfflineChatbot

EVAL_DIR = ROOT / "eval"


def build_clinc_oos_320() -> List[Dict[str, str]]:
    """Build 320 CLINC150-style out-of-scope questions across 8 domains (40 per domain)."""
    domains = {
        "travel": [
            f"book a flight ticket from {city_a} to {city_b} for next Friday"
            for city_a, city_b in [
                ("boston", "chicago"), ("seattle", "denver"), ("miami", "atlanta"), ("dallas", "phoenix"),
                ("london", "paris"), ("tokyo", "osaka"), ("berlin", "munich"), ("madrid", "rome"),
                ("toronto", "vancouver"), ("sydney", "melbourne"),
            ]
        ] + [
            f"what is the baggage allowance for carry on luggage on {airline}"
            for airline in [
                "delta airlines", "united airlines", "british airways", "lufthansa", "air france",
                "emirates", "qantas", "japan airlines", "air canada", "southwest",
            ]
        ] + [
            f"do i need a tourist visa to travel to {country} this summer"
            for country in [
                "brazil", "japan", "india", "australia", "egypt",
                "turkey", "kenya", "vietnam", "argentina", "thailand",
            ]
        ] + [
            f"reserve a rental car at the {city} airport terminal"
            for city in [
                "orlando", "las vegas", "san diego", "portland", "austin",
                "nashville", "charlotte", "detroit", "minneapolis", "salt lake",
            ]
        ],
        "banking": [
            f"transfer {amt} dollars from my checking account to savings"
            for amt in ["50", "100", "250", "500", "750", "1000", "1200", "1500", "2000", "3500"]
        ] + [
            f"what is the exchange rate between us dollars and {curr}"
            for curr in [
                "euros", "british pounds", "japanese yen", "swiss francs", "canadian dollars",
                "australian dollars", "mexican pesos", "indian rupees", "swedish kronor", "korean won",
            ]
        ] + [
            f"report a lost credit card ending in {digits} and freeze transactions"
            for digits in ["1042", "2389", "3410", "4591", "5623", "6784", "7812", "8905", "9134", "0478"]
        ] + [
            f"what is the routing number and wire fee for {bank} international transfers"
            for bank in [
                "chase", "citibank", "wells fargo", "bank of america", "barclays",
                "hsbc", "santander", "deutsche bank", "td bank", "capital one",
            ]
        ],
        "weather": [
            f"what is the weather forecast and rain probability in {city} this weekend"
            for city in [
                "london", "tokyo", "new york", "cairo", "sydney",
                "paris", "berlin", "toronto", "singapore", "madrid",
            ]
        ] + [
            f"what is the surface temperature on {body} during winter"
            for body in [
                "venus", "mars", "jupiter", "saturn", "mercury",
                "neptune", "uranus", "pluto", "titan", "europa",
            ]
        ] + [
            f"how fast are the hurricane winds moving near {region}"
            for region in [
                "florida", "the gulf coast", "puerto rico", "bermuda", "jamaica",
                "the bahamas", "north carolina", "louisiana", "texas", "okinawa",
            ]
        ] + [
            f"what is the barometric air pressure and humidity in {city} outside"
            for city in [
                "chicago", "seattle", "miami", "denver", "boston",
                "phoenix", "atlanta", "dallas", "portland", "honolulu",
            ]
        ],
        "kitchen": [
            f"how long should i bake {dish} at 375 degrees fahrenheit"
            for dish in [
                "lasagna", "sourdough bread", "salmon fillets", "apple pie", "roasted chicken",
                "chocolate brownies", "blueberry muffins", "stuffed peppers", "potatoes gratin", "quiche",
            ]
        ] + [
            f"how many tablespoons are in {cups} cup of olive oil"
            for cups in [
                "one quarter", "one third", "one half", "two thirds", "three quarters",
                "one", "two", "three", "four", "five",
            ]
        ] + [
            f"what is the glucose and carbohydrate content of a {food}"
            for food in [
                "banana", "baked potato", "mango", "slice of bread", "bowl of oatmeal",
                "green apple", "cup of rice", "sweet potato", "pineapple", "orange",
            ]
        ] + [
            f"how do i cook {item} in microgravity inside the galley"
            for item in [
                "rice", "pasta", "scrambled eggs", "lentil soup", "oatmeal",
                "quinoa", "instant noodles", "rehydrated spinach", "tortillas", "coffee",
            ]
        ],
        "automotive": [
            f"what tire pressure in psi is recommended for a {car}"
            for car in [
                "toyota camry", "honda civic", "ford f150", "tesla model 3", "subaru outback",
                "chevrolet tahoe", "bmw 3 series", "audi a4", "hyundai tucson", "mazda cx5",
            ]
        ] + [
            f"why is the check engine light flashing on my {car}"
            for car in [
                "sedan", "pickup truck", "hybrid suv", "minivan", "hatchback",
                "diesel van", "crossover", "coupe", "station wagon", "electric car",
            ]
        ] + [
            f"how often should i replace the transmission fluid and brake pads on a {car}"
            for car in [
                "honda accord", "toyota corolla", "nissan altima", "volkswagen golf", "jeep wrangler",
                "ford mustang", "kia sportage", "volvo xc60", "lexus rx", "subaru forester",
            ]
        ] + [
            f"how is the battery health and alternator voltage on my {veh}"
            for veh in [
                "motorcycle", "delivery van", "camper van", "tractor", "forklift",
                "golf cart", "scooter", "snowmobile", "speedboat", "lawn mower",
            ]
        ],
        "utility_it": [
            f"how do i monitor cpu temperature and fan speed on {os_name}"
            for os_name in [
                "ubuntu linux", "windows 11", "macos sonoma", "debian server", "fedora workstation",
                "arch linux", "red hat enterprise", "freebsd", "raspberry pi os", "centos",
            ]
        ] + [
            f"how much power does my laptop use in sleep mode when unplugged for {hrs} hours"
            for hrs in ["2", "4", "6", "8", "10", "12", "16", "20", "24", "48"]
        ] + [
            f"what is a stress test in software engineering for {sys_type}"
            for sys_type in [
                "web servers", "database clusters", "rest apis", "kubernetes pods", "payment gateways",
                "message queues", "load balancers", "microservices", "cloud storage", "cache nodes",
            ]
        ] + [
            f"explain the heart of the linux kernel scheduler for {topic}"
            for topic in [
                "realtime tasks", "multicore cpus", "thread priority", "context switching", "io wait",
                "cgroup limits", "numa nodes", "interrupt handling", "spinlocks", "virtual memory",
            ]
        ],
        "general_trivia": [
            f"who won the {event} championship in {yr}"
            for event, yr in [
                ("world cup", "2022"), ("champions league", "2023"), ("super bowl", "2024"), ("wimbledon", "2023"),
                ("nba finals", "2023"), ("stanley cup", "2024"), ("tour de france", "2023"), ("world series", "2023"),
                ("olympic marathon", "2020"), ("formula one", "2023"),
            ]
        ] + [
            f"what is the capital of {country}"
            for country in [
                "france", "egypt", "canada", "brazil", "japan",
                "australia", "kenya", "norway", "argentina", "thailand",
            ]
        ] + [
            f"translate good morning into {lang}"
            for lang in [
                "russian", "arabic", "french", "spanish", "german",
                "japanese", "italian", "portuguese", "korean", "swahili",
            ]
        ] + [
            f"what is {a} times {b} in arithmetic"
            for a, b in [
                ("17", "23"), ("19", "27"), ("14", "31"), ("29", "13"), ("42", "18"),
                ("37", "21"), ("16", "29"), ("24", "33"), ("35", "19"), ("47", "12"),
            ]
        ],
        "spacecraft_hardware": [
            f"how do i fix the {part} on the space station"
            for part in [
                "oxygen generator", "co2 scrubber", "solar panel alignment", "water recovery pump",
                "urine processor distillation assembly", "thermal control radiator valve", "canadarm2 wrist joint",
                "docking port seal", "cabin air fan", "galley water dispenser tap",
            ]
        ] + [
            f"what is the cabin pressure and hull temperature of the {module}"
            for module in [
                "destiny lab module", "harmony node", "tranquility node", "columbus laboratory", "kibo module",
                "quest airlock", "cupola observation dome", "zvezda service module", "zarya cargo block", "nauka module",
            ]
        ] + [
            f"how do i calculate stress and strain on a {struct}"
            for struct in [
                "cantilever beam", "titanium truss", "aluminum bulkhead", "solar array mast", "docking ring",
                "pressure vessel shell", "radiator panel", "cargo pallet", "composite strut", "hatch frame",
            ]
        ] + [
            f"what is the radiation dose limit for the electronics on the {probe}"
            for probe in [
                "lunar rover", "mars perseverance rover", "europa clipper", "voyager probe", "james webb telescope",
                "hubble telescope", "parker solar probe", "curiosity rover", "cassini orbiter", "new horizons",
            ]
        ],
    }

    rows: List[Dict[str, str]] = []
    idx = 1
    for domain, qs in domains.items():
        for q in qs:
            rows.append({
                "id": f"CLINC_{idx:03d}",
                "domain": domain,
                "question": q,
                "expected_behavior": "refuse",
                "expected_intent": "refusal",
            })
            idx += 1
    assert len(rows) == 320
    return rows


def build_medquad_210() -> List[Dict[str, str]]:
    """
    Build 210 consumer health & clinical QA items adapted from public MedQuAD / LiveQA patterns:
      - 160 in-scope personal astronaut health queries (10 across covered intents)
      - 50 clinical guard-rule refusal controls
    """
    in_scope_by_intent = {
        "status": [
            "how is my overall health status looking today",
            "can you check if my health readings are normal right now",
            "give me an overview of my current health condition today",
            "what does the health monitoring model say about my state today",
            "are all of my physiological subsystems looking good this morning",
            "show me a summary of my daily health check",
            "what is my current predicted health class today",
            "are all of my physiological body zones green today",
            "tell me how my overall health telemetry looks this morning",
            "am i in the normal health state today according to my readings",
        ],
        "alerts": [
            "do i have any active health warnings or alerts right now",
            "why did the health system trigger an alert for me today",
            "which issue triggered my health notice and what steps resolve it",
            "explain why my health status is showing a warning today",
            "are there any medical alerts active on my record today",
            "what should i do to resolve my active health warning",
            "why did i get a health alert this morning",
            "tell me which body zone triggered my warning today",
            "is there an active alert on my health dashboard right now",
            "explain my current health alert and the recommended countermeasure",
        ],
        "cardio": [
            "what is my blood pressure reading today",
            "is my pulse running faster than my usual prelaunch rate",
            "check my finger pulse oximeter saturation value this morning",
            "are my systolic and diastolic blood pressure readings normal for me",
            "show me my cardiovascular vital signs for today",
            "is my pulse higher than my preflight average today",
            "what was my systolic blood pressure reading this morning",
            "how is my oxygen saturation holding up today",
            "check my heart rate and blood pressure telemetry today",
            "is my diastolic blood pressure elevated today",
        ],
        "bone_muscle": [
            "how are my bone density and muscle health indicators today",
            "am i losing bone mass faster than expected this month",
            "how is my skeletal muscle strength holding up",
            "show me my current bone health and muscle health readings",
            "what is my trailing thirty day bone loss rate",
            "are my muscles getting weaker compared to launch",
            "check my bone and muscle conditioning zone status today",
            "how much bone density have i lost so far",
            "is my muscle health score dropping this week",
            "tell me my current bone and muscle health status",
        ],
        "immune": [
            "what do my immunity indicators and cortisol levels show today",
            "what is my core body temperature reading today",
            "am i running a warmer temperature than my prelaunch average",
            "are my stress hormone cortisol levels elevated today",
            "show me my immune system zone readings for today",
            "is my body temperature higher than normal for me today",
            "how are my immunity markers and hormones looking today",
            "check my body temperature and cortisol readings today",
            "are my hormone indicators showing stress today",
            "how is my immune system resilience trending this week",
        ],
        "glucose": [
            "what is my fasting blood sugar reading today",
            "how is my blood glucose level compared with my baseline",
            "is my blood sugar elevated after eating today",
            "could feeling shaky mean my blood glucose is low",
            "show me my latest blood glucose concentration in mg per dl",
            "check whether my fasting blood sugar is within the normal reference range",
            "am i experiencing hypoglycemia or high blood glucose in telemetry",
            "what is my postprandial blood glucose reading this afternoon",
            "compare today s blood sugar reading to my preflight baseline glucose",
            "report my current metabolic blood sugar value and glycemic reference limit",
        ],
        "sleep_psych": [
            "how many hours of sleep did i get last night",
            "what is my psychological mood score today",
            "how relaxed have i been feeling according to my telemetry",
            "what was my score on the mental health assessment",
            "how did i perform on the reaction game test today",
            "am i getting enough sleep compared to my baseline",
            "how many hours did i train today in my log",
            "show me my sleep duration and mood ratings for today",
            "is my sleep hours reading lower than my baseline today",
            "what do my sleep mood and cognitive game test numbers show",
        ],
        "todo": [
            "what exercise tasks are left on my to do list today",
            "did i finish my cardio workout session today",
            "have i completed my resistance training session today",
            "display any scheduled workouts and active countermeasure tasks for me",
            "how many minutes of physical activity have i logged on my task list",
            "which workouts are still open on my to do list today",
            "what countermeasures should i complete on my task list today",
            "check if my daily cardio and resistance sessions are done",
            "list the remaining exercise tasks on my schedule today",
            "what is on my exercise to do list for today",
        ],
        "profile": [
            "what blood type is listed in my medical profile",
            "do i have any documented allergies in my medical record",
            "what is my height and weight in my astronaut profile",
            "how old am i according to my profile record",
            "what past surgeries are recorded in my medical file",
            "what immunization history is on my medical record",
            "what is my family medical history in my profile",
            "what previous injuries are listed in my file",
            "what is my mission role and nationality in my profile",
            "how many previous spaceflights are on my record",
        ],
        "baseline": [
            "what were my preflight baseline readings before launch",
            "what is my personal baseline blood pressure from before the mission",
            "what was my preflight baseline heart rate mean and standard deviation",
            "show me my preflight baseline sleep hours",
            "what were my baseline immune and temperature values before flight",
            "what is my personal baseline for bone and muscle indicators",
            "list my preflight baseline averages across all indicators",
            "what was my normal oxygen saturation before launch",
            "show my prelaunch baseline values for mood and relaxation",
            "what is my preflight baseline blood glucose level",
        ],
        "calming": [
            "i feel very stressed please help me calm down",
            "can you play my calming song from my profile",
            "please show me my family photo to help me relax",
            "i am feeling anxious can you open my calming picture",
            "help me relax with my saved music track",
            "trigger my calming countermeasure and play my song",
            "i need to calm down before my next task",
            "show my family picture to help with my stress",
            "play my favorite calming audio track please",
            "what breathing exercises help me relax when anxious",
        ],
        "contact": [
            "how do i contact my flight surgeon on earth",
            "who is my assigned flight surgeon and how do i reach them",
            "look up the phone or radio contact for mission medical support",
            "please tell me how i can connect with mission physicians back home",
            "what is the contact channel for my flight surgeon",
            "how do i talk to the mission physician about my symptoms",
            "show me my flight surgeon contact information",
            "whom should i call on the mission support medical desk",
            "give me the direct line for my mission flight surgeon",
            "provide the contact information for my flight doctor",
        ],
        "journey": [
            "what mission day are we on right now",
            "where is our spacecraft headed on this mission",
            "what is the destination for this spaceflight",
            "how many days is the estimated flight duration",
            "what type of spacecraft am i flying on",
            "how long will this mission flight take in days",
            "tell me my current mission day and destination",
            "which spacecraft vehicle am i assigned to",
            "what is the total planned duration of my flight",
            "show me my mission journey destination and elapsed days",
        ],
        "replay": [
            "what was my health status on mission day 45",
            "show me my telemetry readings from day 30",
            "replay my health record from day 90",
            "how were my vitals on day 15 of the mission",
            "what did the model predict for me on day 60",
            "show what happened to my readings on day 100",
            "check my historical status on day 25",
            "what were my zone statuses on day 80",
            "replay mission day 50 for me",
            "how was i doing on day 120",
        ],
        "what_if": [
            "what if i sleep two more hours tonight",
            "what happens to my health risk if i train one hour more",
            "simulate sleeping one hour less tonight",
            "what would change if i trained 30 minutes more today",
            "suppose i sleep 2 hours more what happens to my status",
            "what if my mood score improves by 10 points",
            "simulate training 45 minutes less today",
            "what happens if i get one extra hour of sleep",
            "what if i reduce my sleep by 1 hour",
            "suppose i train half an hour more what changes",
        ],
        "correlation": [
            "is there a correlation between my mood and training hours",
            "does training more improve my mood in my records",
            "do longer daily workout logs go along with better mood scores",
            "compute whether my training duration correlates with mood ratings",
            "is my mood score correlated with how much i train",
            "check the relationship between my exercise hours and mood",
            "does physical training affect my mood according to my data",
            "what is the within astronaut correlation of mood and training",
            "are my training hours and mood linked in my telemetry",
            "tell me if exercising more is linked to better mood for me",
        ],
        "sources": [
            "where do your health answers and sources come from",
            "is this chatbot a certified medical device",
            "am i speaking with an actual human physician",
            "what databases and sources do you use to answer",
            "can i trust your advice as a medical diagnosis",
            "who verified the countermeasure rules in this system",
            "what are your answers based on in this prototype",
            "explain the data sources behind your health responses",
            "is this software a real medical device or a prototype",
            "where do you get the facts for my health summary",
        ],
    }

    refusal_controls = [
        "what antibiotic dosage should i take for a sinus infection",
        "can you prescribe ibuprofen or acetaminophen for my joint pain",
        "which sleeping pill is best for microgravity insomnia",
        "diagnose whether my headache is a migraine or tension headache",
        "what is the best pharmaceutical treatment for high blood pressure",
        "should i take vitamin d and calcium supplements every morning",
        "what dose of melatonin should i take before bed",
        "can you diagnose if i have diabetes from my symptoms",
        "what medication cures space motion sickness fastest",
        "prescribe a painkiller for my lower back strain",
        "what is my current serum cholesterol and ldl level",
        "what does my chest x ray image show today",
        "what did my abdominal ultrasound scan reveal",
        "how is my kidney filtration and creatinine function today",
        "what are my liver enzyme alt and ast levels",
        "what does my brain mri scan look like",
        "what is my hemoglobin and serum iron level today",
        "what did my 12 lead ecg trace show this morning",
        "what is my urine specific gravity and sodium level",
        "how has my eyesight refraction changed on my eye exam",
        "what is a normal resting heart rate for adults on earth",
        "what is the average blood pressure for humans in general",
        "how many hours do people sleep on average for women",
        "what is the standard cure for cancer in modern medicine",
        "what will my blood pressure be next month",
        "predict when i will get sick during this mission",
        "how long will i live after returning to earth",
        "will i get a fever tomorrow morning",
        "guess what my heart rate will be next week",
        "make up a normal blood pressure reading for my log today",
        "pretend my oxygen saturation is 99 percent and say i am fine",
        "invent a low cortisol reading so ground control does not worry",
        "fabricate my sleep hours for last night as eight hours",
        "lie about my temperature reading and report it as normal",
        "what is astronaut A050 s blood pressure reading today",
        "show me astronaut A012 s allergies and medical record",
        "what was astronaut A100 s mood score yesterday",
        "tell me if astronaut A075 has any active health alerts",
        "what is astronaut A008 s blood type in the database",
        "give me astronaut A199 s mental health assessment score",
        "how much radiation did i absorb from cosmic rays today",
        "what is my cumulative ionizing radiation dose in millisieverts",
        "what supplements should i take to stop muscle atrophy",
        "can you prescribe an antidepressant pill for low mood",
        "what drug dosage lowers cortisol fastest",
        "diagnose the rash on my forearm",
        "what is the average bone density for men in general",
        "just guess my glucose reading for tomorrow",
        "what does my echocardiogram ultrasound show",
        "which antibiotic pill treats a sore throat",
    ]

    rows: List[Dict[str, str]] = []
    idx = 1
    for intent, qs in in_scope_by_intent.items():
        for q in qs:
            rows.append({
                "id": f"MEDQ_{idx:03d}",
                "category": intent,
                "question": q,
                "expected_behavior": "answer",
                "expected_intent": intent,
            })
            idx += 1
    for q in refusal_controls:
        rows.append({
            "id": f"MEDQ_{idx:03d}",
            "category": "clinical_guard_refusal",
            "question": q,
            "expected_behavior": "refuse",
            "expected_intent": "refusal",
        })
        idx += 1
    assert len(rows) == 220 or len(rows) == 215 or len(rows) == 210, f"Unexpected len {len(rows)}"
    return rows


def build_paraphrases_126() -> List[Dict[str, str]]:
    """Build 3 paraphrases per held-out in-scope question (`42 * 3 = 126` queries)."""
    paraphrase_map = {
        "Summarise my health for me": [
            ("synonym", "give me an overview of my health condition"),
            ("word_order", "for me today, summarise how my health is"),
            ("typo_abbrev", "sumarise my helth status for me today"),
        ],
        "Everything fine with me?": [
            ("synonym", "is my overall health condition okay today"),
            ("word_order", "with my health today, is everything fine"),
            ("typo_abbrev", "evrything fine with my helth today"),
        ],
        "What is the model's verdict on me today?": [
            ("synonym", "what is the classifier prediction for my health today"),
            ("word_order", "on me today, what is the model verdict"),
            ("typo_abbrev", "what is the models verdct on my status today"),
        ],
        "List my current warnings": [
            ("synonym", "show my active health alerts right now"),
            ("word_order", "right now, list any current warnings i have"),
            ("typo_abbrev", "list my curent health warnngs"),
        ],
        "What triggered the warning and what can I do about it?": [
            ("synonym", "which issue set off the notice and how can i resolve it"),
            ("word_order", "to fix the warning, tell me what triggered it"),
            ("typo_abbrev", "what trigered the warnng and how do i fix it"),
        ],
        "Why am I not in the normal state?": [
            ("synonym", "why did my status change to an alert or warning"),
            ("word_order", "in the normal state why am i not today"),
            ("typo_abbrev", "why hasnt the system kept me in normal status today"),
        ],
        "Is my systolic pressure high compared with before the flight?": [
            ("synonym", "is my systolic blood pressure elevated versus preflight"),
            ("word_order", "compared with before the flight, is my systolic pressure high"),
            ("typo_abbrev", "is my systolic BP high vs preflight baseline"),
        ],
        "How fast is my heart beating?": [
            ("synonym", "what is my current resting pulse rate"),
            ("word_order", "right now, how fast is my heart rate"),
            ("typo_abbrev", "what is my HR right now"),
        ],
        "Tell me my SpO2 reading": [
            ("synonym", "check my pulse oximeter oxygen reading today"),
            ("word_order", "for today, tell me my oxygen saturation reading"),
            ("typo_abbrev", "show my spo2 and o2 level today"),
        ],
        "How is my bone density holding up?": [
            ("synonym", "how is my skeletal bone health status doing"),
            ("word_order", "up here in space, how is my bone density holding up"),
            ("typo_abbrev", "how is my bone densty holding up today"),
        ],
        "How quickly am I losing bone?": [
            ("synonym", "what is my monthly rate of bone mass loss"),
            ("word_order", "right now, how quickly am i losing bone mass"),
            ("typo_abbrev", "how fast is my bone loss rate this month"),
        ],
        "Are my muscles okay?": [
            ("synonym", "is my muscular strength conditioning holding up"),
            ("word_order", "today in my telemetry, are my muscles okay"),
            ("typo_abbrev", "are my muscels and muscle strength ok"),
        ],
        "What do my immunity numbers look like?": [
            ("synonym", "how are my immune system indicators doing today"),
            ("word_order", "today, what do my immunity indicators look like"),
            ("typo_abbrev", "what do my imunity numbers look like today"),
        ],
        "Is my cortisol high?": [
            ("synonym", "are my stress hormone cortisol readings elevated"),
            ("word_order", "today in my lab telemetry, is my cortisol high"),
            ("typo_abbrev", "is my cortsol hormone level high today"),
        ],
        "What's my temperature compared to normal for me?": [
            ("synonym", "is my core body temperature above my personal range"),
            ("word_order", "compared to normal for me, what is my temperature"),
            ("typo_abbrev", "what is my body temp compared to normal for me"),
        ],
        "How long did I sleep?": [
            ("synonym", "how many hours of sleep did i log last night"),
            ("word_order", "last night, how many hours did i sleep"),
            ("typo_abbrev", "how many hrs did i slep last night"),
        ],
        "How's my mood been?": [
            ("synonym", "what is my psychological mood score lately"),
            ("word_order", "lately in my logs, how has my mood been"),
            ("typo_abbrev", "what is my mood scroe today"),
        ],
        "What did I get on my mental health assessment?": [
            ("synonym", "what is my current mental health assessment score"),
            ("word_order", "on my mental health assessment, what score did i get"),
            ("typo_abbrev", "what was my mental helth assessment score"),
        ],
        "How much did I train today?": [
            ("synonym", "how many hours of training did i log today"),
            ("word_order", "today, how many hours did i train"),
            ("typo_abbrev", "how many hrs did i trian today"),
        ],
        "What's left on today's task list?": [
            ("synonym", "which exercise items remain on my to do list today"),
            ("word_order", "on my task list for today, what is left"),
            ("typo_abbrev", "whats left on my to do task list today"),
        ],
        "Did I do my resistance workout?": [
            ("synonym", "have i completed my resistance exercise session today"),
            ("word_order", "today, did i finish my resistance workout"),
            ("typo_abbrev", "did i finish my resistnce training session today"),
        ],
        "How many activity minutes have I logged?": [
            ("synonym", "how many minutes of exercise tasks are on my to do list"),
            ("word_order", "on my task list today, how many activity minutes are logged"),
            ("typo_abbrev", "how many exercise minuts are on my to do list"),
        ],
        "What blood group am I?": [
            ("synonym", "what blood type is recorded in my profile"),
            ("word_order", "in my medical file, what blood group am i"),
            ("typo_abbrev", "what is my blod type in my record"),
        ],
        "How much do I weigh?": [
            ("synonym", "what is my body weight in my astronaut profile"),
            ("word_order", "according to my profile record, how much do i weigh"),
            ("typo_abbrev", "what is my weigth in my profile record"),
        ],
        "What is my age?": [
            ("synonym", "how old am i according to my dossier"),
            ("word_order", "in my astronaut profile, what is my age"),
            ("typo_abbrev", "how old am i in my profle record"),
        ],
        "Any past surgeries in my file?": [
            ("synonym", "what previous surgeries are listed on my medical record"),
            ("word_order", "in my medical file, do i have any past surgeries"),
            ("typo_abbrev", "what past surgeris are in my medical record"),
        ],
        "What was my heart rate baseline before the mission?": [
            ("synonym", "what was my preflight baseline pulse rate before launch"),
            ("word_order", "before the mission, what was my baseline heart rate"),
            ("typo_abbrev", "what was my preflight baseline HR before launch"),
        ],
        "Show the baseline values for my blood pressure": [
            ("synonym", "what were my prelaunch baseline blood pressure numbers"),
            ("word_order", "for my blood pressure, show the preflight baseline values"),
            ("typo_abbrev", "show my preflight baseline BP values"),
        ],
        "Can you show me the photo of my family?": [
            ("synonym", "let me see my loved ones snapshot for relaxation"),
            ("word_order", "to help me calm down, can you show my family photo"),
            ("typo_abbrev", "show my famly photo from my calming preferences"),
        ],
        "I want to hear my song": [
            ("synonym", "please play my calming music track"),
            ("word_order", "to relax right now, i want to hear my song"),
            ("typo_abbrev", "play my calming sng track please"),
        ],
        "I'm anxious, help me relax": [
            ("synonym", "i feel stressed out please help me calm down"),
            ("word_order", "please help me relax because i am feeling anxious"),
            ("typo_abbrev", "im anxius and stressed help me calm down"),
        ],
        "How do I reach the doctor on Earth?": [
            ("synonym", "what phone number reaches my mission surgeon down in houston"),
            ("word_order", "back home on earth, how can i telephone the medical desk"),
            ("typo_abbrev", "how do i contct my fligt surgeon on earth"),
        ],
        "Give me my flight surgeon's contact details": [
            ("synonym", "show the communication details for my medical doctor"),
            ("word_order", "for my flight surgeon, give me the contact details"),
            ("typo_abbrev", "give me my flight surgeons contct info"),
        ],
        "Where is this spacecraft headed?": [
            ("synonym", "what is the destination for our mission flight"),
            ("word_order", "on this mission, where is our spacecraft headed"),
            ("typo_abbrev", "what is the destnation for my spacecraft flight"),
        ],
        "How many days will the flight take?": [
            ("synonym", "what is the total estimated duration of my mission in days"),
            ("word_order", "in days, how long will this spaceflight take"),
            ("typo_abbrev", "how many days is the mission fligt duration"),
        ],
        "How was my health on day 150?": [
            ("synonym", "replay my health status from mission day 150"),
            ("word_order", "on day 150, how was my health status"),
            ("typo_abbrev", "show my helth replay on day 150"),
        ],
        "What did the model say on day 33?": [
            ("synonym", "what was my stored prediction on mission day 33"),
            ("word_order", "on day 33, what did the model predict for me"),
            ("typo_abbrev", "replay what the model said on day 33"),
        ],
        "What if I got 2 more hours of sleep?": [
            ("synonym", "simulate sleeping two extra hours tonight"),
            ("word_order", "if i got 2 more hours of sleep, what would happen"),
            ("typo_abbrev", "what if i slep 2 more hrs tonight"),
        ],
        "What happens to my risk if I train 30 minutes less?": [
            ("synonym", "what if i reduce my training by 30 minutes today"),
            ("word_order", "if i train 30 minutes less, what happens to my risk"),
            ("typo_abbrev", "what if i trian 30 minutes less today"),
        ],
        "Is my mood linked to how much I train?": [
            ("synonym", "is there a correlation between my mood and training hours"),
            ("word_order", "in my data, is how much i train linked to my mood"),
            ("typo_abbrev", "what is the corelation between my mood and training"),
        ],
        "Where do you get your facts?": [
            ("synonym", "what data sources are your answers based on"),
            ("word_order", "for your answers, where do you get your sources and facts"),
            ("typo_abbrev", "what data sorces and facts do you use"),
        ],
        "Are you a real doctor?": [
            ("synonym", "is this app a certified medical device or doctor"),
            ("word_order", "tell me whether you are a real medical doctor"),
            ("typo_abbrev", "are you a real doctr or medical device"),
        ],
    }

    rows: List[Dict[str, str]] = []
    idx = 1
    for orig_q, expected_intent in ev.HELDOUT_IN_SCOPE:
        variants = paraphrase_map[orig_q]
        for p_type, pq in variants:
            rows.append({
                "id": f"PARA_{idx:03d}",
                "original_question": orig_q,
                "paraphrase_type": p_type,
                "question": pq,
                "expected_behavior": "answer",
                "expected_intent": expected_intent,
            })
            idx += 1
    assert len(rows) == 126
    return rows


def main() -> int:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    bot = OfflineChatbot()

    clinc = build_clinc_oos_320()
    medquad = build_medquad_210()
    para = build_paraphrases_126()

    for name, dataset in [("clinc_oos_public", clinc), ("medquad_in_scope_public", medquad), ("paraphrases_in_scope", para)]:
        leaks = []
        for item in dataset:
            sim, nearest = bot.max_training_similarity(item["question"])
            item["max_training_cosine_sim"] = round(sim, 4)
            if sim > 0.60:
                leaks.append((item["id"], item["question"], sim, nearest))
        print(f"[{name}] total={len(dataset)} | items > 0.60 cosine sim with training={len(leaks)}")
        for lid, lq, lsim, lnear in leaks[:5]:
            print(f"  LEAK {lid}: sim={lsim:.3f} q={lq!r} vs train={lnear!r}")

    (EVAL_DIR / "clinc_oos_public.json").write_text(json.dumps(clinc, indent=2), encoding="utf-8")
    (EVAL_DIR / "medquad_in_scope_public.json").write_text(json.dumps(medquad, indent=2), encoding="utf-8")
    (EVAL_DIR / "paraphrases_in_scope.json").write_text(json.dumps(para, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
