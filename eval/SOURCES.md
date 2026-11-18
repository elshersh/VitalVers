# Chatbot Evaluation Datasets — Sources & Licenses (`eval/`)

This directory holds the four separate evaluation sources required by **Phase 4 (C2 Unbiased Evaluation)**, along with the topic mapping (`eval/topic_map.json`) and label dispute log (`eval/label_disputes.md`) required by **Ground Rule 6**.

| Source ID | File | Count | Author / Provenance | License | Purpose |
|---|---|---:|---|---|---|
| **(a) Public Out-of-Scope Set** | `eval/clinc_oos_public.json` | 320 | Out-of-scope queries adapted from the public **CLINC150 OOS** benchmark domains (Larson et al., *EMNLP 2019*: travel, banking, weather, kitchen/dining, automotive, utility/IT, general trivia, plus spacecraft/engineering hardware queries with keyword overlap). | CC BY 3.0 (`https://github.com/clinc/oos-eval`) | Measures false-acceptance / keyword-leakage rate on out-of-scope queries across 8 non-clinical domains. |
| **(b) Public Health-Question Set** | `eval/medquad_in_scope_public.json` | 220 | Consumer health & self-monitoring questions adapted from public **NIH MedQuAD / LiveQA Medical** consumer QA patterns (Ben Abacha & Demner-Fushman, *BMC Bioinformatics 2019*), mapped to 17 covered astronaut health intents (`170` queries) plus clinical prescription/diagnosis/unmeasured refusal controls (`50` queries). | U.S. Government Public Domain (NIH corpora) / CC BY 4.0 (`https://github.com/abachaa/MedQuAD`) | Measures intent routing sensitivity and clinical guard-rule specificity on consumer health phrasings. |
| **(c) Paraphrase Stress Test** | `eval/paraphrases_in_scope.json` | 126 | 3 systematic paraphrases per held-out in-scope question (`42 × 3 = 126` queries): (1) synonym substitution, (2) word-order / clause permutation, and (3) common typos or clinical abbreviations (`BP`, `HR`, `SpO2`, `temp`, `PVT`). | Project-generated evaluation artifact (MIT) | Quantifies routing accuracy drop under lexical, syntactic, abbreviation, and character-typo perturbations. |
| **(d) External Question Set** | `eval/external_questions.csv` | 100 | Externally authored evaluation set (`60` answer, `40` refuse) across 16 `style_tag` categories. **Labeled in reports as: `external, AI-authored (not human)`.** | Project evaluation benchmark (unmodified per Ground Rule 6) | Final blind evaluation of scope gating, hard-negative keyword discrimination, urgent escalation, and intent routing. |

---

## Anti-Leakage Verification Rule (Phase 4 C2)

Before running evaluation in `test_chatbot.py`, every question across sets **(a)**, **(b)**, **(c)**, and **(d)** is checked via TF-IDF word-ngram cosine similarity against all training examples in `offline_ai_chatbot.py`:
- Any question in **(a)–(c)** with similarity `> 0.60` is flagged/removed during dataset verification.
- Any question in **(d)** (`eval/external_questions.csv`) with similarity `> 0.60` is flagged in the evaluation output without modifying `eval/external_questions.csv`.
