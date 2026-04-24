"""
Intermediate evals — three layers:
  1. LLM judge     : coverage, depth, coherence, source reliability
  2. Structure     : word count, sections, balance, summary accuracy
  3. Pipeline      : source credibility, gap-fill effectiveness

Usage:
    python evals.py
    python evals.py --save baseline.json
"""

import asyncio
import json
import argparse
import time
import re
from dotenv import load_dotenv
load_dotenv()

from agents import Agent, Runner
# from core.research_manager_baseline import ResearchManager
from core.research_manager import ResearchManager

BENCHMARK_QUERIES = [
    "What are the different types of research being done in AI security today?",
    "What are the main causes of rising global inflation in recent years?",
    "What are the different approaches to improving public health outcomes at a population level?",
    "What are the major challenges in modern education systems, and what solutions are being explored?",
    "What are the different types of cybersecurity threats today, and how are they evolving?",
    "What strategies are being used globally to reduce carbon emissions, and how effective are they?",
    "What are the major bottlenecks in global semiconductor supply chains, and why do they matter?",
    "What are the risks and benefits of decentralized finance (DeFi) compared to traditional banking systems?",
]

# ── LLM Judge ─────────────────────────────────────────────────────────────
judge_agent = Agent(
    name="Judge",
    instructions=(
        "You are evaluating a research report. Be strict — reserve 0.9+ for excellent work.\n"
        "Score ONLY this JSON, no other text:\n"
        "{\n"
        '  "coverage": <0.0-1.0, did it fully answer every aspect of the query?>,\n'
        '  "depth": <0.0-1.0, specific expert details vs vague surface-level statements?>,\n'
        '  "coherence": <0.0-1.0, do sections connect well and flow logically?>,\n'
        '  "source_reliability": <0.0-1.0, does it feel well-sourced with specific facts vs generic claims?>\n'
        "}"
    ),
    model="gpt-4o-mini",
)

async def llm_judge(query: str, markdown: str) -> dict[str, float]:
    try:
        result = await Runner.run(
            judge_agent,
            f"Query: {query}\n\nFull Report:\n{markdown}"
        )
        raw    = result.final_output.strip().replace("```json", "").replace("```", "")
        scores = json.loads(raw)
        return {k: round(max(0.0, min(1.0, float(v))), 2) for k, v in scores.items()}
    except Exception as e:
        print(f"  ⚠️  Judge failed: {e}")
        return {"coverage": 0.0, "depth": 0.0, "coherence": 0.0, "source_reliability": 0.0}


# ── Structure checks ───────────────────────────────────────────────────────
def structure_checks(markdown: str) -> dict[str, bool | float]:
    words         = markdown.split()
    total_words   = len(words)
    sections      = re.findall(r"^## .+", markdown, re.MULTILINE)
    section_count = len(sections)

    # Section balance — no section should be >40% of total words
    section_word_counts = []
    parts = re.split(r"^## .+", markdown, flags=re.MULTILINE)
    for part in parts[1:]:  # skip content before first section
        section_word_counts.append(len(part.split()))
    max_pct = max(c / total_words for c in section_word_counts) if section_word_counts else 1.0
    balanced = max_pct <= 0.40

    # Summary accuracy — do key query words appear in the summary?
    summary_match = re.search(r"> \*\*Summary:\*\* (.+)", markdown)
    summary_text  = summary_match.group(1).lower() if summary_match else ""
    query_words   = [w.lower() for w in re.findall(r"\b\w{5,}\b", markdown[:100])]
    summary_accurate = sum(1 for w in query_words if w in summary_text) >= 2

    return {
        "1500+ words":        total_words >= 1500,
        "4+ sections":        section_count >= 4,
        "has follow-ups":     "follow" in markdown.lower(),
        "sections balanced":  balanced,
        "summary accurate":   summary_accurate,
        "_max_section_pct":   round(max_pct * 100),   # diagnostic only
        "_total_words":       total_words,
        "_section_count":     section_count,
    }


# ── Pipeline checks ────────────────────────────────────────────────────────
def pipeline_checks(search_results: list[dict], gap_results: list[dict]) -> dict:
    if not search_results:
        return {"avg_credibility": 0.0, "high_credibility_pct": 0, "gap_fill_new_domains": 0}

    all_scores  = [r["credibility_score"] for r in search_results]
    avg_cred    = round(sum(all_scores) / len(all_scores), 2)
    high_cred   = round(sum(1 for s in all_scores if s >= 4) / len(all_scores) * 100)

    # Gap-fill effectiveness — how many new domains did round 2 add?
    r1_domains  = {d for r in search_results for d in r.get("source_domains", [])}
    r2_domains  = {d for r in gap_results    for d in r.get("source_domains", [])}
    new_domains = len(r2_domains - r1_domains)

    return {
        "avg_credibility":       avg_cred,
        "high_credibility_pct":  high_cred,   # % of sources scoring 4+/5
        "gap_fill_new_domains":  new_domains,
    }


