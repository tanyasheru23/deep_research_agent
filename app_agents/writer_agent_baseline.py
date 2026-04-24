from pydantic import BaseModel, Field
from agents import Agent

INSTRUCTIONS = (
    "You are a senior researcher tasked with writing a cohesive, well-structured report.\n\n"
    "You will receive:\n"
    "- The original research query\n"
    "- Summarized search results annotated with credibility scores and source types\n"
    "- The research depth requested (quick/standard/deep)\n\n"
    "Instructions:\n"
    "1. First create an outline, then write the full report.\n"
    "2. Weight information from higher-credibility sources more heavily. "
    "   Call out any contradictions between sources.\n"
    "3. The report should be in Markdown. Aim for:\n"
    "   - quick: ~1500 words\n"
    "   - standard: ~2500 words\n"
    "   - deep: 3000+ words, 5-10 pages\n"
    "4. Structure the report with clear sections. Generate a table of contents.\n"
    "5. Note any remaining gaps or uncertainties.\n"
)


class ReportSection(BaseModel):
    title: str = Field(description="Section heading.")
    content: str = Field(description="Section body in Markdown.")


class ReportData(BaseModel):
    short_summary: str = Field(description="A short 2-3 sentence executive summary of the findings.")

    table_of_contents: list[str] = Field(description="Ordered list of section titles.")

    sections: list[ReportSection] = Field(description="Ordered list of report sections.")

    key_facts: list[str] = Field(description="Up to 10 bullet-point key facts extracted from the research.")

    contradictions_found: list[str] = Field(
        description="Any contradictions or disagreements found between sources. Empty list if none."
    )

    follow_up_questions: list[str] = Field(description="Suggested topics to research further.")

    @property
    def markdown_report(self) -> str:
        """Assemble sections into a single Markdown document."""
        lines = [f"## {s.title}\n\n{s.content}" for s in self.sections]
        toc = "\n".join(f"- {t}" for t in self.table_of_contents)
        contradictions = ""
        if self.contradictions_found:
            contradictions = "\n\n## Contradictions & Caveats\n\n" + "\n".join(
                f"- {c}" for c in self.contradictions_found
            )
        key_facts_section = "\n\n## Key Facts\n\n" + "\n".join(f"- {f}" for f in self.key_facts)
        follow_up = "\n\n## Suggested Follow-up Questions\n\n" + "\n".join(
            f"- {q}" for q in self.follow_up_questions
        )
        return (
            f"> **Summary:** {self.short_summary}\n\n"
            f"## Table of Contents\n\n{toc}\n\n"
            + "\n\n".join(lines)
            + contradictions
            + key_facts_section
            + follow_up
        )


writer_agent = Agent(
    name="WriterAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o",
    output_type=ReportData,
)
