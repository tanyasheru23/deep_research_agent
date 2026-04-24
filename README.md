# Deep Research Agent

A multi-agent research system that takes a natural language query, plans
and executes multi-round web searches, synthesises a structured report,
and delivers it as a PDF download or email.

> **Stack:** Python · FastAPI · SQLAlchemy · OpenAI Agents SDK · SQLite

---

## Architecture

```
User Query
    │
    ▼
Planner Agent
  • Breaks query into N prioritised searches
  • Classifies expected source types
  • Identifies knowledge gaps for round 2
    │
    ▼  (parallel via asyncio.gather)
Search Agents [1..N]  ◄── SQLite cache (24hr TTL)
  • Web search + summarise
  • Returns credibility score (1–5) + source domains
    │
    ▼  (gap-fill round)
Round 2 Searches
  • Planner re-queried with existing results + gaps
  • Targeted searches for unresolved questions
    │
    ▼
Coordinator Agent
  • Reads all results, produces 4-section outline
    │
    ▼  (parallel)
Section Writer Agents [1..4]
  • Each writes one section (500+ words)
  • Only receives relevant search results
    │
    ▼
Editor Agent
  • Stitches sections, fixes transitions
  • Produces final ReportData
    │
    ├──► PDF (in-memory bytes → browser download)
    ├──► Email (SendGrid)
    └──► FastAPI SSE stream → browser
```

---

## Features

| Feature | Detail |
|---|---|
| Multi-round research | Gap analysis after round 1 triggers targeted follow-up searches |
| Credibility scoring | Each search result rated 1–5; writer weights sources accordingly |
| Parallel section writers | 4 agents write simultaneously via asyncio.gather |
| SQLite cache | SHA-256 keyed, 24hr TTL — eliminates redundant API calls |
| Model routing | quick/standard → gpt-4o-mini · deep → gpt-4o |
| PDF export | reportlab PDF served as in-memory browser download |
| Email delivery | SendGrid HTML report delivery |
| SSE streaming | Every pipeline step streamed live to browser |
| JWT auth | PBKDF2-SHA256 passwords, HS256 tokens, 7-day expiry |
| Eval suite | LLM judge + structural + pipeline health checks |

---

## Eval Results

Benchmarked across 8 queries, comparing single-agent baseline vs
multi-agent V2 (with prompt engineering):

| Metric | Baseline | Multi-agent V2 | Change |
|---|---|---|---|
| Composite score | 84% | 92% | +9.5% |
| Avg words | 962 | 2,227 | +131% |
| Avg coverage | 0.89 | 0.93 | +4.5% |
| Avg depth | 0.85 | 0.90 | +5.9% |
| Avg time | 107.7s | 89.5s | −17% |
| 1500+ word pass | 0/8 | 5/8 | +62.5% |

Run your own:
```bash
python evals.py --save eval_outputs/results.json
```
For baseline results, uncomment the line 21 in evals.py and comment line 22.

For multi_agent results, comment the line 21 in evals.py and uncomment line 22. (current state)

---

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/yourname/deep-research-agent
cd deep-research-agent
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# fill in your keys
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your keys
```

### 3. Run

```bash
python main.py
# → open http://localhost:8000
```

---

## Project Structure

```
deep_research_agent/
│
├── app_agents/
│   ├── __init__.py 
│   ├── planner_agent.py                 # Query decomposition + gap analysis
│   ├── search_agent.py                  # Web search + credibility scoring
│   ├── writer_agent_baseline.py         
│   ├── writer_agent.py                  # Coordinator + section writers + editor
│   ├── email_agent.py                   # SendGrid email delivery
├── auth/
│   ├── __init__.py
│   ├── auth.py                          # JWT auth — register, login, tokens
├── core/
│   ├── __init__.py
│   ├── cache.py                         # SQLite search cache (key-value)
│   ├── research_manager_baseline.py
│   ├── research_manager.py              # Pipeline orchestration
│   ├── pdf_export.py                    # reportlab PDF generation
├── db/                      
│   ├── __init__.py
│   ├── models.py                        # SQLAlchemy models
│   ├── session.py                       # db session
├── eval_ouputs/                         # for storing eval outputs
│   ├── example.json
│ 
├── main.py                              # FastAPI app — routes, lifespan, SSE
├── evals.py                             # Evaluation suite
├── index.html                           # Frontend (served by FastAPI)
├── deep_research.db                     # SQL DB for startup - FastAPI
│
├── .env.example
├── requirements.txt
├── uvicorn_app.py                       # initial app - without FastAPI and frontend,
│                                        # using gradio - add `gradio` in requirements.txt to run this
└── README.md
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API key |
| `SENDGRID_API_KEY` | Optional | For email delivery |
| `SENDER_EMAIL` | Optional | Must be verified in SendGrid |
| `SECRET_KEY` | ✅ | JWT signing key — generate once, keep fixed |

Generate a SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Store the generated key in .env as SECRET_KEY.

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/` | — | Frontend |
| `POST` | `/api/auth/register` | — | Create account |
| `POST` | `/api/auth/login` | — | Get JWT token |
| `GET` | `/api/auth/me` | ✅ | Current user |
| `PUT` | `/api/auth/email` | ✅ | Update email |
| `POST` | `/api/research` | ✅ | Start research job |
| `GET` | `/api/stream/{job_id}` | ✅ | SSE progress stream |
| `GET` | `/api/pdf/{job_id}` | ✅ | Download PDF |
| `GET` | `/api/reports` | ✅ | Report history |
| `GET` | `/api/reports/{id}` | ✅ | Single report |
| `DELETE` | `/api/reports/{id}` | ✅ | Delete report |
| `GET` | `/api/cache/stats` | ✅ | Cache info |
| `POST` | `/api/cache/clear` | ✅ | Clear cache |

---

## License

MIT
