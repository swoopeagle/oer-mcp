# Benchmark Investigation — Root Cause Analysis

**Status:** `content_accuracy_lift_both_vs_sg = 0.0` (target: not met)

## Problem Statement
The benchmark's `both` condition (OER + StandardGraph) does not lift content_accuracy above StandardGraph alone. Both score 5.0/5.0 with zero lift.

## Root Causes Identified

### 1. **Measurement Blindness (Primary Issue)**
The JUDGE_PROMPT (line 70–84 in `benchmark.py`) is **blind to the OER context**:

```python
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
```

**The judge sees:**
- Only the generated segments (A and B)
- The standard definition
- NOT the OER context that was fed to the generator

**Result:**
- The judge cannot verify whether OER materials were actually incorporated into the generation
- Even if `both` condition uses OER content, the judge can't tell the difference
- It's evaluating "fidelity to real curriculum" in the abstract, not comparing against actual provided curriculum materials

### 2. **Weak Generator Instructions**
The GEN_PROMPT (line 61–68) says "use... specific methods, notation, example types that real curriculum materials use" but:
- Does not mandate incorporation of the provided OER content
- Does not ask the generator to cite or explicitly use provided examples
- The instruction is suggestive, not prescriptive
- qwen2.5:72b may be ignoring the OER context and generating generic content

### 3. **Ceiling Effect in Judge Scoring**
All 20 topics × 3 conditions receive `content_accuracy: 5.0`. This suggests:
- The 1–5 rubric is too coarse and saturates (not enough discrimination between conditions)
- The judge may be scoring "is this reasonable?" rather than "is this grounded in the provided materials?"
- The benchmark doesn't reward content that actually uses the OER materials

### 4. **Data Completeness Unknown (Secondary Issue)**
- Local dev DB (`data/oer_core.db`) does not exist
- Cannot verify that OER alignments exist for the 20 benchmark topics
- If alignments are missing, `_oer_context()` returns empty string, making `both` ≡ `standardgraph`
- Bench.json shows complete results, implying the benchmark was run on a mini with the full DB

## Impact
**Product Impact:** Cannot measure whether OER content actually improves generated curriculum materials. The benchmark is not fit for purpose.

## Recommended Fixes

### Fix 1: Make Judge Aware of OER Context (Priority: HIGH)
Modify the benchmark to pass the provided OER context to the judge:

```python
JUDGE_PROMPT = """Two teaching segments (A and B) cover the same math topic, generated
with different amounts of reference material.

Topic: {topic}
Standard {standard_id}: {standard_text}

Reference materials available to generator for version B (if any):
{reference_materials}

--- Segment A (generated with standard definition only) ---
{a}

--- Segment B (generated with standard definition + reference materials) ---
{b}

Which segment is more faithful to the reference materials and real curriculum practice?
Reply with exactly one token: A, B, or TIE."""
```

This lets the judge verify whether segment B actually incorporates the provided materials.

### Fix 2: Strengthen Generator Instructions (Priority: MEDIUM)
Update GEN_PROMPT to explicitly require use of provided content:

```python
GEN_PROMPT = """Produce a short teaching segment for this math topic: a one-line
objective, TWO worked examples with step-by-step solutions, and one practice
problem.

Topic: {topic}
{context}

IMPORTANT: If reference content is provided, use the specific methods, notation,
and example types shown in those materials. Your examples should be grounded in
the provided curriculum, not generic. Return only the teaching segment."""
```

### Fix 3: Use Pairwise Ranking (Already Implemented)
The benchmark is already using pairwise comparison (`both` vs `standardgraph` vs `none`), which is better than absolute scores. But the judge still needs visibility into the materials to make informed comparisons.

## Next Steps
1. **Immediately:** Fix the judge prompt to include OER context (enables actual measurement)
2. **Follow-up:** Strengthen generator instructions
3. **Validation:** Re-run benchmark on mini with full DB; target: `both` should prefer over `standardgraph` in ≥60% of comparisons
4. **If still failing:** Investigate whether OER content is high-fidelity enough to teach the benchmarked standards

## Notes
- The benchmark is well-structured (pairwise, deterministic checks, local LLM judge)
- The DB ingestion pipeline and alignment logic appear sound
- The measurement design is the core blocker, not the data or infrastructure
