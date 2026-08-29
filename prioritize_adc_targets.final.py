#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import pandas as pd
import numpy as np
from copy import deepcopy
from typing import Tuple

# ------------------- Azure OpenAI Client Setup -------------------

try:
    from openai import AzureOpenAI
except ImportError:
    print("You must install the openai package to enable Azure OpenAI functionality.")
    print("Run: pip install openai")
    sys.exit(1)

_AZURE_CLIENT = None  # global client cache


def get_azure_client() -> AzureOpenAI:
    """
    Lazily initialize and return a global AzureOpenAI client.

    Requires:
      AZURE_OPENAI_API_KEY
      AZURE_OPENAI_ENDPOINT
    Optional:
      AZURE_OPENAI_API_VERSION
    """
    global _AZURE_CLIENT
    if _AZURE_CLIENT is not None:
        return _AZURE_CLIENT

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

    if not api_key or not endpoint:
        raise RuntimeError(
            "Azure OpenAI environment variables not set. Please set:\n"
            "  AZURE_OPENAI_API_KEY\n"
            "  AZURE_OPENAI_ENDPOINT (e.g. https://YOUR-RESOURCE-NAME.openai.azure.com/)\n"
            "Optionally:\n"
            "  AZURE_OPENAI_API_VERSION (default: 2025-01-01-preview)"
        )

    _AZURE_CLIENT = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )
    return _AZURE_CLIENT


# ------------------- GPT / Chat Function -------------------

def query_chatgpt(prompt: str, deployment: str = "gpt-4o", temperature: float = 0.3) -> str:
    """
    Query Azure OpenAI Chat Completions API.

    Parameters
    ----------
    prompt : str
        User prompt text.
    deployment : str
        Azure OpenAI deployment name (NOT the bare model name).
        Example: "gpt-4o-mini", "gpt-4o", etc.
    temperature : float
        Sampling temperature.

    Returns
    -------
    str
        The assistant's reply, or an error message string.
    """
    client = get_azure_client()

    try:
        response = client.chat.completions.create(
            model=deployment,  # deployment name
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Azure ChatGPT API Error] {e}"


# ------------------- Utilities -------------------

def read_table_maybe_header(path: str, encoding: str = "ISO-8859-1") -> pd.DataFrame:
    """
    Read a delimited file (CSV/TSV/etc.) and try to infer whether the first
    row is a header if the initial header row looks suspicious.
    """
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding=encoding, dtype=str)
    except Exception:
        df = pd.read_csv(path, dtype=str, encoding=encoding)

    df = df.fillna("")
    col_blank_or_numeric = sum(
        1 for c in df.columns if (str(c).strip() == "" or str(c).strip().isdigit())
    )

    # If many column names are blank or numeric, maybe first row is the real header
    if len(df) > 1 and col_blank_or_numeric > len(df.columns) // 3:
        first = df.iloc[0].astype(str).tolist()
        if any(("gene" in v.lower() or "stage" in v.lower() or "score" in v.lower()) for v in first):
            df.columns = first
            df = df.drop(index=0).reset_index(drop=True)

    df.columns = [str(c).strip() for c in df.columns]
    return df


def interpret_n_score(x):
    if pd.isna(x) or x == "":
        return np.nan
    s = str(x).strip().lower()
    if s in ("1", "1.0", "true", "yes", "y", "pass"):
        return 1
    try:
        return int(float(s))
    except Exception:
        return np.nan


def normalize_clinical_stage(val: str, approval_cancertypes: str = "") -> str:
    if pd.isna(val) or str(val).strip() == "":
        return ""
    v = str(val).strip().lower()
    approval = str(approval_cancertypes).lower() if approval_cancertypes else ""

    if v in {"approval", "approved", "fda", "fda-approved", "fda approved"}:
        if "colon" in approval or "pancancer" in approval or "pan-cancer" in approval:
            return "fda-approved (colon cancer)"
        return "fda-approved (non-colon cancer)"

    if "phase" in v:
        if "3" in v:
            stage = "3"
        elif "2" in v:
            stage = "2"
        elif "1" in v:
            stage = "1"
        else:
            stage = v
    else:
        if v in {"3", "2", "2/3" ,"1", "1/2"}:
            stage = v
        else:
            stage = v

    if "colon" in approval or "pancancer" in approval or "pan-cancer" in approval:
        return "fda-approved (colon cancer)"
    if stage in ("3","2/3"):
        return "late-stage"
    if stage == "2":
        return "early-stage"
    if stage in ("1", "1/2"):
        return "early-stage"
    return stage


