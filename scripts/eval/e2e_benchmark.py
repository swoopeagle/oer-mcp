"""D9 end-to-end benchmark — local LLM agent + live MCP servers via stdio.

NOTE — there are two D9 benchmarks with different scopes; don't confuse them:
  * THIS file (scripts/eval/e2e_benchmark.py): integration-style. Spawns both MCP
    servers over stdio, drives real tool calls, and scores answers with
    deterministic checks + a YES/PARTIAL/NO judge and a head-to-head A/B compare.
    Measures whether the *wired-up system* answers curriculum questions better.
  * oer_ingestion.benchmark: a focused **pairwise content-grounding** eval. No MCP
    server; it calls the query layer directly, generates a teaching segment three
    ways (none/standardgraph/both) and asks a judge which is better grounded in
    real OER excerpts. Reports both-vs-standardgraph win-rate → bench.json.
Use this one for end-to-end/tool-calling regressions; use the other for measuring
content-grounding lift.

Headline question: does adding oer-mcp to standardgraph improve curriculum
content answers?

Spawns both MCP servers, drives real tool calls with qwen2.5:72b (or any
Ollama model with tool-calling support), scores with deterministic checks +
gemma judge. Each scenario runs twice: combined (both servers) vs SG-only,
to measure the delta.

No ANTHROPIC_API_KEY needed — 100% local inference.

Usage:
    cd /path/to/oer-mcp
    .venv/bin/python scripts/eval/e2e_benchmark.py
    .venv/bin/python scripts/eval/e2e_benchmark.py --scenario 3 --verbose
    .venv/bin/python scripts/eval/e2e_benchmark.py --no-judge
    .venv/bin/python scripts/eval/e2e_benchmark.py --list
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).parent.parent.parent
OER_PROJECT  = ROOT
SG_PROJECT   = Path(os.environ.get(
    "STANDARDGRAPH_ROOT",
    str(Path.home() / "projects" / "intl-math-standards-mcp"),
))

OER_CORE_DB = OER_PROJECT / "data" / "oer_core.db"
OER_NCSA_DB = OER_PROJECT / "data" / "oer_ncsa.db"
SG_DB       = SG_PROJECT / "data" / "common_core.db"

AGENT_URL   = os.environ.get("OER_AGENT_URL", "http://169.254.1.1:11434")
AGENT_MODEL = os.environ.get("OER_AGENT_MODEL", "qwen2.5:72b")
JUDGE_URL   = os.environ.get("OER_JUDGE_URL", "http://169.254.1.1:11434")
JUDGE_MODEL = os.environ.get("OER_JUDGE_MODEL", "gemma4:31b-it-q8_0")

MAX_TURNS   = int(os.environ.get("OER_MAX_TURNS", "12"))
AGENT_TIMEOUT = float(os.environ.get("OER_AGENT_TIMEOUT", "300"))

_OK   = "\033[32m OK \033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_PART = "\033[33mPART\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"
_DIM  = "\033[90m"
_RST  = "\033[0m"


# ── Scenarios ────────────────────────────────────────────────────────────────

SCENARIOS: list[dict[str, Any]] = [
    # ── OER-only: content retrieval ───────────────────────────────────────────
    {
        "name": "Fetch content for integer exponents",
        "prompt": (
            "What textbook content teaches integer exponents "
            "(CCSS.MATH.8.EE.1)? Show me the actual content."
        ),
        "expect_tools": ["fetch_for_standard"],
        "expect_in_answer": ["exponent"],
        "oer_advantage": True,
    },
    {
        "name": "Search: graphing equations",
        "prompt": (
            "Find a worked example or lesson from our content library that "
            "teaches graphing equations in two variables on the coordinate plane."
        ),
        "expect_tools": ["search_content"],
        "expect_in_answer": ["graph"],
        "oer_advantage": True,
    },
    {
        "name": "Coverage report: Grade 5 fractions",
        "prompt": (
            "How well do our textbook resources cover the CCSS Grade 5 "
            "fractions cluster (5.NF)? Identify any gaps."
        ),
        "expect_tools": ["check_coverage"],
        "expect_in_answer": ["5.NF"],
        "oer_advantage": True,
    },
    {
        "name": "Search: solving multi-step problems",
        "prompt": (
            "Show me an exposition or worked example from our content "
            "library that teaches solving multi-step real-life problems, "
            "suitable for 7th grade."
        ),
        "expect_tools": ["search_content"],
        "expect_in_answer": ["problem"],
        "oer_advantage": True,
    },

    # ── Combined: both servers together ───────────────────────────────────────
    {
        "name": "Lookup + fetch content (multi-tool)",
        "prompt": (
            "Look up CCSS standard 5.NF.A.1 to see what it covers, then "
            "find teaching content for it from our textbook library."
        ),
        "expect_tools": ["lookup_standard", "fetch_for_standard"],
        "expect_in_answer": ["5.NF", "fraction"],
        "expect_min_tool_calls": 2,
        "oer_advantage": True,
    },
    {
        "name": "Progression + content sample (multi-tool)",
        "prompt": (
            "Trace how fractions develop from Grade 3 to Grade 5 in CCSS, "
            "then find a specific lesson for the Grade 4 stage from our "
            "textbook content."
        ),
        "expect_tools": ["get_progression"],
        "expect_in_answer": ["3", "4", "5", "fraction"],
        "expect_min_tool_calls": 2,
        "oer_advantage": True,
    },
    {
        "name": "Gap analysis: Grade 8 expressions",
        "prompt": (
            "Search for CCSS Grade 8 expressions and equations standards, "
            "then check which ones are covered or missing in our textbook "
            "content."
        ),
        "expect_tools": ["search_standards"],
        "expect_in_answer": ["8"],
        "expect_min_tool_calls": 2,
        "oer_advantage": True,
    },

    # ── SG-only: OER should not degrade these ────────────────────────────────
    {
        "name": "TX Grade 4 multiplication (SG baseline)",
        "prompt": "What are the Grade 4 multiplication standards in Texas TEKS?",
        "expect_tools": ["search_standards"],
        "expect_in_answer": ["TX", "multiplication", "4"],
        "oer_advantage": False,
    },
    {
        "name": "SG to CCSS crosswalk (SG baseline)",
        "prompt": (
            "What is the CCSS equivalent of Singapore standard "
            "SG_MOE.MATH.7.N7.7.2?"
        ),
        "expect_tools": ["map_standard"],
        "expect_in_answer": ["CCSS", "SG_MOE"],
        "oer_advantage": False,
    },
    {
        "name": "CCSS fractions progression (SG baseline)",
        "prompt": (
            "How does the concept of fractions develop across Grade 3 "
            "to Grade 5 in CCSS?"
        ),
        "expect_tools": ["get_progression"],
        "expect_in_answer": ["3", "4", "5", "fraction"],
        "oer_advantage": False,
    },
]


# ── MCP server management ───────────────────────────────────────────────────

def _mcp_to_ollama_tool(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


async def _spawn_server(stack: AsyncExitStack, command: str, args: list[str],
                        env: dict, label: str, cwd: str | Path | None = None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
    transport = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(*transport))
    await session.initialize()
    resp = await session.list_tools()
    tools = {t.name: t for t in resp.tools}
    print(f"  [{label}] {len(tools)} tools: {', '.join(tools)}")
    return session, tools


# ── Ollama agent loop ────────────────────────────────────────────────────────

def _call_ollama(messages: list[dict], tools: list[dict],
                 url: str, model: str) -> dict:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192},
    }
    if tools:
        body["tools"] = tools
    resp = httpx.post(f"{url}/api/chat", json=body, timeout=AGENT_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


async def run_agent(prompt: str, ollama_tools: list[dict],
                    sessions: dict[str, Any], tool_to_session: dict[str, str],
                    verbose: bool = False) -> dict:
    messages = [
        {"role": "system", "content": (
            "You are a curriculum specialist with access to tools for looking up "
            "educational standards and finding teaching content. Use the available "
            "tools to answer the user's question thoroughly. When you find content, "
            "include relevant excerpts. Always cite sources. "
            "Always respond in English regardless of the content language."
        )},
        {"role": "user", "content": prompt},
    ]
    tool_calls_made: list[dict] = []
    final_answer = ""
    error = ""

    try:
        for turn in range(MAX_TURNS):
            data = _call_ollama(messages, ollama_tools, AGENT_URL, AGENT_MODEL)
            msg = data.get("message", {})

            calls = msg.get("tool_calls")
            if not calls:
                final_answer = msg.get("content", "")
                break

            messages.append(msg)

            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)

                tool_calls_made.append({"name": name, "input": args})
                if verbose:
                    print(f"       -> {name}({json.dumps(args)[:120]})")

                session_key = tool_to_session.get(name)
                if session_key and session_key in sessions:
                    mcp_result = await sessions[session_key].call_tool(name, args)
                    result_text = (
                        mcp_result.content[0].text
                        if mcp_result.content else "{}"
                    )
                else:
                    result_text = json.dumps({"error": f"unknown tool: {name}"})

                messages.append({"role": "tool", "content": result_text})

    except Exception as e:
        error = str(e)

    return {
        "tool_calls": tool_calls_made,
        "final_answer": final_answer,
        "error": error,
    }


# ── Deterministic checks ────────────────────────────────────────────────────

def _check(scenario: dict, result: dict) -> tuple[bool, str]:
    if result["error"]:
        return False, f"Error: {result['error'][:120]}"

    names = [t["name"] for t in result["tool_calls"]]
    for expected in scenario.get("expect_tools", []):
        if expected not in names:
            return False, f"Expected tool '{expected}' not called (got: {names})"

    min_calls = scenario.get("expect_min_tool_calls", 1)
    if len(result["tool_calls"]) < min_calls:
        return False, f"Expected >={min_calls} tool calls, got {len(result['tool_calls'])}"

    answer_lower = result["final_answer"].lower()
    for phrase in scenario.get("expect_in_answer", []):
        if phrase.lower() not in answer_lower:
            return False, f"Expected '{phrase}' in answer"

    return True, ""


# ── Gemma judge ──────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are evaluating whether an AI assistant gave a good answer to a user's
educational/curriculum question using standards and content databases.

User question: {prompt}

Assistant's answer:
{answer}

Does the answer satisfactorily address the user's question with specific,
relevant information (not generic filler)?
Reply ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""

_COMPARE_PROMPT = """\
Two AI assistants answered the same curriculum question. One had access to a
standards database only; the other also had access to a textbook content database.

