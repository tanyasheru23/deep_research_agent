"""
Multi-agent report writer.

Flow:
  1. Coordinator  — reads search results, produces an outline (section titles + briefs)
  2. Section agents (parallel) — each writes one section from its brief
  3. Editor       — stitches sections, fixes transitions, produces final ReportData

All agents use gpt-4o-mini to keep costs low.
Switch editor to gpt-4o only if quality needs a boost.
"""

import asyncio
from pydantic import BaseModel, Field
from agents import Agent, Runner


# ── Output models ──────────────────────────────────────────────────────────

class SectionBrief(BaseModel):
    title:  str = Field(description="Section heading.")
    brief:  str = Field(description="What this section should cover in 1-2 sentences.")
    relevant_sources: list[str] = Field(description="Query strings from search results most relevant to this section.")

class Outline(BaseModel):
    sections: list[SectionBrief] = Field(description="Ordered list of sections. Aim for 4-5 sections.")

class SectionDraft(BaseModel):
    title:   str = Field(description="Section heading.")
    content: str = Field(description="Full section content in markdown. Minimum 300 words.")

class ReportSection(BaseModel):
    title:   str
    content: str

class ReportData(BaseModel):
    short_summary:       str        = Field(description="2-3 sentence summary.")
    table_of_contents:   list[str]  = Field(description="Ordered section titles.")
    sections:            list[ReportSection]
    key_facts:           list[str]  = Field(description="5-8 key facts from the research.")
    contradictions_found: list[str] = Field(description="Any conflicting findings. Empty list if none.")
    follow_up_questions: list[str]  = Field(description="3-5 suggested follow-up research questions.")

    @property
    def markdown_report(self) -> str:
        toc  = "\n".join(f"- {t}" for t in self.table_of_contents)
        body = "\n\n".join(f"## {s.title}\n\n{s.content}" for s in self.sections)
        facts = "\n".join(f"- {f}" for f in self.key_facts)
        followups = "\n".join(f"- {q}" for q in self.follow_up_questions)
        contradictions = ""
        if self.contradictions_found:
            contradictions = "\n\n## Contradictions & Caveats\n\n" + "\n".join(f"- {c}" for c in self.contradictions_found)
        return (
            f"> **Summary:** {self.short_summary}\n\n"
            f"## Table of Contents\n\n{toc}\n\n"
            f"{body}"
            f"{contradictions}\n\n"
            f"## Key Facts\n\n{facts}\n\n"
            f"## Follow-up Questions\n\n{followups}"
        )


# ── Agents ─────────────────────────────────────────────────────────────────

coordinator_agent = Agent(
    name="Coordinator",
    instructions=(
        "You are a research coordinator. Given a query and search results, "
        "Produce an outline of exactly 4 sections for a detailed research report. "
        "Each section must be broad enough to warrant at least 500 words of content. "
        "Give each section a clear title, a detailed brief of what to cover (3-4 sentences), "
        "and which search queries are most relevant to it. "
        "Sections should together give complete, deep coverage — avoid narrow or overlapping topics."
    ),
    model="gpt-4o-mini",
    output_type=Outline,
)

section_agent = Agent(
    name="SectionWriter",
    instructions=(
        "You are an expert research writer. You will be given a section title, "
        "a brief of what to cover, and relevant search results. "
        "Write a thorough, detailed section in markdown. "
        "Minimum 500 words — go deep, do not summarise. "
        "Use 2-3 subheadings (###) to organise the content. "
        "Include specific facts, numbers, examples, and mechanisms — not just high-level claims. "
        "Every paragraph should add new information, not restate the previous one."
    ),
    model="gpt-4o-mini",
    output_type=SectionDraft,
)

editor_agent = Agent(
    name="Editor",
    instructions=(
        "You are a senior editor. You will receive a query, all section drafts, "
        "and the original search results. Your job is to:\n"
        "1. Combine all sections into a final cohesive report — preserve all detail, do not compress\n"
        "2. Only remove true duplicates (identical facts stated twice) — similar ideas in different sections are fine\n"
        "3. Add smooth transitions between sections\n"
        "4. Additionally write a 2-3 sentence summary\n"
        "5. Extract 8-10 key facts from across all sections\n"
        "6. Note any contradictions found in the sources\n"
        "7. Suggest 5 follow-up research questions\n"
        "The final report should be at least 2000 words. Return the complete structured report."
    ),
    model="gpt-4o",
    output_type=ReportData,
)


# ── Orchestration ──────────────────────────────────────────────────────────

async def write_report(query: str, search_results: list[dict]) -> ReportData:
    """
    Full multi-agent pipeline:
      coordinator → parallel section writers → editor
    """
    # Format search results for agents
    formatted = "\n\n".join(
        f"[Query: {r['query']} | Credibility: {r['credibility_score']}/5]\n{r['summary']}"
        for r in search_results
    )

    # Step 1 — Coordinator produces outline
    coord_result = await Runner.run(
        coordinator_agent,
        f"Research query: {query}\n\nSearch results:\n{formatted}",
    )
    outline: Outline = coord_result.final_output_as(Outline)
    print(f"  Outline ready — {len(outline.sections)} sections planned")

    # Step 2 — Section agents run in parallel
    async def write_section(brief: SectionBrief) -> SectionDraft:
        # Only pass relevant search results to each section agent
        relevant = "\n\n".join(
            f"[Query: {r['query']}]\n{r['summary']}"
            for r in search_results
            if r["query"] in brief.relevant_sources
        ) or formatted  # fallback to all results if none matched

        result = await Runner.run(
            section_agent,
            f"Section title: {brief.title}\n"
            f"What to cover: {brief.brief}\n\n"
            f"Relevant research:\n{relevant}",
        )
        draft = result.final_output_as(SectionDraft)
        print(f"  ✅ Section done: {brief.title} ({len(draft.content.split())} words)")
        return draft

    drafts = await asyncio.gather(*[write_section(b) for b in outline.sections])

    # Step 3 — Editor stitches everything together
    drafts_text = "\n\n---\n\n".join(
        f"## {d.title}\n\n{d.content}" for d in drafts
    )
    editor_result = await Runner.run(
        editor_agent,
        f"Original query: {query}\n\n"
        f"Section drafts:\n{drafts_text}\n\n"
        f"Original search results:\n{formatted}",
    )
    report = editor_result.final_output_as(ReportData)
    total_words = sum(len(s.content.split()) for s in report.sections)
    print(f"  Report complete — {total_words} words across {len(report.sections)} sections")
    return report