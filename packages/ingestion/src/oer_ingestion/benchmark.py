"""Combined-MCP benchmark (D9, PRD §13).

Measures whether grounding lesson-plan generation in retrieved OER content
produces measurably better plans. For each topic, a lesson plan is generated
three ways — context differs, generator is held constant so the delta isolates
the value of the retrieved context:

  none           topic only
  standardgraph  topic + standard text (StandardGraph DB)
  both           topic + standard text + OER content (fetch_for_standard)

A judge model then scores every plan BLIND to condition on three 1–5 rubric
dimensions. Target: `both` beats `standardgraph` by ≥1.0 on content_accuracy.

Generator and judge both run via Ollama (configurable). Using one local model
for both is a relative measure — the generator cancels across conditions; only
the injected context varies. Build-time eval; never runs at query time.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from oer_shared import config

# 20 math topics spanning K-12, each anchored to a StandardGraph standard id
# (SG omits cluster letters for K-8; HS standards keep them).
TOPICS: list[tuple[str, str]] = [
    ("Counting objects to 10", "CCSS.MATH.K.CC.5"),
    ("Understanding the equal sign", "CCSS.MATH.1.OA.D.7"),
    ("Partitioning shapes into halves and fourths", "CCSS.MATH.2.G.A.3"),
    ("Understanding a fraction as a number on the number line", "CCSS.MATH.3.NF.2"),
    ("Place value: a digit is ten times the place to its right", "CCSS.MATH.4.NBT.A.1"),
    ("Dividing unit fractions by whole numbers", "CCSS.MATH.5.NF.B.7"),
    ("Ratio and rate reasoning to solve problems", "CCSS.MATH.6.RP.3"),
    ("Dividing fractions by fractions", "CCSS.MATH.6.NS.1"),
    ("Positive and negative integers on the number line", "CCSS.MATH.6.NS.5"),
    ("Adding and subtracting rational numbers", "CCSS.MATH.7.NS.1"),
    ("Solving two-step linear equations", "CCSS.MATH.7.EE.4"),
    ("Properties of integer exponents", "CCSS.MATH.8.EE.1"),
    ("Understanding functions as inputs and outputs", "CCSS.MATH.8.F.1"),
    ("Solving systems of linear inequalities by graphing", "CCSS.MATH.HSA.REI.D.12"),
    ("Average rate of change of a function", "CCSS.MATH.HSF.IF.B.6"),
    ("Rewriting expressions with rational exponents and radicals", "CCSS.MATH.HSN.RN.A.2"),
    ("Representing data with dot plots, histograms, and box plots", "CCSS.MATH.HSS.ID.1"),
    ("Deriving the equation of a circle", "CCSS.MATH.HSG.GPE.A.1"),
    ("Multiplying multi-digit whole numbers", "CCSS.MATH.5.NBT.B.5"),
    ("Solving real-world problems with percentages", "CCSS.MATH.7.RP.3"),
]

CONDITIONS = ("none", "standardgraph", "both")
DIMENSIONS = ("standards_accuracy", "content_accuracy", "pedagogical_coherence")

GEN_PROMPT = """Write a concise math lesson plan (objective, 2-3 worked teaching
steps, and one practice problem) for this topic:

Topic: {topic}
{context}
Return only the lesson plan."""

JUDGE_PROMPT = """You are grading a math lesson plan. Score it 1-5 (5=best) on:
- standards_accuracy: alignment to the stated standard's intent
- content_accuracy: mathematical correctness and appropriate examples
- pedagogical_coherence: logical teaching sequence, clear and grade-appropriate

Topic: {topic}
Standard: {standard_id}

Lesson plan:
{plan}

