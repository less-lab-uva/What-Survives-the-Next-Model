# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"RBCTest: Leveraging LLMs to Mine and Verify Oracles of API Response Bodies for RESTful API Testing"**. The original paper proposes RBCTest, a multi-step GPT-4o pipeline that mines logical constraints from OpenAPI specifications and generates test cases to detect mismatches between a spec and real API responses. This reproduction replaces the full pipeline with a single Claude Sonnet 4.6 call per service and evaluates it on 8 services from the AGORA+ benchmark using Precision, Recall, and F1 over constraint triples.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Dataset

The dataset files are not included in this directory. Obtain them from the RBCTest repository:

```text
https://github.com/vnkata/RBCTest
```

Two folders are required:

**1. OpenAPI specs and request-response pairs** — copy `datasets/agora/` from the repository and place it one level above this directory:

```text
../datasets/agora/OMDB bySearch/openapi.json
../datasets/agora/OMDB bySearch/*.csv
../datasets/agora/OMDB byIdOrTitle/
../datasets/agora/Yelp getBusinesses/
../datasets/agora/Hotel Search/
../datasets/agora/Spotify createPlaylist/
../datasets/agora/Spotify getAlbumTracks/
../datasets/agora/Spotify getArtistAlbums/
../datasets/agora/Marvel getComicById/
```

**2. Ground-truth constraints** — copy `approaches/agora_data/our_ground_truth/` from the repository and place it one level above this directory:

```text
../approaches/agora_data/our_ground_truth/OMDB bySearch/
../approaches/agora_data/our_ground_truth/OMDB byIdOrTitle/
...
```

Each service folder under `our_ground_truth/` must contain:

```text
response_property_constraints_all_groups.csv
request_response_constraints_all_groups.csv
```

The two GitHub services (`Github CreateOrganizationRepository`, `Github GetOrganizationRepositories`) are excluded because their OpenAPI specifications exceed the 190K token context window limit. `Youtube GetVideos` is excluded because its dataset is not available.

---

## Step 2 — Run the LLM

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 5.0
```

`main.py` reads:

```text
../datasets/agora/<service>/openapi.json
../datasets/agora/<service>/*.csv
prompts/promptA.py
prompts/promptB.py
```

It runs Prompt A and Prompt B on each of the 8 feasible services, checking the budget before every API call. Re-running continues from where it stopped without re-calling the LLM for already completed services.

Outputs are saved to:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

Services whose serialised output exceeds 50 KB are saved to separate files instead, with spaces and special characters in the service name replaced by `_`:

```text
outputs/Spotify_getAlbumTracks_promptB.json
outputs/Spotify_getArtistAlbums_promptA.json
```

Token logs are saved to:

```text
outputs/tokens_A.jsonl
outputs/tokens_B.jsonl
```

---

## Step 3 — Evaluate

```bash
python3 evaluator.py
```

To evaluate a single service:

```bash
python3 evaluator.py "Hotel Search"
```

`evaluator.py` reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
outputs/<safe_service_name>_prompt{A|B}.json   (for large-output services)
../approaches/agora_data/our_ground_truth/<service>/
```

It matches mined constraints to ground truth using the `(operation, response_resource, attribute)` triple as the key, computes Precision, Recall, and F1 per service for both prompts, and prints a per-service comparison table against the paper's baselines.

Results are saved to:

```text
results/rq1_results.json
results/results_A.jsonl
results/results_B.jsonl
```

`rq1_results.json` contains the full per-service breakdown for both prompts. Line 1 of each `results_{A|B}.jsonl` is the aggregate; subsequent lines are per-service.

---

## Metrics

The main metrics are:

```text
Precision  -> TP / (TP + FP) over constraint triples
Recall     -> TP / (TP + FN) over constraint triples
F1         -> harmonic mean of Precision and Recall
```

A constraint is a TP if the mined `(operation, response_resource, attribute)` triple matches a ground-truth triple exactly. Precision, Recall, and F1 are computed over the union of response-property and request-response constraints per service.

---