Question: {prompt}

Answer A (standards only):
{answer_a}

Answer B (standards + content):
{answer_b}

Which answer is more helpful for a teacher preparing a lesson?
Reply ONLY: A, B, or TIE
Then one sentence explaining why.
"""


def _gemma_judge(prompt: str, answer: str) -> tuple[str, str]:
    if not answer.strip():
        return "NO", "Empty answer"
    try:
        resp = httpx.post(f"{JUDGE_URL}/api/generate", json={
            "model": JUDGE_MODEL,
            "prompt": _JUDGE_PROMPT.format(prompt=prompt, answer=answer[:2000]),
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
    except Exception as e:
        return "ERR", str(e)[:100]
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    first = lines[0].upper() if lines else ""
    reason = lines[1] if len(lines) > 1 else raw
    if first.startswith("YES"):     return "YES", reason
    if first.startswith("PARTIAL"): return "PARTIAL", reason
    if first.startswith("NO"):      return "NO", reason
    return "PARTIAL", raw[:100]


def _gemma_compare(prompt: str, answer_a: str, answer_b: str) -> tuple[str, str]:
    if not answer_a.strip() and not answer_b.strip():
        return "TIE", "Both empty"
    try:
        resp = httpx.post(f"{JUDGE_URL}/api/generate", json={
            "model": JUDGE_MODEL,
            "prompt": _COMPARE_PROMPT.format(
                prompt=prompt,
                answer_a=answer_a[:2000],
                answer_b=answer_b[:2000],
            ),
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
    except Exception as e:
        return "ERR", str(e)[:100]
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    first = lines[0].upper() if lines else ""
    reason = lines[1] if len(lines) > 1 else raw
    if first.startswith("B"):   return "B", reason
    if first.startswith("A"):   return "A", reason
    if first.startswith("TIE"): return "TIE", reason
    return "TIE", raw[:100]


# ── Main ─────────────────────────────────────────────────────────────────────

async def _run(scenario_filter: int | None, no_judge: bool,
               verbose: bool, sg_only: bool) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    base_env = {k: v for k, v in os.environ.items()}

    sg_env = {
        **base_env,
        "DB_PATH": str(SG_DB),
        "OLLAMA_BASE_URL": "http://localhost:11434",
    }
    oer_env = {
        **base_env,
        "OER_CORE_DB_PATH": str(OER_CORE_DB),
        "OER_ADDON_DB_PATH": str(OER_NCSA_DB),
        "OLLAMA_BASE_URL": "http://localhost:11434",
    }

    scenarios = SCENARIOS
    if scenario_filter is not None:
        if scenario_filter < 1 or scenario_filter > len(SCENARIOS):
            print(f"ERROR: --scenario must be 1-{len(SCENARIOS)}")
            return 1
        scenarios = [SCENARIOS[scenario_filter - 1]]

    mode = "SG-only" if sg_only else "Combined (SG + OER)"
    print(f"\n── D9 Benchmark: {mode} ────────────────────────────────────")
    print(f"  Agent: {AGENT_MODEL} @ {AGENT_URL}")
    if not no_judge:
        print(f"  Judge: {JUDGE_MODEL} @ {JUDGE_URL}")
    print(f"  SG DB: {SG_DB}")
    if not sg_only:
        print(f"  OER core: {OER_CORE_DB}")
        print(f"  OER ncsa: {OER_NCSA_DB}")
    print()

    passed = partial = failed = errors = 0
    results_log: list[dict] = []

    print(f"  {'#':<3} {'Scenario':<42} {'Tools':<18} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*42} {'-'*18} {'----':>4} {'----':>4}")

    async with AsyncExitStack() as stack:
        # Spawn StandardGraph
        sg_session, sg_tools = await _spawn_server(
            stack, "uv", ["run", "standardgraph"],
            sg_env, "SG", cwd=SG_PROJECT,
        )
        sessions = {"sg": sg_session}
        all_tools = dict(sg_tools)
        tool_to_session = {name: "sg" for name in sg_tools}

        if not sg_only:
            oer_session, oer_tools = await _spawn_server(
                stack, "uv", ["run", "oer-mcp"],
                oer_env, "OER", cwd=OER_PROJECT,
            )
            sessions["oer"] = oer_session
            all_tools.update(oer_tools)
            tool_to_session.update({name: "oer" for name in oer_tools})

        ollama_tools = [_mcp_to_ollama_tool(t) for t in all_tools.values()]

        for i, scenario in enumerate(scenarios, 1):
            real_i = SCENARIOS.index(scenario) + 1

            if verbose:
                print(f"\n  [{real_i}] {scenario['name']}")
                print(f"       Q: {scenario['prompt']}")

            result = await run_agent(
                scenario["prompt"], ollama_tools, sessions,
                tool_to_session, verbose,
            )

            det_ok, det_msg = _check(scenario, result)
            det_tag = _OK if det_ok else (_ERR if result["error"] else _FAIL)

            llm_verdict = llm_reason = ""
            llm_tag = _SKIP
            if not no_judge and not result["error"]:
                llm_verdict, llm_reason = _gemma_judge(
                    scenario["prompt"], result["final_answer"],
                )
                llm_tag = (
                    _OK   if llm_verdict == "YES"     else
                    _PART if llm_verdict == "PARTIAL" else
                    _ERR  if llm_verdict == "ERR"     else
                    _FAIL
                )

            tool_summary = ", ".join(
                t["name"].replace("_", "") for t in result["tool_calls"]
            )
            if len(tool_summary) > 18:
                tool_summary = tool_summary[:15] + "..."
            short = scenario["name"][:40] + ".." if len(scenario["name"]) > 42 else scenario["name"]
            print(f"  {real_i:<3} {short:<42} {tool_summary:<18} [{det_tag}] [{llm_tag}]")

            if not det_ok:
                print(f"       DET: {det_msg}")
            if llm_verdict and llm_verdict not in ("YES",):
                print(f"       LLM: {llm_reason[:120]}")

            if verbose and result["final_answer"]:
                print(f"       A: {_DIM}{result['final_answer'][:300]}{_RST}")

            if result["error"]:
                errors += 1
            elif not det_ok:
                failed += 1
            elif llm_verdict == "PARTIAL":
                partial += 1
            else:
                passed += 1

            results_log.append({
                "scenario": scenario["name"],
                "mode": "sg_only" if sg_only else "combined",
                "det_ok": det_ok,
                "llm_verdict": llm_verdict,
                "tool_calls": [t["name"] for t in result["tool_calls"]],
                "answer_len": len(result["final_answer"]),
                "answer": result["final_answer"],
                "error": result["error"],
            })

    total = len(scenarios)
    print(f"\n  {total} scenarios: {passed} passed, {partial} partial, "
          f"{failed} failed, {errors} errors")
    print()
    return results_log


async def _run_comparison(scenario_filter: int | None, no_judge: bool,
                          verbose: bool) -> int:
    print("=" * 72)
    print("  D9 BENCHMARK — OER + StandardGraph vs StandardGraph alone")
    print("=" * 72)

    sg_results = await _run(scenario_filter, no_judge, verbose, sg_only=True)
    combined_results = await _run(scenario_filter, no_judge, verbose, sg_only=False)

    if isinstance(sg_results, int) or isinstance(combined_results, int):
        return 1

    print("\n── Comparison ────────────────────────────────────────────────────")
    print(f"  {'#':<3} {'Scenario':<42} {'SG-only':>8} {'Combined':>9} {'Winner':>7}")
    print(f"  {'-'*3} {'-'*42} {'-'*8:>8} {'-'*9:>9} {'-'*7:>7}")

    b_wins = a_wins = ties = 0
    for sg_r, comb_r in zip(sg_results, combined_results):
        sg_grade = sg_r["llm_verdict"] or ("OK" if sg_r["det_ok"] else "FAIL")
        co_grade = comb_r["llm_verdict"] or ("OK" if comb_r["det_ok"] else "FAIL")

        prompt = next(s["prompt"] for s in SCENARIOS if s["name"] == sg_r["scenario"])
        if not no_judge and sg_r.get("answer") and comb_r.get("answer"):
            cmp, _ = _gemma_compare(prompt, sg_r["answer"], comb_r["answer"])
            if cmp == "B":
                winner_tag = "OER+"
                b_wins += 1
            elif cmp == "A":
                winner_tag = "SG"
                a_wins += 1
            else:
                winner_tag = "="
                ties += 1
        else:
            winner_tag = "-"

        short = sg_r["scenario"][:40] + ".." if len(sg_r["scenario"]) > 42 else sg_r["scenario"]
        print(f"  {SCENARIOS.index(next(s for s in SCENARIOS if s['name'] == sg_r['scenario'])) + 1:<3} "
              f"{short:<42} {sg_grade:>8} {co_grade:>9} {winner_tag:>7}")

    if b_wins + a_wins + ties > 0:
        print(f"\n  Head-to-head: OER+ wins {b_wins}, SG wins {a_wins}, ties {ties}")

    sg_pass = sum(1 for r in sg_results if r["det_ok"])
    co_pass = sum(1 for r in combined_results if r["det_ok"])
    print(f"  Deterministic pass rate: SG-only {sg_pass}/{len(sg_results)}, "
          f"Combined {co_pass}/{len(combined_results)}")
    print()

    any_fail = any(not r["det_ok"] for r in combined_results)
    return 1 if any_fail else 0


def main() -> None:
    p = argparse.ArgumentParser(description="D9 e2e benchmark: local LLM + MCP")
    p.add_argument("--no-judge", action="store_true", help="Skip Gemma LLM judge")
    p.add_argument("--scenario", type=int, default=None, metavar="N",
                   help=f"Run only scenario N (1-{len(SCENARIOS)})")
    p.add_argument("--verbose", action="store_true", help="Print tool calls + answers")
    p.add_argument("--sg-only", action="store_true", help="Run SG-only baseline (no comparison)")
    p.add_argument("--combined-only", action="store_true", help="Run combined mode only (no comparison)")
    p.add_argument("--list", action="store_true", help="List scenarios and exit")
    args = p.parse_args()

    if args.list:
        print(f"\n  {'#':<3} {'Scenario':<45} OER advantage?")
        for i, s in enumerate(SCENARIOS, 1):
            adv = "yes" if s.get("oer_advantage") else ""
            print(f"  {i:<3} {s['name']:<45} {adv}")
        print()
        return

    if args.sg_only:
        result = asyncio.run(_run(args.scenario, args.no_judge, args.verbose, sg_only=True))
        sys.exit(0 if isinstance(result, list) else result)
    elif args.combined_only:
        result = asyncio.run(_run(args.scenario, args.no_judge, args.verbose, sg_only=False))
        sys.exit(0 if isinstance(result, list) else result)
    else:
        sys.exit(asyncio.run(_run_comparison(args.scenario, args.no_judge, args.verbose)))


if __name__ == "__main__":
    main()