# ── Single query eval ──────────────────────────────────────────────────────
async def run_eval(query: str) -> dict:
    print(f"\n  Query : {query}")
    start    = time.time()
    manager  = ResearchManager()
    markdown = ""

    # Intercept search results for pipeline checks
    r1_results, r2_results = [], []
    _orig_perform = manager._perform_searches

    round_num = 0
    async def _capture_searches(plan):
        nonlocal round_num
        round_num += 1
        results = await _orig_perform(plan)
        if round_num == 1:
            r1_results.extend(results)
        else:
            r2_results.extend(results)
        return results
    manager._perform_searches = _capture_searches

    async for chunk in manager.run(
        query, depth="standard", send_email=False, export_pdf_flag=False
    ):
        if chunk.startswith(">") or chunk.startswith("##") or chunk.startswith("# "):
            markdown = chunk

    duration = round(time.time() - start, 1)

    # Run all checks
    llm_scores  = await llm_judge(query, markdown)
    struct      = structure_checks(markdown)
    pipeline    = pipeline_checks(r1_results, r2_results)

    # Separate scoring values from diagnostic values
    struct_scores = {k: v for k, v in struct.items() if not k.startswith("_")}
    struct_diag   = {k: v for k, v in struct.items() if k.startswith("_")}

    # Composite — LLM (60%) + structure (40%)
    llm_avg    = sum(llm_scores.values()) / len(llm_scores)
    struct_avg = sum(1 for v in struct_scores.values() if v) / len(struct_scores)
    composite  = round((llm_avg * 0.60 + struct_avg * 0.40) * 100)

    # Print results
    bar = "█" * (composite // 10) + "░" * (10 - composite // 10)
    print(f"  Score : {bar} {composite}%  |  {struct_diag['_total_words']} words  |  {duration}s")
    print(f"  LLM   → " + "  ".join(f"{k}={v:.2f}" for k, v in llm_scores.items()))
    print(f"  Struct→ " + "  ".join(f"{'✅' if v else '❌'} {k}" for k, v in struct_scores.items()))
    print(f"  Pipe  → credibility={pipeline['avg_credibility']}/5  "
          f"high_cred={pipeline['high_credibility_pct']}%  "
          f"gap_new_domains={pipeline['gap_fill_new_domains']}")

    return {
        "query":      query,
        "composite":  composite,
        "duration":   duration,
        "llm_scores": llm_scores,
        "structure":  {**struct_scores, **struct_diag},
        "pipeline":   pipeline,
    }


# ── Main ───────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", default=None, help="Save results to JSON")
    args = parser.parse_args()

    print("\n🔬 Running evals...\n" + "─" * 60)
    results = []
    for query in BENCHMARK_QUERIES:
        results.append(await run_eval(query))

    # Summary
    avg_composite  = round(sum(r["composite"] for r in results) / len(results))
    avg_words      = round(sum(r["structure"]["_total_words"] for r in results) / len(results))
    avg_cred       = round(sum(r["pipeline"]["avg_credibility"] for r in results) / len(results), 2)
    avg_coverage   = round(sum(r["llm_scores"]["coverage"] for r in results) / len(results), 2)
    avg_depth      = round(sum(r["llm_scores"]["depth"] for r in results) / len(results), 2)
    avg_time       = round(sum(r["duration"] for r in results) / len(results), 1)

    print(f"\n{'─' * 60}")
    print(f"  Queries run        : {len(results)}")
    print(f"  Avg composite      : {avg_composite}%")
    print(f"  Avg words          : {avg_words}")
    print(f"  Avg coverage       : {avg_coverage}")
    print(f"  Avg depth          : {avg_depth}")
    print(f"  Avg src credibility: {avg_cred}/5")
    print(f"  Avg duration       : {avg_time}s")
    print(f"{'─' * 60}\n")

    if args.save:
        out = {
            "avg_composite":   avg_composite,
            "avg_words":       avg_words,
            "avg_credibility": avg_cred,
            "avg_coverage":    avg_coverage,
            "avg_depth":       avg_depth,
            "avg_time":        avg_time,
            "results":         results,
        }
        with open(args.save, "w") as f:
            json.dump(out, f, indent=2)
        print(f"💾 Saved to {args.save}")

if __name__ == "__main__":
    asyncio.run(main())