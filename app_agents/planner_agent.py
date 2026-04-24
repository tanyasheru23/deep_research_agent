from pydantic import BaseModel, Field
from agents import Agent

# Base searches per depth; multiplied dynamically by query complexity
DEPTH_SEARCHES = {
    "quick": 3,
    "standard": 5,
    "deep": 8,
}

INSTRUCTIONS = """You are a helpful research assistant. Given a query and a desired depth, 
produce a set of web searches to best answer the query.

For each search item, also classify the expected source type so downstream agents can weight results:
- 'academic'  : peer-reviewed papers, university sites, research orgs
- 'news'      : journalism, press releases, current events
- 'official'  : government, standards bodies, official documentation  
- 'community' : forums, blogs, Stack Overflow, Reddit
- 'commercial': product pages, vendor blogs

Output the number of searches appropriate for the requested depth.
"""


class WebSearchItem(BaseModel):
    reason: str = Field(description="Your reasoning for why this search is important to the query.")
    query: str = Field(description="The search term to use for the web search.")
    priority: int = Field(description="Priority 1 (highest) to 3 (lowest). High-priority searches run first.", ge=1, le=3)
    expected_source_type: str = Field(
        description="Expected type of sources: 'academic', 'news', 'official', 'community', or 'commercial'."
    )


class WebSearchPlan(BaseModel):
    complexity: str = Field(description="Assessed complexity of the query: 'simple', 'moderate', or 'complex'.")
    searches: list[WebSearchItem] = Field(description="A list of web searches to perform, ordered by priority.")
    knowledge_gaps: list[str] = Field(
        description="Key questions that are NOT yet answered by the planned searches — used for follow-up rounds."
    )


planner_agent = Agent(
    name="PlannerAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=WebSearchPlan,
)
