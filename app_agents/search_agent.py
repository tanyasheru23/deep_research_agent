from pydantic import BaseModel, Field
from agents import Agent, WebSearchTool, ModelSettings

INSTRUCTIONS = (
    "You are a research assistant. Given a search term and its expected source type, search the web "
    "and produce a concise summary of the results.\n\n"
    "The summary must be 2-3 paragraphs and under 300 words. Capture the main points.\n"
    "Write succinctly — no need for complete sentences or perfect grammar. This will be "
    "consumed by someone synthesizing a report, so capture the essence and ignore fluff.\n\n"
    "IMPORTANT: Also return the following metadata:\n"
    "- actual_source_type: the actual type of sources you found "
    "  ('academic', 'news', 'official', 'community', 'commercial', or 'mixed')\n"
    "- source_domains: up to 3 domain names you drew from (e.g. 'nature.com', 'bbc.co.uk')\n"
    "- credibility_score: integer 1-5 where 5=very credible (academic/official), "
    "  3=mixed, 1=mostly unverified blogs or forums\n\n"
    "Do not include any commentary beyond the summary and metadata."
)


class SearchResult(BaseModel):
    summary: str = Field(description="2-3 paragraph summary of search results, under 300 words.")
    actual_source_type: str = Field(
        description="Type of sources found: 'academic', 'news', 'official', 'community', 'commercial', or 'mixed'."
    )
    source_domains: list[str] = Field(description="Up to 3 domain names the summary draws from.")
    credibility_score: int = Field(description="Credibility score 1-5 (5 = most credible).", ge=1, le=5)


search_agent = Agent(
    name="Search agent",
    instructions=INSTRUCTIONS,
    tools=[WebSearchTool(search_context_size="low")],
    model="gpt-4o-mini",
    model_settings=ModelSettings(tool_choice="required"),
    output_type=SearchResult,
)
