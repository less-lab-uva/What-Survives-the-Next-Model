# RBCTest — LLM Replacement Study on AGORA+ Benchmark

This directory extends the original [RBCTest](https://doi.org/10.1145/3744916.3787775) pipeline with an LLM replacement study. We replace the multi-step GPT-4o pipeline with a single Claude Sonnet 4.6 call and evaluate it on the AGORA+ benchmark using the same Precision/Recall/F1 metric reported in the original paper (RQ1: constraint mining).

---

## Overview

RBCTest automatically mines logical constraints from OpenAPI specifications (OAS) and generates test cases to detect mismatches between a spec and real API responses. The original pipeline has three phases driven by GPT-4o:

1. **Constraint Mining** — LLM reads the OAS and a real response to extract two constraint types:
   - **Response Property (RP):** constraints on field schemas (data type, enum values, URI format, nullable, etc.)
   - **Request-Response (RR):** constraints where a request parameter determines a response field value (e.g., the `type` query parameter determines the `Type` field in every result)
2. **Test Generation** — LLM generates Python verification scripts for each constraint.
3. **Test Execution** — Scripts are executed against real responses to produce verdicts.

The original pipeline uses an Observation-Confirmation (OC) two-step prompting scheme per constraint and reports results averaged over 5 independent runs.

In this study, we replace all LLM phases with a **single Claude Sonnet 4.6 call** per service that outputs both constraint types in one structured JSON response. Two prompt strategies are compared:

- **Prompt A (Black-box):** Provides the output JSON schema and a worked example, but no explicit reasoning methodology.
- **Prompt B (Chain-of-thought):** Adds 9 explicit reasoning steps: read spec paths → observe property schemas → identify RP constraints → observe request parameters → trace RR relationships → identify RR constraints → generate verification scripts → format output → verify completeness.

---

## Why These 9 Services

The AGORA+ benchmark includes 11 services. We evaluate 9 of them:

| Service | GT constraints | Reason included |
|---|---|---|
| OMDB bySearch | 6 | Small OAS, representative |
| OMDB byIdOrTitle | 15 | Small OAS, representative |
| Yelp getBusinesses | 4 | Small-to-medium OAS |
| Hotel Search | 59 | Largest RP/RR GT set among feasible services |
| Spotify createPlaylist | 27 | Medium OAS, mixed constraint types |
| Spotify getAlbumTracks | 21 | Medium OAS |
| Spotify getArtistAlbums | 16 | Medium OAS |
| Marvel getComicById | 50 | Large GT set |
| Youtube GetVideos | 161 | Largest single service GT |

The two GitHub services (`Github CreateOrganizationRepository`, `Github GetOrganizationRepositories`) are excluded because their OpenAPI specifications are ~1.6 MB (~460K tokens) each, far exceeding the 190K token context window limit. No amount of truncation would preserve the full spec needed for constraint mining.

---

## Prerequisites

**Python packages:**
```bash
pip install -r requirements.txt
```

This installs only the Anthropic Python SDK. No other packages are required by `with_sonnet/`.

**Environment variable:**
```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

---

## Dataset

The pipeline reads from two directories that are part of the RBCTest replication package:

| Path (relative to `with_sonnet/`) | Contents |
|---|---|
| `../datasets/agora/<service>/openapi.json` | OpenAPI specification for each service |
| `../datasets/agora/<service>/*.csv` | Request-response pairs collected from the live API |
| `../approaches/agora_data/our_ground_truth/<service>/` | Hand-annotated ground-truth constraints (RP and RR CSVs) |

These directories are **not** included in this repository. To obtain them:

1. Download the full RBCTest replication package from the paper's artifact (linked via the ACM DL page at `https://doi.org/10.1145/3744916.3787775`).
2. Place the `datasets/` and `approaches/` folders one level above `with_sonnet/` (i.e., at `RBCTest/datasets/` and `RBCTest/approaches/`).

The AGORA+ dataset originates from the AGORA paper (Corradini et al.). The RBCTest authors extended it with additional ground-truth annotations; use the version bundled in the RBCTest artifact, not the original AGORA release.

---

## Step 1 — Generate Predictions

`main.py` runs both prompts on all 9 feasible AGORA+ services until the budget is exhausted or all services are completed.

```bash
python3 main.py <budget_usd>
```

Example:
```bash
python3 main.py 5.0
```

**Behavior:**
- Loads all 9 services at startup and prints their status (done / not started).
- For each service, runs Prompt A then Prompt B sequentially.
- Checks the remaining budget before every API call and stops when exhausted.
- Is fully resumable: re-running continues from where it stopped.
- Partially completed services (one prompt done) are always finished before new ones start.
- Performs a token pre-flight check before each call; services exceeding ~190K estimated tokens are logged as skipped (none of the 9 services are skipped in practice).

**Outputs** (under `outputs/`):

| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per service: `service_name`, `prompt`, `request_info`, `response_body`, `response_property_constraints`, `request_response_constraints` |
| `outputs_B.jsonl` | Same for Prompt B |
| `Spotify_getAlbumTracks_promptB.json` | Separate file for outputs > 50 KB |
| `Spotify_getArtistAlbums_promptA.json` | Separate file for outputs > 50 KB |
| `tokens_A.jsonl` | Per-call token counts, cost, and wall-clock time for Prompt A |
| `tokens_B.jsonl` | Same for Prompt B |

**Estimated cost** (Claude Sonnet 4.6, $3/MTok input, $15/MTok output):
- All 9 services × 2 prompts: ~$2.34 total
- Youtube GetVideos is the most expensive service (~$0.51 for both prompts) due to its 185KB OAS spec.

---

## Step 2 — Evaluate (RQ1)

```bash
python3 evaluator.py
```

To evaluate a single service:
```bash
python3 evaluator.py "Hotel Search"
```

**What it does:**
1. Loads ground-truth constraints from `approaches/agora_data/our_ground_truth/<service>/`.
2. Matches mined constraints to ground truth using the `(operation, response_resource, attribute)` triple as the key.
3. Computes Precision, Recall, and F1 per service for both Prompt A and Prompt B.
4. Prints a per-service table and saves results to `results/`.

**Results** (under `results/`):

| File | Description |
|---|---|
| `rq1_results.json` | Full per-service breakdown for both prompts with paper baselines |
| `results_A.jsonl` | Per-service P/R/F1 for Prompt A |
| `results_B.jsonl` | Per-service P/R/F1 for Prompt B |

---

## Results and Comparison

### RQ1: Constraint Mining (macro-averaged P/R/F1 across 9 services)

| System | Precision | Recall |
|---|---|---|---|
| RBCTest | 85.1% | 83.7% |
| Ours — Prompt A | 53.7% | 41.6% |
| Ours — Prompt B | 61.8% | 40.6% |

> Paper baselines are for the 9 feasible services only (5-seed mean from `CompareAGORAData.xlsx`). Full per-service breakdown is in `results/rq1_results.json`.

### Per-service F1 comparison

| Service | Paper F1 | Prompt A F1 | Prompt B F1 |
|---|---|---|---|
| OMDB bySearch | 80.0 | **100.0** | **100.0** |
| OMDB byIdOrTitle | 85.5 | 58.3 | 54.5 |
| Yelp getBusinesses | 71.1 | 0.0 | 0.0 |
| Hotel Search | 83.9 | 55.6 | 60.3 |
| Spotify createPlaylist | 75.0 | 35.0 | 37.8 |
| Spotify getAlbumTracks | 80.9 | 66.7 | 60.6 |
| Spotify getArtistAlbums | 87.5 | 58.8 | 66.7 |
| Marvel getComicById | 81.2 | 24.2 | 17.6 |
| Youtube GetVideos | 89.1 | 3.8 | 10.2 |

---

## Analysis

### Where the paper's approach outperforms ours

The original RBCTest achieves significantly higher F1 on 8 of 9 services. Several factors explain the gap:

1. **Multi-step Observation-Confirmation (OC) scheme.** The paper's pipeline uses a dedicated prompt per constraint: first an "observation" prompt that contextualises what to look for, then a "confirmation" prompt that verifies presence. This two-pass approach drastically reduces hallucination. Our single call asks the model to both discover and verify constraints simultaneously.

2. **5-seed averaging.** The paper averages results across 5 independent runs, reducing stochastic variance. We run each service once, so a single bad generation is not compensated.

3. **Recall collapse on large services.** For Marvel getComicById (GT=50) and Youtube GetVideos (GT=161), our mined counts are only 20 and 10 respectively. When the OAS is large and the model is asked to enumerate all constraints at once, it tends to produce only a partial list — particularly when the OAS contains many repeated schema patterns. The paper's iterative per-constraint prompting avoids this.

4. **Yelp getBusinesses (F1=0).** The LLM mined 14 constraints (A) / 8 constraints (B), all of which were false positives — none matched the 4 ground-truth triples. The GT for this service uses a non-obvious `(operation, response_resource, attribute)` triple format; our model generated valid-looking but differently-keyed constraints that did not align with the GT matching logic.

5. **Ground-truth count discrepancies.** For several services our evaluator reports lower GT counts than the paper (e.g., Hotel Search: 46 vs paper 59). The evaluator matches constraints against the full GT CSV; discrepancies arise because the paper processes multiple response variants while we send a single randomly-sampled response per service, so some GT triples reference schema branches not present in our specific response.

### Where our approach matches or exceeds

- **OMDB bySearch** — both prompts achieve F1=100 vs the paper's 80.0. This is the simplest service (6 constraints, small OAS), where a single call is sufficient.
- **Prompt B is generally better than Prompt A.** The chain-of-thought structure improves Precision (+8 pp macro) and produces more conservative mining, reducing false positives (FP: 51 vs 67).
- **Single-call cost efficiency.** At ~$2.34 total for all 9 services × 2 prompts, our approach is significantly cheaper than running GPT-4o across 5 seeds with multi-step prompting per constraint.

### Summary

The paper's approach is substantially better on recall-heavy, large services. The single-call strategy works well for compact, well-structured APIs (OMDB) but struggles to enumerate exhaustive constraint lists from complex multi-schema OAS documents. Adding an iterative enumeration step (one prompt per endpoint section rather than the entire spec at once) would likely recover a large portion of the recall gap.
