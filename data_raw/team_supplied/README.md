# NASA Space Apps Challenge 2026: Health Monitoring Software Dataset
**Target Folder:** `D:\data nasa\`
**Consolidated Standalone File:** `D:\data nasa.json`
**Date Extracted:** 2026-11-13

---

## 📌 Dataset Overview
This folder contains the complete, extracted data from the NASA Space Apps Challenge 2026 resource suite for the challenge:
**"Create Health Monitoring Software for Astronauts on Space Missions"**  
URL: `https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/?tab=resources`

All data has been structured in both human-readable Markdown (`.md`) and machine-readable JSON (`.json` / `.jsonl`) formats, optimized for:
1. **AI Model Analysis & Fine-Tuning:** Ingesting domain-specific spaceflight physiology and clinical risk structures.
2. **Retrieval-Augmented Generation (RAG):** Pre-chunked documents in `09_rag_documents.jsonl`.
3. **Telemetry & Feature Engineering:** Explicit metric ranges, thresholds, and sensor modalities in `07_health_indicators_schema.json`.

---

## 📂 Directory Contents

| File | Description |
|---|---|
| `00_challenge_details.json` / `.md` | Full challenge prompt, summary, background, objectives, video link, and UI considerations. |
| `01_resources_catalog.json` / `.md` | Index of all resources (R0 to R5) with official URLs, host organizations, and descriptions. |
| `02_nasa_5_hazards_of_human_spaceflight.json` / `.md` | Detailed breakdown of the 5 hazards (Radiation, Isolation, Distance, Gravity, Hostile Environments). |
| `03_nasa_hrp_risks_and_countermeasures.json` / `.md` | NASA Human Research Program risk elements (HHC, HFBP, ExMC, SRE) and clinical countermeasures. |
| `04_nasa_ongoing_hrp_research.json` / `.md` | Ongoing campaigns: CIPHER, Standard Measures, and ground analogs (HERA, CHAPEA, bed rest). |
| `05_csa_monitoring_radiation_for_astronaut_health.json` / `.md` | Full CSA article on radiation, CANS instrument, and 30% neutron radiation contribution on the ISS. |
| `06_csa_science_experiments_in_space.json` / `.md` | Full CSA article & transcript on microgravity physiological changes and the accelerated aging model. |
| `07_health_indicators_schema.json` | Comprehensive telemetry definitions, baselines, alert thresholds, and units for model training. |
| `08_all_resources_consolidated.json` | Single consolidated JSON file containing all metadata, text, and structures. |
| `09_rag_documents.jsonl` | Line-delimited JSON with metadata for vector embeddings, semantic search, or RAG pipelines. |

---

## 🚀 How to Ingest with Another AI Model

### In Python (Single Consolidated File):
```python
import json

with open(r"D:\data nasa\08_all_resources_consolidated.json", "r", encoding="utf-8") as f:
    space_data = json.load(f)

# Access indicators, hazards, or risks directly:
indicators = space_data["health_indicators_schema"]["indicators"]
hazards = space_data["nasa_5_hazards"]["hazards"]
```

### In LangChain / LlamaIndex / Vector DBs:
```python
import json

documents = []
with open(r"D:\data nasa\09_rag_documents.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        doc = json.loads(line)
        documents.append(doc)
```
