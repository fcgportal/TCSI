# TCSI

**Patient-level prioritization of clinically actionable antibody-drug conjugate (ADC) targets using clinical-development status and precomputed tumor/normal expression scores.**

This repository contains the target-prioritization workflow associated with the manuscript:

> **Systematic Characterization of Clinically Actionable Antibody-Drug Targets Across Solid Tumors to Advance Precision Oncology**  

## Overview

`prioritize_adc_targets.final.py` combines two inputs:

1. A target-level table describing the highest clinical-development stage and approved cancer types.
2. A multi-patient matrix containing a precomputed `N_score pass` and `T_score` for each gene and patient.

The script normalizes clinical-stage labels, assigns each patient–gene pair to **Tier 1–9** or **Unranked**, sorts the results by tier and score, and writes one CSV or tab-delimited output file.

By default, the workflow also queries an Azure OpenAI deployment for literature summaries for Tier 1 and Tier 2 targets. The default deployment name in the script is `gpt-4o`. Use `--no-enrich` to run only the deterministic tier-assignment workflow without external API calls.

The definitions and derivation of `N_score pass` and `T_score` are described in the associated manuscript; this repository treats them as precomputed inputs.

## Repository contents

| Path | Description |
|---|---|
| `prioritize_adc_targets.final.py` | Main command-line target-prioritization program. |
| `data/clinical_targets.csv` | Candidate targets, highest clinical stage, and approval cancer types. |
| `data/patient_scores.csv` | Multi-patient `N_score pass`/`T_score` matrix with a two-row header. |
| `results/TCSI_prioritized_targets.csv` | Generated patient-level target-prioritization table. |
| `requirements.txt` | Pinned Python dependencies. |
| `LICENSE` | MIT license for the original code and documentation. |

## Prioritization rules

Clinical-stage values are normalized before tier assignment:

- Approved targets whose approval text contains `colon`, `pancancer`, or `pan-cancer` are labeled `fda-approved (colon cancer)`.
- Other approved targets are labeled `fda-approved (non-colon cancer)`.
- Phase 3 and Phase 2/3 targets are labeled `late-stage`.
- Phase 1, Phase 1/2, and Phase 2 targets are labeled `early-stage`.

The implemented tier rules are:

| Tier | Rule |
|---|---|
| Tier 1 | FDA-approved in colon/pan-cancer and `T_score > 0`. |
| Tier 2 | FDA-approved outside colon cancer and `T_score > 0`. |
| Tier 3 | Late-stage and `T_score >= 0.5`. |
| Tier 4 | Early-stage and `T_score >= 0.5`. |
| Tier 5 | FDA-approved, `N_score == 1`, and not already assigned to Tier 1 or 2. |
| Tier 6 | Late-stage and `0 < T_score < 0.5`. |
| Tier 7 | Early-stage and `0 < T_score < 0.5`. |
| Tier 8 | Late-stage, no positive `T_score`, and `N_score == 1`. |
| Tier 9 | Early-stage, no positive `T_score`, and `N_score == 1`. |
| Unranked | Does not meet any rule above. |

Within each patient, rows are sorted by tier number, then by decreasing `T_score`, and then by decreasing `N_score`.

## Requirements

Recommended Python version: **Python 3.9–3.12**.

Create an isolated environment and install the pinned dependencies:

```bash
git clone https://github.com/fcgportal/TCSI.git
cd TCSI

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

The `openai` package is required because the current script imports `AzureOpenAI` when it starts, including when `--no-enrich` is selected.

## Default run: Azure OpenAI `gpt-4o`

Configure the Azure OpenAI credentials before running the default workflow:

```bash
export AZURE_OPENAI_API_KEY="YOUR_KEY"
export AZURE_OPENAI_ENDPOINT="https://YOUR-RESOURCE-NAME.openai.azure.com/"
export AZURE_OPENAI_API_VERSION="2025-01-01-preview"
```

Run the target-prioritization workflow with the `gpt-4o` Azure deployment:

```bash
mkdir -p results

python prioritize_adc_targets.final.py \
  --clinical data/clinical_targets.csv \
  --expression data/patient_scores.csv \
  --output results/TCSI_prioritized_targets.csv \
  --azure-deployment gpt-4o