def assign_tiers_vectorized(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign prioritization tiers based on clinical stage and expression scores.
    """
    out = df.copy()
    out["Tier"] = "Unranked"
    out["Rationale"] = ""

    t0_mask = out["T_score"].notna() & (out["T_score"] > 0)
    t50_mask = out["T_score"].notna() & (out["T_score"] >= 0.5)
    n_pass_mask = out["N_score"].notna() & (out["N_score"] == 1)

    # Tier 1 & 2: FDA-approved
    m1 = out["Clinical Stage"] == "fda-approved (colon cancer)"
    out.loc[m1 & t0_mask, ["Tier", "Rationale"]] = [
        "Tier 1",
        "FDA-approved in colon cancer; detectable expression",
    ]

    m2 = out["Clinical Stage"] == "fda-approved (non-colon cancer)"
    out.loc[m2 & t0_mask, ["Tier", "Rationale"]] = [
        "Tier 2",
        "FDA-approved in other cancers; detectable expression",
    ]

    # Late-stage
    mlate = out["Clinical Stage"] == "late-stage"
    out.loc[mlate & t50_mask, ["Tier", "Rationale"]] = [
        "Tier 3",
        "Late-stage; robust tumor expression",
    ]
    out.loc[mlate & ~t50_mask & t0_mask, ["Tier", "Rationale"]] = [
        "Tier 6",
        "Late-stage; detectable expression",
    ]
    out.loc[mlate & ~t0_mask & n_pass_mask, ["Tier", "Rationale"]] = [
        "Tier 8",
        "Late-stage; no T-score but passes N-score",
    ]

    # Early-stage
    mearly = out["Clinical Stage"] == "early-stage"
    out.loc[mearly & t50_mask, ["Tier", "Rationale"]] = [
        "Tier 4",
        "Early-stage; robust tumor expression",
    ]
    out.loc[mearly & ~t50_mask & t0_mask, ["Tier", "Rationale"]] = [
        "Tier 7",
        "Early-stage; detectable expression",
    ]
    out.loc[mearly & ~t0_mask & n_pass_mask, ["Tier", "Rationale"]] = [
        "Tier 9",
        "Early-stage; no T-score but passes N-score",
    ]

    # Tier 5: FDA-approved with N-score pass but not yet ranked above
    m_fda_any = out["Clinical Stage"].astype(str).str.startswith("fda-approved")
    out.loc[m_fda_any & n_pass_mask & (out["Tier"] == "Unranked"), ["Tier", "Rationale"]] = [
        "Tier 5",
        "FDA-approved in some cancer; passes N-score",
    ]

    out.loc[out["Tier"] == "Unranked", "Rationale"] = (
        "Does not meet clinical or expression threshold"
    )
    return out


# ------------------- NEW: Multi-patient Table 2 reader -------------------

def read_expr_multi_patient(expr_path: str, encoding: str = "ISO-8859-1") -> pd.DataFrame:
    """
    Read Table 2 with 2-row header:
      header row 1: patient IDs repeated
      header row 2: N_score / T_score
      first column: Gene

    Returns long dataframe:
      Gene | Patient_ID | N_score | T_score
    """
    raw = pd.read_csv(
        expr_path,
        sep=None,
        engine="python",
        encoding=encoding,
        header=[0, 1],
        dtype=str
    ).fillna("")

    # Gene is ALWAYS the first column by position
    gene = raw.iloc[:, 0].astype(str).str.strip()

    # Score columns are everything else (MultiIndex tuples)
    score_df = raw.iloc[:, 1:]
    cols = list(score_df.columns)

    rows = []
    for col in cols:
        # Expect tuple: (patient_id, score_type)
        if not isinstance(col, tuple) or len(col) != 2:
            continue

        pid, score_type = col
        pid = str(pid).strip()
        score_type = str(score_type).strip()

        if score_type not in ("N_score", "T_score"):
            continue

        tmp = pd.DataFrame({
            "Gene": gene,
            "Patient_ID": pid,
            score_type: score_df[col].astype(str).replace({"": np.nan})
        })
        rows.append(tmp)

    if not rows:
        raise ValueError(
            "Could not parse Table 2 as (patient_id, N_score/T_score) MultiIndex columns. "
            "Please check the first two header rows."
        )

    long_df = pd.concat(rows, ignore_index=True)

    # pivot to one row per (Gene, Patient_ID)
    long_df = long_df.pivot_table(
        index=["Gene", "Patient_ID"],
        values=["N_score", "T_score"],
        aggfunc="first"
    ).reset_index()

    # Coerce types
    long_df["T_score"] = pd.to_numeric(long_df["T_score"], errors="coerce")
    long_df["N_score"] = long_df["N_score"].apply(interpret_n_score)

    return long_df[["Gene", "Patient_ID", "N_score", "T_score"]]


# ------------------- Main: Multi-patient prioritization -> ONE file -------------------

def prioritize_adc_targets_multi_patient_single_file(
    clinical_path: str,
    expr_path: str,
    out_path: str,
    azure_deployment: str = "gpt-4o",
    temperature: float = 0.3,
    enrich: bool = True,
) -> pd.DataFrame:
    """
    Multi-patient ADC target prioritization (Table 2 wide format) and write ONE output file.

    Output columns:
      Patient_ID, Gene, Clinical Stage, N_score, T_score, Tier, Rationale, Literature Summary

    If out_path ends with .txt -> tab-separated, else CSV.
    """
    # ---- Table 1 ----
    clinical_df = read_table_maybe_header(clinical_path)
    cols_lower = {c.lower(): c for c in clinical_df.columns}

    gene_col = cols_lower.get("gene") or next((c for c in clinical_df.columns if "gene" in c.lower()), None)
    stage_col = cols_lower.get("highest stage") or next((c for c in clinical_df.columns if "stage" in c.lower()), None)
    approval_col = cols_lower.get("approval cancer types") or next((c for c in clinical_df.columns if "approval" in c.lower()), None)

    if gene_col is None:
        raise ValueError("Could not find a 'Gene' column in Table 1.")
    if stage_col is None:
        # allow missing stage, but results will be less meaningful
        stage_col = ""

    clinical = clinical_df.rename(columns={gene_col: "Gene"})
    clinical["Gene"] = clinical["Gene"].astype(str).str.strip()
    clinical["Highest Stage"] = clinical_df[stage_col] if stage_col else ""
    clinical["Approved Cancer Types"] = clinical_df[approval_col] if approval_col else ""

    clinical["Clinical Stage"] = clinical.apply(
        lambda r: normalize_clinical_stage(r["Highest Stage"], r["Approved Cancer Types"]),
        axis=1,
    )

    # ---- Table 2 (multi-patient) ----
    expr_long = read_expr_multi_patient(expr_path)

    all_results = []

    for pid, expr_pid in expr_long.groupby("Patient_ID"):
        merged = pd.merge(
            clinical,
            expr_pid[["Gene", "N_score", "T_score"]],
            on="Gene",
            how="outer",
        )

        merged = assign_tiers_vectorized(merged)

        tier_order = {f"Tier {i}": i for i in range(1, 10)}
        merged["Tier_Rank"] = merged["Tier"].map(tier_order).fillna(9999).astype(int)

        prioritized = merged.copy()
        prioritized = prioritized.sort_values(
            by=["Tier_Rank", "T_score", "N_score"],
            ascending=[True, False, False],
        )

        # ---- Optional Azure enrichment for Tier 1–2 ----
        summaries = []
        for _, row in prioritized.iterrows():
            if enrich and row["Tier"] in ("Tier 1", "Tier 2"):
                gene = row["Gene"]
                prompt = (
                    f"List ONLY the most relevant and recent clinical trials and key publications "
                    f"related to antibody–drug conjugates (ADCs) targeting {gene} in colon cancer.\n\n"
                    f"FORMAT REQUIREMENTS:\n"
                    f"- Use bullet points only\n"
                    f"- For trials: \"Trial: <Name or NCT ID> — <year> — <reference>\"\n"
                    f"- For publications: \"Publication: <Title> — <journal, year>\"\n"
                    f"- No paragraphs, no explanations.\n"
                    f"- Keep each bullet short.\n"
                )
                print(f"🔎 {pid}: querying literature for {gene}...")
                summary = query_chatgpt(prompt, deployment=azure_deployment, temperature=temperature)
            else:
                summary = ""
            summaries.append(summary)

        prioritized["Literature Summary"] = summaries
        prioritized["Patient_ID"] = pid

        out_cols = [
            "Patient_ID",
            "Gene",
            "Clinical Stage",
            "N_score",
            "T_score",
            "Tier",
            "Rationale",
            "Literature Summary",
        ]
        all_results.append(prioritized[out_cols])

    final_df = pd.concat(all_results, ignore_index=True)

    if out_path.lower().endswith(".txt"):
        final_df.to_csv(out_path, sep="\t", index=False,encoding="utf-8-sig")
    else:
        final_df.to_csv(out_path, index=False,encoding="utf-8-sig")

    print(f"✅ Multi-patient results written to: {out_path}")
    return final_df


# ------------------- CLI -------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ADC Target Prioritization (Multi-patient Table 2) + optional Azure OpenAI literature enrichment"
    )
    parser.add_argument("--clinical", required=True, help="Path to clinical stage file (Table 1)")
    parser.add_argument("--expression", required=True, help="Path to expression file (Table 2; multi-patient wide format)")
    parser.add_argument("--output", required=True, help="Path to output file (.csv or .txt)")
    parser.add_argument(
        "--azure-deployment",
        required=False,
        default="gpt-4o",
        help="Azure OpenAI deployment name to use for chat completions (default: gpt-4o)",
    )
    parser.add_argument(
        "--temperature",
        required=False,
        type=float,
        default=0.3,
        help="Chat completion temperature (default: 0.3)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Disable Azure OpenAI literature enrichment (Tier 1–2).",
    )

    args = parser.parse_args()

    prioritize_adc_targets_multi_patient_single_file(
        clinical_path=args.clinical,
        expr_path=args.expression,
        out_path=args.output,
        azure_deployment=args.azure_deployment,
        temperature=args.temperature,
        enrich=(not args.no_enrich),
    )
