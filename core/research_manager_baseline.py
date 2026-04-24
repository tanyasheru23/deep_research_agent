"""
ResearchManager — orchestrates the full research pipeline.

Key changes vs original:
  - PDF generated as in-memory bytes (no local file save)
  - recipient_email passed through for per-user email delivery
  - send_email / export_pdf are optional flags
"""

from __future__ import annotations

import asyncio
import io
from typing import AsyncGenerator

from agents import Runner, trace, gen_trace_id

from core.cache import get_cached, set_cached
from app_agents.planner_agent import planner_agent, WebSearchItem, WebSearchPlan, DEPTH_SEARCHES
from app_agents.search_agent import search_agent, SearchResult
from app_agents.writer_agent_baseline import writer_agent, ReportData
from app_agents.email_agent import make_email_agent
from core.pdf_export import export_pdf_bytes

WRITER_MODELS = {
    "quick":    "gpt-4o-mini",
    "standard": "gpt-4o-mini",
    "deep":     "gpt-4o",
}


class ResearchManager:

    async def run(
        self,
        query: str,
        depth: str = "standard",
        send_email: bool = False,
        export_pdf_flag: bool = True,
        recipient_email: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Yields status strings during the pipeline, then the final markdown report.
        PDF bytes are stored on the job object in server.py — not yielded.
        """
        trace_id = gen_trace_id()
        self._last_pdf_bytes: bytes | None = None

        with trace("Research trace", trace_id=trace_id):
            yield f"🔍 Trace: https://platform.openai.com/traces/trace?trace_id={trace_id}"

            # ── Round 1 ──────────────────────────────────────────────────
            yield f"📋 Planning searches (depth: {depth})..."
            search_plan = await self._plan_searches(query, depth)
            yield f"✅ Plan ready — {len(search_plan.searches)} searches | complexity: {search_plan.complexity}"

            yield "🌐 Running searches (round 1)..."
            search_results = await self._perform_searches(search_plan)
            yield f"✅ Round 1 complete — {len(search_results)} results"

            # ── Round 2: gap-filling ──────────────────────────────────────
            if depth in ("standard", "deep") and search_plan.knowledge_gaps:
                yield f"🔄 Gap-fill round — {len(search_plan.knowledge_gaps)} gap(s)..."
                gap_plan = await self._plan_gap_searches(query, search_results, search_plan.knowledge_gaps, depth)
                if gap_plan.searches:
                    gap_results = await self._perform_searches(gap_plan)
                    search_results.extend(gap_results)
                    yield f"✅ Round 2 complete — {len(gap_results)} additional results"

            # ── Write report ──────────────────────────────────────────────
            model = WRITER_MODELS.get(depth, "gpt-4o-mini")
            yield f"✍️ Writing report with {model}..."
            report = await self._write_report(query, search_results, depth, model)
            yield "✅ Report written"

            # ── PDF (in-memory bytes) ─────────────────────────────────────
            if export_pdf_flag:
                yield "📄 Generating PDF..."
                try:
                    self._last_pdf_bytes = export_pdf_bytes(report, query)
                    yield "✅ PDF ready for download"
                except Exception as e:
                    yield f"⚠️ PDF generation failed: {e}"

            # ── Email ─────────────────────────────────────────────────────
            if send_email and recipient_email:
                yield f"📧 Sending report to {recipient_email}..."
                try:
                    await self._send_email(report, recipient_email)
                    yield f"✅ Email sent to {recipient_email}"
                except Exception as e:
                    yield f"⚠️ Email failed: {e}"
            elif send_email and not recipient_email:
                yield "⚠️ No email address set — skipping email"

            yield "🎉 Research complete!"
            yield report.markdown_report

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _plan_searches(self, query: str, depth: str) -> WebSearchPlan:
        n = DEPTH_SEARCHES.get(depth, 5)
        result = await Runner.run(
            planner_agent,
            f"Query: {query}\nRequested depth: {depth}\nProduce exactly {n} search items.",
        )
        plan: WebSearchPlan = result.final_output_as(WebSearchPlan)
        plan.searches.sort(key=lambda s: s.priority)
        return plan

    async def _plan_gap_searches(self, query, existing, gaps, depth) -> WebSearchPlan:
        summaries = "\n".join(
            f"- [{r['query']}] (cred {r['credibility_score']}/5): {r['summary'][:200]}..."
            for r in existing
        )
        gap_text = "\n".join(f"- {g}" for g in gaps)
        n = max(2, DEPTH_SEARCHES.get(depth, 5) // 2)
        result = await Runner.run(
            planner_agent,
            f"Original query: {query}\n\nAlready gathered:\n{summaries}\n\n"
            f"Known gaps:\n{gap_text}\n\n"
            f"Produce {n} NEW search items to fill these gaps.",
        )
        plan: WebSearchPlan = result.final_output_as(WebSearchPlan)
        plan.searches.sort(key=lambda s: s.priority)
        return plan

    async def _perform_searches(self, plan: WebSearchPlan) -> list[dict]:
        tasks = [asyncio.create_task(self._search(item)) for item in plan.searches]
        results = []
        for task in asyncio.as_completed(tasks):
            result = await task
            if result:
                results.append(result)
        return results

    async def _search(self, item: WebSearchItem) -> dict | None:
        cached = get_cached(item.query)
        if cached:
            return cached
        try:
            result = await Runner.run(
                search_agent,
                f"Search term: {item.query}\nReason: {item.reason}\n"
                f"Expected source type: {item.expected_source_type}",
            )
            sr: SearchResult = result.final_output_as(SearchResult)
            record = {
                "query": item.query,
                "summary": sr.summary,
                "actual_source_type": sr.actual_source_type,
                "source_domains": sr.source_domains,
                "credibility_score": sr.credibility_score,
            }
            set_cached(item.query, record)
            return record
        except Exception as e:
            print(f"Search failed '{item.query}': {e}")
            return None

    async def _write_report(self, query, results, depth, model) -> ReportData:
        formatted = "\n\n".join(
            f"[Credibility: {r['credibility_score']}/5 | type: {r['actual_source_type']} | "
            f"domains: {', '.join(r['source_domains'])}]\n"
            f"Query: {r['query']}\nSummary: {r['summary']}"
            for r in results
        )
        original = writer_agent.model
        writer_agent.model = model
        try:
            result = await Runner.run(
                writer_agent,
                f"Original query: {query}\nRequested depth: {depth}\n\n"
                f"Search results:\n{formatted}",
            )
            return result.final_output_as(ReportData)
        finally:
            writer_agent.model = original

    async def _send_email(self, report: ReportData, recipient_email: str) -> None:
        agent = make_email_agent(recipient_email)
        await Runner.run(agent, report.markdown_report)