# RDFS-LLM-Bench

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![License: CC BY-SA 4.0](https://img.shields.io/badge/Data%20License-CC%20BY--SA%204.0-lightgrey.svg)](LICENSE-DATA)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19867258.svg)](https://doi.org/10.5281/zenodo.19867258)

A Benchmark for Evaluating RDF Schema Inference in LLMs.

Japanese version: [README.ja.md](README.ja.md)

---

## Overview

RDFS-LLM-Bench systematically evaluates how well LLMs can perform RDFS-based reasoning.
The benchmark covers 6 core RDFS rules (rdfs2, rdfs3, rdfs5, rdfs7, rdfs9, rdfs11) and
13 combined rule sets (19 rule configurations in total), with 7 dataset families and
6 inference operation types.

---

## RDFS Rules

| Rule | If … | Then … |
|---|---|---|
| rdfs2 | `<i, rdfs:domain, X>` and `<a, i, b>` | `<a, rdf:type, X>` |
| rdfs3 | `<i, rdfs:range, X>` and `<a, i, b>` | `<b, rdf:type, X>` |
| rdfs5 | `<i, rdfs:subPropertyOf, j>` and `<j, rdfs:subPropertyOf, k>` | `<i, rdfs:subPropertyOf, k>` |
| rdfs7 | `<i, rdfs:subPropertyOf, j>` and `<a, i, b>` | `<a, j, b>` |
| rdfs9 | `<X, rdfs:subClassOf, Y>` and `<a, rdf:type, X>` | `<a, rdf:type, Y>` |
| rdfs11 | `<X, rdfs:subClassOf, Y>` and `<Y, rdfs:subClassOf, Z>` | `<X, rdfs:subClassOf, Z>` |

Combined rule configurations (13): rdfs2\_3, rdfs2\_7, rdfs2\_9, rdfs3\_7, rdfs3\_9, rdfs5\_7, rdfs9\_11, rdfs2\_3\_7, rdfs2\_3\_9, rdfs2\_5\_7, rdfs2\_9\_11, rdfs3\_5\_7, rdfs3\_9\_11

---

## Dataset Families

| Family | Source | Description |
|---|---|---|
| `rk` | LOD samples | Raw real-world triples from DBpedia/Wikidata/schema.org |
| `ls` | LOD samples | Local shuffle: terms swapped/deranged within each entry |
| `gs` | LOD samples | Global shuffle: term slots filled with globally shuffled LOD values |
| `gsc` | LOD samples | Like `gs` but with type-consistent case (PascalCase for classes, camelCase for properties) |
| `ns` | Standalone | Non-Semantic: random 8-char alphanumeric tokens for all term slots |
| `nsc` | Standalone | Non-Semantic with Case: type-specific random tokens (PascalCase / camelCase) |
| `rva` | Standalone | Random Vocabulary Assignment: random DBpedia local names assigned by term type |

---

## Inference Operation Types

Each dataset entry is paired with a prompt based on the **Inference Operation Type**, which defines
how much rule information is given to the model.

| Operation Type | Abbrev. | Description |
|---|---|---|
| Necessary Rule Presentation | NRP | The rule(s) needed for the inference task are given; the model applies them to the premise |
| All-Rule Presentation | ARP | All RDFS rules are given; the model selects and applies as needed |

Each operation type has three **rule info** variants:

| Variant | Suffix | What the model receives |
|---|---|---|
| Full | `-full` | Rule name + definition |
| Name only | `-name` | Rule name only |
| Definition only | `-def` | Rule definition only |

This gives 6 inference operation types in total:
`NRP-full`, `NRP-name`, `NRP-def`, `ARP-full`, `ARP-name`, `ARP-def`

### Valid combinations by rule count

All operation types apply to all rule counts.

| | 1-rule | 2-rule | 3-rule |
|---|---|---|---|
| NRP-full | ✓ | ✓ | ✓ |
| NRP-name | ✓ | ✓ | ✓ |
| NRP-def  | ✓ | ✓ | ✓ |
| ARP-full | ✓ | ✓ | ✓ |
| ARP-name | ✓ | ✓ | ✓ |
| ARP-def  | ✓ | ✓ | ✓ |

NRP prompts adapt their template to the rule count: single-rule scenarios use a singular form ("Solely based on this rule…"), while multi-rule scenarios use a plural form ("…by combining these rules").

---

## Directory Layout

```
scripts/
  fetch-samples/
    1-rule/           fetch_samples_rdfs{N}.py          (6 scripts)
    2-rule/           fetch_samples_rdfs{N}_{M}.py      (7 scripts)
    3-rule/           fetch_samples_rdfs{N}_{M}_{K}.py  (6 scripts)
    shared/           _base.py
  build-dataset/
    from-samples/     gen_rk.py, gen_ls.py, gen_gs-gsc.py
    standalone/       gen_ns.py, gen_nsc.py, gen_rva.py
    shared/           _base.py
    run_all.py
  llm-eval/
    tasks/            build_zeroshot_tasks.py
    adapters/         to_openai_batch.py, to_sequential.py
    run/              openai_batch_upload.py, openai_batch_download.py
                      run_sequential_openai_compat.py, run_sequential_ollama.py
    eval/             evaluate_outputs.py
    report/           aggregate_scores.py, export_excel.py,
                      compute_composite_metrics.py,
                      analyze_scaling.py, analyze_rule_accuracy.py
    shared/           rule_defs.py, prompt_builder.py, io.py, naming.py,
                      eval_utils.py
    model-config.json

data/
  lod-samples/
    {1,2,3}-rule/     lod-sample__{rule}__n{N}__f-xxxxxxxx.json
  datasets/
    {rk,ls,gs,gsc,ns,nsc,rva}/
      {1,2,3}-rule/   dataset__{type}__{rule}__n{N}__f-xxxxxxxx__b-xxxxxxxx.json
  llm-eval/
    tasks/
      zeroshot/
        {operation_type}/{dataset_type}/{n-rule}/
                        task__{op}__{type}__{rule}__n{N}__...json
    requests/
      openai-batch/
        {model-slug}/{operation_type}/{dataset_type}/{n-rule}/
                        batch__{model-slug}__{op}__{type}__{rule}__n{N}__...jsonl
      sequential/
        {model-slug}/{operation_type}/{dataset_type}/{n-rule}/
                        seq__{model-slug}__{op}__{type}__{rule}__n{N}__...jsonl
    responses/
      openai-batch/
        {model-slug}/{operation_type}/{dataset_type}/{n-rule}/
                        response__{model-slug}__{op}__{type}__{rule}__n{N}__...
                          __batch_{batch-id}__{YYYYMMDDHHMMSS}.jsonl
    eval/
      {strict,flex}/
        {response_type}/{model}/{operation_type}/{dataset_type}/{n-rule}/
                        eval-{mode}__{model}__{op}__{type}__{rule}__n{N}__...jsonl
    reports/
      {strict,flex}/
                        scores-{mode}.csv
                        scores-{mode}__{model}.xlsx
                        composite_metrics-{mode}.csv
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Fetch LOD samples

Single rule:

```bash
python scripts/fetch-samples/1-rule/fetch_samples_rdfs2.py --date 20260418
```

All 19 rule configurations:

```bash
for f in \
  scripts/fetch-samples/1-rule/fetch_samples_*.py \
  scripts/fetch-samples/2-rule/fetch_samples_*.py \
  scripts/fetch-samples/3-rule/fetch_samples_*.py
do
  echo ">>> $f"
  python "$f" --date 20260418
done
```

### 3. Update `lod-sample-config.json`

Set each rule to point to the sample file you want to use:

```
scripts/build-dataset/lod-sample-config.json
```

### 4. Build benchmark datasets

```bash
# All families at once
python scripts/build-dataset/run_all.py

# Or individual families
python scripts/build-dataset/from-samples/gen_rk.py
python scripts/build-dataset/from-samples/gen_ls.py
python scripts/build-dataset/from-samples/gen_gs-gsc.py
python scripts/build-dataset/standalone/gen_ns.py
python scripts/build-dataset/standalone/gen_nsc.py
python scripts/build-dataset/standalone/gen_rva.py
```

Output: `data/datasets/{family}/{1,2,3}-rule/dataset__*.json`

---

## LLM Evaluation Pipeline

### Step 1 — Build zero-shot task files

Generates prompt files from benchmark datasets for each inference operation type.

```bash
# All operation types and dataset families
python scripts/llm-eval/tasks/build_zeroshot_tasks.py

# Filtered example
python scripts/llm-eval/tasks/build_zeroshot_tasks.py \
  --dataset-types rva,gs \
  --operation-types NRP-full,ARP-full \
  --rules rdfs2,rdfs9
```

| Argument | Default | Description |
|---|---|---|
| `--dataset-types` | all | Comma-separated dataset families (e.g. `rva,gs`) |
| `--operation-types` | all 6 | Comma-separated operation types (e.g. `NRP-full,ARP-name`) |
| `--rules` | all | Comma-separated rule ids (e.g. `rdfs2,rdfs2_3`) |
| `--entry-limit` | 0 (all) | Debug: cap entries per dataset file |
| `--max-files` | 0 (all) | Debug: process only first N dataset files |
| `--overwrite` | skip existing | Overwrite existing task files instead of skipping them |
| `--verbose` | — | Print each saved file path (default: summary only) |

Output: `data/llm-eval/tasks/zeroshot/{operation_type}/{dataset_type}/{n-rule}/task__*.json`

### Step 2 — Convert to request files

**OpenAI Batch API:**

```bash
python scripts/llm-eval/adapters/to_openai_batch.py \
  --model gpt-4o-mini-2024-07-18 \
  --operation-types NRP-full \
  --dataset-types rva
```

**Sequential (OpenAI-compatible / Ollama):**

```bash
python scripts/llm-eval/adapters/to_sequential.py \
  --model llama3.1-8b \
  --operation-types NRP-full \
  --dataset-types rva
```

Available models are defined in `scripts/llm-eval/model-config.json`. The `--model` argument takes the slug (key in the config); the actual API model name is resolved internally.

### Step 3 — Run LLM inference

Each runner uses a dedicated queue base directory. Create a named subdirectory, place the request files inside, then run the script with `--queue <name>`.

```
data/llm-eval/requests/input-queues/
  openai-batch/
    <queue-name>/   ← place batch__*.jsonl here
  openai-compat/
    <queue-name>/   ← place seq__*.jsonl here
  ollama/
    <queue-name>/   ← place seq__*.jsonl here
```

**OpenAI Batch:**

```bash
python scripts/llm-eval/run/openai_batch_upload.py --queue <queue-name>
python scripts/llm-eval/run/openai_batch_download.py --queue <queue-name>
```

The upload result is recorded in `input-queues/openai-batch/<queue-name>/upload_mapping.json`.
Re-run download until all batches are completed.

**Sequential (OpenAI-compatible API):**

Targets models with `runner: "sequential-openai-compat"` in `model-config.json`.
Requires the following variables in `.env`:

```
OPENAI_COMPAT_API_KEY=<your-api-key>
OPENAI_COMPAT_BASE_URL=https://api.deepinfra.com/v1/openai
```

```bash
python scripts/llm-eval/run/run_sequential_openai_compat.py --queue <queue-name>
```

**Sequential (Ollama):**

Targets models with `runner: "sequential-ollama"` in `model-config.json`.
Requires a running Ollama daemon with the target model pulled.

```bash
python scripts/llm-eval/run/run_sequential_ollama.py --queue <queue-name>
```

By default, the local Ollama daemon is used. To use a remote host, set `OLLAMA_HOST` in `.env` and pass `--use-host`:

```
OLLAMA_HOST=http://<host>:<port>
```

```bash
python scripts/llm-eval/run/run_sequential_ollama.py --queue <queue-name> --use-host
```

For a one-off override without `.env`:

```bash
python scripts/llm-eval/run/run_sequential_ollama.py --queue <queue-name> --ollama-host http://<host>:<port>
```

If `--queue` is omitted, available queue names are listed. All three runners share these arguments:

| Argument | Default | Description |
|---|---|---|
| `--queue` | required | Queue subdirectory name (e.g. `queue1`) |
| `--overwrite` | skip existing | Re-run / re-upload files already processed |
| `--yes` | prompt | Skip confirmation prompt |
| `--dry-run` | — | Show what would run without calling the API |
| `--verbose` | — | Print skipped file paths |
| `--fallback-root` | skip | (sequential only) Save to response root directly when filename cannot be parsed |

Output: `data/llm-eval/responses/sequential/{slug}/{operation_type}/{dataset_type}/{n-rule}/response__*.jsonl`

### Step 4 — Evaluate outputs

By default, all response types (`openai-batch`, `sequential`, etc.) under `data/llm-eval/responses/` are evaluated together.

```bash
# strict mode (default): only canonical <s, p, o> format accepted
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict

# flex mode: order-based matching; accepts <s,p,o>, <s p o>, <X rdf:type Y>, etc.
python scripts/llm-eval/eval/evaluate_outputs.py --mode flex

# evaluate a specific response type only
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict --response-type sequential
python scripts/llm-eval/eval/evaluate_outputs.py --mode strict --response-type openai-batch
```

| Argument | Default | Description |
|---|---|---|
| `--mode` | `strict` | Evaluation mode: `strict` or `flex` |
| `--response-type` | all | Sub-directory under `responses/` to scan (e.g. `openai-batch`, `sequential`). Omit to evaluate all. |
| `--models` | all | Comma-separated model slugs to filter |
| `--operation-types` | all | Comma-separated operation types to filter (e.g. `NRP-full,ARP-name`) |
| `--dataset-types` | all | Comma-separated dataset types to filter |
| `--rules` | all | Comma-separated rule ids to filter |
| `--overwrite` | skip existing | Overwrite existing eval files |
| `--verbose` | — | Print per-file details |

Output: `data/llm-eval/eval/{strict,flex}/{response_type}/{model}/...`

### (Optional) Check experiment status

Export a per-model Excel sheet showing which experiments have been run:

```bash
python scripts/llm-eval/report/export_status_excel.py --overwrite
```

Output: `data/llm-eval/reports/status.xlsx` (one sheet per model)

Each cell shows the status for a (op-type, rule-id, dataset-type) combination:

| Symbol | Meaning |
|--------|---------|
| ○ | Response file exists and **all UIDs match** the task file (correct experiment) |
| △ | Response file exists but at least one UID differs (e.g. run with a different prompt template) |
| × | Task file exists but no response yet (experiment not run) |
| - | Combination is structurally undefined (e.g. rdfs5 on gs/gsc) |

Cells relevant to composite metrics are highlighted with a hatched amber fill.

| Option | Default | Description |
|--------|---------|-------------|
| `--task-root` | `data/llm-eval/tasks/zeroshot` | Root of task files |
| `--response-root` | `data/llm-eval/responses` | Root of response files |
| `--report-root` | `data/llm-eval/reports` | Output directory |
| `--overwrite` | skip existing | Overwrite existing output file |

### (Optional) Estimate API budget

Estimate input/output token counts and API costs from the request files in `input-queues`:

```bash
python scripts/llm-eval/run/estimate_budget.py --overwrite
```

Output: `data/llm-eval/reports/budget_estimate.xlsx`

- **Summary sheet** — total input/output tokens and estimated cost per model
- **Detail sheet** — breakdown per (model, op-type, dataset, rule)

Input tokens are counted from the prompt messages in each request file.
Output tokens are estimated from `expected_output` in the corresponding task file (ARP operations also include the expected `[used_rules: ...]` line).

Pricing is configured in `scripts/llm-eval/model-pricing.json` (USD per 1M tokens). Edit this file to update rates before running.

### Step 5 — Aggregate scores

```bash
python scripts/llm-eval/report/aggregate_scores.py --mode strict
python scripts/llm-eval/report/aggregate_scores.py --mode flex
```

Output: `data/llm-eval/reports/{strict,flex}/scores-{mode}.csv`

### Step 6 — Export to Excel

```bash
python scripts/llm-eval/report/export_excel.py --mode strict
python scripts/llm-eval/report/export_excel.py --mode flex
```

Output: `data/llm-eval/reports/{strict,flex}/scores-{mode}__{model}.xlsx`

### Step 7 — Compute composite metrics

```bash
python scripts/llm-eval/report/compute_composite_metrics.py --mode strict
python scripts/llm-eval/report/compute_composite_metrics.py --mode flex
```

Output: `data/llm-eval/reports/{strict,flex}/composite_metrics-{mode}.csv`

### (Optional) Scaling analysis

How F1 changes across 1-rule / 2-rule / 3-rule (rule_info == "full" only):

```bash
python scripts/llm-eval/report/analyze_scaling.py --mode strict
python scripts/llm-eval/report/analyze_scaling.py --mode flex
```

Output: `data/llm-eval/reports/{strict,flex}/scaling_analysis-{mode}.xlsx` (one sheet per dataset type)

### (Optional) Rule-level analysis

Per-rule F1 breakdown using only single-rule scenarios (n_rule == 1, rule_info == "full"). Multi-rule scenarios are excluded so that each rule's score reflects its intrinsic difficulty without contamination from other rules in chained patterns.

```bash
python scripts/llm-eval/report/analyze_rule_accuracy.py --mode strict
python scripts/llm-eval/report/analyze_rule_accuracy.py --mode flex
```

Output: `data/llm-eval/reports/{strict,flex}/rule_accuracy_analysis-{mode}.xlsx` (one sheet per dataset type)

### (Optional) F1 by dataset variant

A single-table summary of F1 averaged over the six (NRP/ARP × {1-rule, 2-rule, 3-rule}) cells under the full setting, with rows = LLMs and columns = dataset variants:

```bash
python scripts/llm-eval/report/f1_by_dataset_table.py --mode strict
python scripts/llm-eval/report/f1_by_dataset_table.py --mode flex
```

Output: `data/llm-eval/reports/{strict,flex}/f1_by_dataset-{mode}.xlsx`

---

## Evaluation Modes

Two evaluation modes are supported, selectable via `--mode` in Steps 4–7.

| Mode | Description |
|---|---|
| `strict` | Only the canonical `<s, p, o>` format (comma + space separated) is accepted as a valid triple. Measures both reasoning ability and format compliance. |
| `flex` | Accepts any `<...>` token that contains s, p, o in order, separated only by `,`, ` `, or `<>` characters. Handles variants like `<s,p,o>`, `<s p o>`, `<X rdf:type Y>`. Measures reasoning ability independent of format compliance. |

The difference between strict and flex scores quantifies the impact of output format non-compliance.

---

## Data Format

### Dataset entry (`data/datasets/`)

```json
{
  "metadata": {
    "rule_id": "rdfs2",
    "rules": ["rdfs2"],
    "dataset_type": "rva",
    "fetch_uid": "v-a1b2c3d4",
    "build_uid": "b-e5f6g7h8"
  },
  "entries": [
    {
      "premise_knowledge": "<hasJob, rdfs:domain, Person>, <Alice, hasJob, Engineer>",
      "expected_output": "<Alice, rdf:type, Person>"
    }
  ]
}
```

### Task file (`data/llm-eval/tasks/zeroshot/`)

```json
{
  "metadata": {
    "operation_type": "NRP-full",
    "dataset_type": "rva",
    "rule_id": "rdfs2",
    "rules": ["rdfs2"]
  },
  "tasks": [
    {
      "task_id": "request-1",
      "system_prompt": "You are a helpful assistant.",
      "user_prompt": "Given the following rule and premise knowledge: ...",
      "premise_knowledge": "<hasJob, rdfs:domain, Person>, <Alice, hasJob, Engineer>",
      "expected_output": "<Alice, rdf:type, Person>"
    }
  ]
}
```

---

## File Naming Conventions

| File type | Pattern |
|---|---|
| LOD sample | `lod-sample__{rule}__n{N}__f-{uid}.json` |
| Dataset | `dataset__{type}__{rule}__n{N}__f-{uid}__b-{uid}.json` |
| Task | `task__{op}__{type}__{rule}__n{N}__{uid}__{uid}.json` |
| Batch request | `batch__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}.jsonl` |
| Sequential request | `seq__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}.jsonl` |
| Batch response | `response__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}__batch_{id}__{ts}.jsonl` |
| Eval result | `eval-{mode}__{slug}__{op}__{type}__{rule}__n{N}__{uid}__{uid}__batch_{id}__{ts}.jsonl` |

UIDs: `f-` = fetch/source (LOD-based datasets), `b-` = build  
`{slug}` = model slug defined in `model-config.json`  
`{ts}` = `completed_at` timestamp from OpenAI Batch API (`YYYYMMDDHHMMSS`, UTC)

---

## Troubleshooting

**`0 rows available` during fetch**
SPARQL endpoint load or temporary instability. Wait and retry.

**`lod-sample file not found`**
The path in `scripts/build-dataset/lod-sample-config.json` does not match the actual sample filename. Update the config.

---

## License

**Code** (`scripts/`): [MIT License](LICENSE) © 2026 Taichi Hosokawa

**Data** (`data/lod-samples/`, `data/datasets/`, `data/llm-eval/`): [CC BY-SA 4.0](LICENSE-DATA)

The datasets are derived from the following sources:

- [DBpedia](https://dbpedia.org) — CC BY-SA 3.0
- [Wikidata](https://www.wikidata.org) — CC0 1.0
- [schema.org](https://schema.org) — CC BY-SA 3.0

Data was collected via SPARQL queries against the public endpoints of the above sources.

