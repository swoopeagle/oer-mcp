"""Combined-MCP benchmark (D9, PRD §13) — pairwise preference design.

An earlier absolute 1-5 rubric saturated (a weak local judge scored ~everything
5/5, so no lift was measurable). This version fixes both failure modes:

  * Pairwise judging — the judge sees two segments for the same topic and must
    pick the better-grounded one (A / B / TIE), which beats the ceiling effect.
  * Grounding-stressing task — generate worked examples (not a generic plan),
    and judge on fidelity to how the standard is *actually* taught, so the value
    of real OER content can show. Generic "is it correct" doesn't need grounding;
    "does it match real curriculum examples/methods" does.

Each topic is generated three ways (none / standardgraph / both); the generator
is held constant so the comparison isolates the injected context. Headline
metric: how often `both` is preferred over `standardgraph` (and over `none`),
blind and order-randomized. Target: `both` preferred over `standardgraph` in
≥60% of decisive comparisons. Build-time eval; never runs at query time.
"""

from __future__ import annotations

import json
import random
import re
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
# Comparisons whose preference we tally (the headline is both-vs-standardgraph).
PAIRS = (("both", "standardgraph"), ("both", "none"), ("standardgraph", "none"))

GEN_PROMPT = """Produce a short teaching segment for this math topic: a one-line
objective, TWO worked examples with step-by-step solutions, and one practice
problem. Use the specific methods, notation, and example types that real
curriculum materials use for this topic.

Topic: {topic}
{context}
Return only the teaching segment."""

JUDGE_PROMPT = """Two teaching segments (A and B) cover the same math topic.
Decide which one is more faithful to how this standard is ACTUALLY taught in real
curriculum materials — concrete and correct worked examples, standard methods and
notation, grade-appropriate. Judge fidelity and usefulness, not length.

Topic: {topic}
Standard {standard_id}: {standard_text}

--- Segment A ---
{a}

--- Segment B ---
{b}

Reply with exactly one token: A, B, or TIE."""


@dataclass
class Plan:
    topic: str
    standard_id: str
    condition: str
    text: str


@dataclass
class Comparison:
    topic: str
    standard_id: str
    left: str   # condition shown as "A"
    right: str  # condition shown as "B"
    winner: str | None = None  # condition that won, or "tie", or None (unparsed)


def _sg_context(sg, standard_id: str) -> str:
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


def _standard_text(sg, standard_id: str) -> str:
    row = sg.execute(
        "SELECT standard_text FROM standards WHERE id=? AND system='ccss'",
        (standard_id,),
    ).fetchone()
    return row[0] if row else ""


def _oer_context(oer_conn, standard_id: str, queries) -> str:
    res = queries.fetch_for_standard(oer_conn, standard_id, limit=2, include_content=True)
    if isinstance(res, dict):  # no_content
        return ""
    parts = [f"From {r['attribution']}:\n{(r['content'] or '')[:900]}" for r in res]
    return "Reference content (use these example types and methods):\n" + "\n\n".join(parts) if parts else ""


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
        timeout=300.0,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def parse_pref(text: str) -> str | None:
    """Extract A / B / TIE from a judge response; None if unparseable.
    Prefer the first token (the judge is told to reply with one), then fall back
    to TIE anywhere, then a standalone A/B."""
    t = text.strip().upper()
    tokens = re.findall(r"[A-Z]+", t)
    if tokens and tokens[0] in ("A", "B", "TIE"):
        return tokens[0]
    if re.search(r"\bTIE\b", t):
        return "TIE"
    m = re.search(r"\b([AB])\b", t)
    return m.group(1) if m else None


def run_benchmark(
    oer_db: str | Path, sg_db: str | Path, *,
    gen_model: str | None = None, judge_model: str | None = None,
    addon_db: str | Path | None = None, topics=None, seed: int = 0,
) -> dict:
    import sqlite3

    from oer_server import queries
    from oer_shared.db import connect

    gen_model = gen_model or config.ANNOTATE_MODEL
    judge_model = judge_model or config.ANNOTATE_MODEL
    topics = topics or TOPICS
    rng = random.Random(seed)
    sg = sqlite3.connect(f"file:{sg_db}?mode=ro", uri=True)
    oer_conn = connect(oer_db, addon_db)

    comparisons: list[Comparison] = []
    with httpx.Client() as client:
        for topic, sid in topics:
            plans = {}
            for cond in CONDITIONS:
                ctx = _build_context(cond, sid, sg, oer_conn, queries)
                plans[cond] = _ollama(gen_model, GEN_PROMPT.format(topic=topic, context=ctx), client)
            stext = _standard_text(sg, sid)
            for left_cond, right_cond in PAIRS:
                # randomize which condition is shown as A vs B (blind to judge)
                a_cond, b_cond = (left_cond, right_cond) if rng.random() < 0.5 else (right_cond, left_cond)
                verdict = _ollama(
                    judge_model,
                    JUDGE_PROMPT.format(topic=topic, standard_id=sid, standard_text=stext,
                                        a=plans[a_cond], b=plans[b_cond]),
                    client, temperature=0,
                )
                pref = parse_pref(verdict)
                winner = None
                if pref == "TIE":
                    winner = "tie"
                elif pref == "A":
                    winner = a_cond
                elif pref == "B":
                    winner = b_cond
                comparisons.append(Comparison(topic, sid, a_cond, b_cond, winner))

    sg.close()
    oer_conn.close()
    return _aggregate(comparisons, len(topics))


def _aggregate(comparisons: list[Comparison], n_topics: int) -> dict:
    results = {}
    for left, right in PAIRS:
        key = f"{left}_vs_{right}"
        wins = losses = ties = unparsed = 0
        for c in comparisons:
            if {c.left, c.right} != {left, right}:
                continue
            if c.winner is None:
                unparsed += 1
            elif c.winner == "tie":
                ties += 1
            elif c.winner == left:
                wins += 1
            else:
                losses += 1
        decisive = wins + losses
        results[key] = {
            "wins": wins, "losses": losses, "ties": ties, "unparsed": unparsed,
            "win_rate": round(wins / decisive, 3) if decisive else None,
        }
    headline = results["both_vs_standardgraph"]["win_rate"]
    return {
        "n_topics": n_topics,
        "comparisons": results,
        "both_vs_standardgraph_win_rate": headline,
        "target_met": headline is not None and headline >= 0.60,
        "raw": [vars(c) for c in comparisons],
    }


def print_report(result: dict) -> None:
    print(f"\nCombined-MCP benchmark (pairwise) — {result['n_topics']} topics\n")
    print(f"{'comparison':<28}{'win':>5}{'loss':>6}{'tie':>5}{'win_rate':>10}")
    for key, r in result["comparisons"].items():
        wr = "n/a" if r["win_rate"] is None else f"{r['win_rate']:.2f}"
        print(f"{key:<28}{r['wins']:>5}{r['losses']:>6}{r['ties']:>5}{wr:>10}")
    hr = result["both_vs_standardgraph_win_rate"]
    print(f"\nheadline — both preferred over standardgraph: "
          f"{('n/a' if hr is None else f'{hr:.0%}')} "
          f"(target ≥60% → {'MET' if result['target_met'] else 'not met'})")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Combined-MCP pairwise benchmark (D9)")
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