Return ONLY a JSON object: {{"standards_accuracy": N, "content_accuracy": N, "pedagogical_coherence": N}}"""


@dataclass
class Plan:
    topic: str
    standard_id: str
    condition: str
    text: str
    scores: dict[str, int] = field(default_factory=dict)


def _sg_context(sg: sqlite3.Connection, standard_id: str) -> str:
    row = sg.execute(
        "SELECT standard_text FROM standards WHERE id=? AND system='ccss'",
        (standard_id,),
    ).fetchone()
    if not row:
        return ""
    subs = sg.execute(
        "SELECT text FROM sub_standards WHERE parent_id=? ORDER BY position",
        (standard_id,),
    ).fetchall()
    out = f"Standard {standard_id}: {row[0]}"
    if subs:
        out += "\nSub-standards: " + "; ".join(s[0] for s in subs)
    return out


def _oer_context(oer_conn, standard_id: str, queries) -> str:
    res = queries.fetch_for_standard(oer_conn, standard_id, limit=2, include_content=True)
    if isinstance(res, dict):  # no_content
        return ""
    parts = []
    for r in res:
        parts.append(f"From {r['attribution']}:\n{(r['content'] or '')[:900]}")
    return "Reference content:\n" + "\n\n".join(parts) if parts else ""


def _build_context(condition, standard_id, sg, oer_conn, queries) -> str:
    if condition == "none":
        return ""
    sg_ctx = _sg_context(sg, standard_id)
    if condition == "standardgraph":
        return sg_ctx
    return (sg_ctx + "\n\n" + _oer_context(oer_conn, standard_id, queries)).strip()


def _ollama(model, prompt, client, *, temperature=0.2) -> str:
    resp = client.post(
        f"{config.OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False,
              "options": {"temperature": temperature}},
        timeout=600.0,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def parse_scores(text: str) -> dict[str, int]:
    """Lenient extraction of the three rubric scores from judge output."""
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            return {k: int(d[k]) for k in DIMENSIONS if k in d}
    except (ValueError, KeyError, TypeError):
        pass
    # fallback: find "dimension: N" patterns
    out = {}
    for dim in DIMENSIONS:
        m = re.search(rf"{dim}\D{{0,5}}([1-5])", text, re.IGNORECASE)
        if m:
            out[dim] = int(m.group(1))
    return out


def run_benchmark(
    oer_db: str | Path, sg_db: str | Path, *,
    gen_model: str | None = None, judge_model: str | None = None,
    addon_db: str | Path | None = None, topics=None, seed: int = 0,
) -> dict:
    from oer_server import queries  # local import; server pkg
    from oer_shared.db import connect

    gen_model = gen_model or config.ANNOTATE_MODEL
    judge_model = judge_model or config.ANNOTATE_MODEL
    topics = topics or TOPICS
    sg = sqlite3.connect(f"file:{sg_db}?mode=ro", uri=True)
    oer_conn = connect(oer_db, addon_db)

    plans: list[Plan] = []
    with httpx.Client() as client:
        for topic, sid in topics:
            for cond in CONDITIONS:
                ctx = _build_context(cond, sid, sg, oer_conn, queries)
                text = _ollama(gen_model,
                               GEN_PROMPT.format(topic=topic, context=ctx), client)
                plans.append(Plan(topic, sid, cond, text))

        # judge blind: shuffle so order leaks nothing about condition
        order = list(range(len(plans)))
        random.Random(seed).shuffle(order)
        for i in order:
            p = plans[i]
            verdict = _ollama(judge_model,
                              JUDGE_PROMPT.format(topic=p.topic, standard_id=p.standard_id,
                                                  plan=p.text), client, temperature=0)
            p.scores = parse_scores(verdict)

    sg.close()
    oer_conn.close()
    return _aggregate(plans)


def _aggregate(plans: list[Plan]) -> dict:
    means = {c: {d: 0.0 for d in DIMENSIONS} for c in CONDITIONS}
    counts = {c: 0 for c in CONDITIONS}
    for p in plans:
        if not p.scores:
            continue
        counts[p.condition] += 1
        for d in DIMENSIONS:
            means[p.condition][d] += p.scores.get(d, 0)
    for c in CONDITIONS:
        if counts[c]:
            for d in DIMENSIONS:
                means[c][d] /= counts[c]
    lift = (means["both"]["content_accuracy"]
            - means["standardgraph"]["content_accuracy"])
    return {
        "n_topics": len(plans) // len(CONDITIONS),
        "scored": counts,
        "means": means,
        "content_accuracy_lift_both_vs_sg": round(lift, 3),
        "target_met": lift >= 1.0,
        "plans": [vars(p) for p in plans],
    }


def print_report(result: dict) -> None:
    print(f"\nCombined-MCP benchmark — {result['n_topics']} topics\n")
    hdr = f"{'condition':<14}" + "".join(f"{d[:16]:>18}" for d in DIMENSIONS)
    print(hdr)
    for c in CONDITIONS:
        row = f"{c:<14}" + "".join(f"{result['means'][c][d]:>18.2f}" for d in DIMENSIONS)
        print(row)
    print(f"\ncontent_accuracy lift (both - standardgraph): "
          f"{result['content_accuracy_lift_both_vs_sg']:+.2f}  "
          f"(target ≥ +1.0 → {'MET' if result['target_met'] else 'not met'})")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Combined-MCP benchmark (D9)")
    p.add_argument("--db", default=str(config.CORE_DB_PATH))
    p.add_argument("--addon-db", default=None)
    p.add_argument("--sg-db", default=str(config.STANDARDGRAPH_DB_PATH))
    p.add_argument("--gen-model", default=None)
    p.add_argument("--judge-model", default=None)
    p.add_argument("--topics", type=int, default=None, help="cap topic count (smoke test)")
    p.add_argument("--out", default=None, help="write full JSON result here")
    args = p.parse_args()

    topics = TOPICS[: args.topics] if args.topics else TOPICS
    result = run_benchmark(
        args.db, args.sg_db, gen_model=args.gen_model, judge_model=args.judge_model,
        addon_db=args.addon_db, topics=topics,
    )
    print_report(result)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"\nfull result → {args.out}")


if __name__ == "__main__":
    main()