```

The script already uses `gpt-4o` as the default value of `--azure-deployment`, so the following command is equivalent:

```bash
python prioritize_adc_targets.final.py \
  --clinical data/clinical_targets.csv \
  --expression data/patient_scores.csv \
  --output results/TCSI_prioritized_targets.csv
```

`--azure-deployment` must match the deployment name configured in the Azure OpenAI resource. A deployment named `gpt-4o` must therefore exist in that resource.

The current script requires `--clinical`, `--expression`, and `--output`; consequently, the abbreviated command below is not sufficient by itself:

```bash
python prioritize_adc_targets.final.py --azure-deployment gpt-4o
```

To make that abbreviated command executable, the Python argument parser would need default paths for all three required file arguments.

### Optional sampling temperature

The default temperature is `0.3`. It can be supplied explicitly:

```bash
python prioritize_adc_targets.final.py \
  --clinical data/clinical_targets.csv \
  --expression data/patient_scores.csv \
  --output results/TCSI_prioritized_targets.csv \
  --azure-deployment gpt-4o \
  --temperature 0.3
```

Do not place API keys, endpoints containing credentials, or other secrets in source control. Azure-generated literature summaries should be independently checked against authoritative trial registries and publications before scientific or clinical interpretation.

## Deterministic run without Azure enrichment

To reproduce only the clinical-stage normalization, tier assignments, rationales, and sorting without external API calls:

```bash
mkdir -p results

python prioritize_adc_targets.final.py \
  --clinical data/clinical_targets.csv \
  --expression data/patient_scores.csv \
  --output results/TCSI_prioritized_targets.no_enrich.csv \
  --no-enrich
```

With `--no-enrich`, the `Literature Summary` column is left blank.

When the output filename ends in `.txt`, the script writes a tab-delimited file. Other filename extensions are written as comma-separated files.

## Input formats

### `data/clinical_targets.csv`

Required or automatically detected fields:

| Column | Description |
|---|---|
| `Gene` | Gene symbol or target identifier used to join the two input tables. |
| `Highest Stage` | Approval or clinical-development stage, such as `Approval`, `3`, `2/3`, `2`, `1/2`, or `1`. |
| `Approval cancer types` | Cancer types for which an approved target is indicated. |

Example:

```csv
Gene,Highest Stage,Approval cancer types
FOLR1,Approval,"FRα-positive, platinum-resistant ovarian cancer"
ERBB2,Approval,"HER2-positive solid tumors; pancancer"
ERBB3,2,
CLDN18,3,
```

The reader attempts to infer the delimiter and tolerates modest differences in capitalization and column naming. A gene column is required.

### `data/patient_scores.csv`

This file must use a **two-row header**. Each patient identifier appears twice in the first header row, with `N_score` and `T_score` in the second header row:

```csv
,Patient_001,Patient_001,Patient_002,Patient_002
Gene,N_score,T_score,N_score,T_score
FOLR1,0,0.000,1,0.095
ERBB2,1,0.182,0,0.000
```

Requirements:

- The first column contains gene identifiers.
- Each patient has one `N_score` column and one `T_score` column.
- `T_score` values must be numeric or blank.
- `N_score` accepts numeric values and common pass-like values such as `1`, `true`, `yes`, `y`, or `pass`.

## Output

The output contains one row per patient–gene pair:

| Column | Description |
|---|---|
| `Patient_ID` | Patient or sample identifier from the first header row of the score matrix. |
| `Gene` | Target gene. |
| `Clinical Stage` | Normalized clinical-stage category. |
| `N_score` | Parsed normal-tissue score/pass indicator. |
| `T_score` | Numeric tumor-expression score. |
| `Tier` | Assigned priority tier or `Unranked`. |
| `Rationale` | Rule that generated the tier assignment. |
| `Literature Summary` | Azure OpenAI-generated text for Tier 1 and Tier 2 targets; blank with `--no-enrich`. |


## Research-use statement

This software is provided for research and reproducibility purposes. It is not a validated clinical decision-support system and must not be used by itself to select treatment or make patient-care decisions. Target rankings require biological, clinical, and regulatory interpretation.


## License and data notice

Original source code and documentation are released under the [MIT License](LICENSE).

The MIT license does not override the terms governing third-party or source datasets. Users are responsible for complying with the applicable data-access, attribution, privacy, and redistribution requirements for all input data.
