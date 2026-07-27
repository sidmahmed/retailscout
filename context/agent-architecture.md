## Recommended approach

Add **one primary RetailScout agent inside the FastAPI backend**, but keep it separated from the scoring and GIS code:

```text
Next.js application
├── Map and filters
├── Location cards and comparisons
└── Conversational side panel
          │
          │ POST + SSE stream
          ▼
FastAPI
├── /api/v1/chat/stream
│
├── agent/
│   ├── orchestration
│   ├── tools
│   ├── prompts
│   ├── context
│   ├── guardrails
│   └── response schemas
│
├── domain services
│   ├── location search
│   ├── score explanation
│   ├── comparison
│   ├── pedestrian analysis
│   ├── business analysis
│   └── project management
│
└── PostgreSQL + PostGIS
```

The agent should **never calculate scores itself** and should never have unrestricted database or SQL access. It calls typed application tools which invoke the same tested services used by the normal UI.

LangChain’s current `create_agent` runtime supports iterative tool calls, structured responses, streaming, middleware and persistent conversation state through LangGraph. That makes it a reasonable fit for your Python/FastAPI architecture without needing multiple agents. ([Docs by LangChain][1])

---

# 1. What the conversational layer should do

## Explain a location

Example:

> Why did this Bourke Street location score 78?

The agent should retrieve:

* Overall score
* Component scores
* Relevant percentiles
* Foot-traffic patterns
* Worker population
* Competitor density
* Transport access
* Development activity
* Data confidence
* Data-source dates

It could answer:

> This location performs particularly well for a weekday-focused café. Its strongest factors are morning pedestrian activity, worker density within 800 metres and proximity to tram stops. Competition is the largest drawback, with 14 café-type establishments within 400 metres. The pedestrian component is based on sensors approximately 180 metres away, so confidence is moderate rather than high.

Every number must come from a tool result, not from the model’s memory.

## Find suitable locations

Example:

> Find the best areas for a small café near a train station. I care more about weekday breakfast traffic than weekends and want to avoid areas with too many existing cafés.

The agent converts this into a typed search:

```json
{
  "business_profile": "cafe",
  "geography": {
    "boundary": "city_of_melbourne"
  },
  "objectives": {
    "weekday_morning_traffic": 0.35,
    "worker_population": 0.25,
    "transport_access": 0.20,
    "competition": 0.20
  },
  "constraints": {
    "max_distance_to_train_station_m": 800,
    "max_competing_cafes_400m": 12
  },
  "result_count": 10
}
```

PostGIS and the scoring service perform the search. The agent receives only the top candidates and supporting evidence.

It should not receive all analysis cells and attempt to rank them in context.

## Compare locations

Example:

> Compare this location with the one I saved near Queen Victoria Market.

The result could include:

* Side-by-side score breakdown
* Different daypart patterns
* Competitor mix
* Transport access
* Confidence and data coverage
* The type of business each location suits
* A recommendation conditional on the user’s priorities

The agent should avoid declaring one location universally superior. A result might say:

> Location A is stronger for weekday office-worker demand. Location B appears better for weekend and destination traffic.

## Control the application

Users should be able to say:

* “Show only locations scoring above 75.”
* “Zoom into Carlton.”
* “Highlight the top five café locations.”
* “Hide development projects.”
* “Change this project to a food-truck profile.”
* “Save the first and third locations.”
* “Open the pedestrian chart for this location.”
* “Compare the selected locations.”

These should produce typed UI commands, not instructions that the frontend tries to interpret from natural language.

## Answer methodology questions

Examples:

* “How is competition measured?”
* “Why does a planned development improve the score?”
* “How recent is the pedestrian data?”
* “Does this score consider rent?”
* “What does medium confidence mean?”

These answers should be grounded in your methodology, data dictionary and dataset documentation.

## Conduct scenario analysis

Later:

* “What happens if I value weekend traffic more?”
* “Remove transport access from the weighting.”
* “Assume the nearby development is completed.”
* “How would this location score as a convenience store instead?”
* “What would need to improve for this location to reach 80?”

The recalculation remains deterministic. The agent changes approved inputs and calls the scoring service again.

---

# 2. Agent tool design

Start with approximately 12 focused tools rather than one generic database tool.

## Location analysis tools

| Tool                      | Purpose                                                      |
| ------------------------- | ------------------------------------------------------------ |
| `search_locations`        | Find ranked cells or candidate locations from typed criteria |
| `get_location_score`      | Retrieve a complete score breakdown                          |
| `compare_locations`       | Compare two to five locations                                |
| `get_pedestrian_profile`  | Retrieve hourly, daily and seasonal patterns                 |
| `get_nearby_businesses`   | Retrieve establishment counts and categories                 |
| `get_worker_population`   | Retrieve employment measures around a location               |
| `get_transport_context`   | Retrieve nearby stops, stations and routes                   |
| `get_development_context` | Retrieve nearby development projects                         |
| `get_data_lineage`        | Retrieve source releases, dates and confidence               |

## Application tools

| Tool                         | Purpose                                   |
| ---------------------------- | ----------------------------------------- |
| `update_map_view`            | Zoom, centre or highlight locations       |
| `update_map_filters`         | Change visible layers and score filters   |
| `save_locations`             | Save selected candidates to a project     |
| `update_project_preferences` | Change profile, weights or constraints    |
| `create_comparison`          | Add locations to the comparison workspace |
| `generate_location_report`   | Produce a later report or export          |

Use strict Pydantic input and result models. Structured outputs allow the frontend to render predictable cards, maps and charts rather than parsing assistant prose. LangChain supports validated Pydantic-based agent responses, while provider-native structured output can be used when the selected model supports it. ([Docs by LangChain][2])

### Do not provide these tools

Avoid:

```text
execute_sql
query_database
run_python
call_arbitrary_url
calculate_score
update_any_record
```

They are unnecessarily broad and make authorisation, auditing and hallucination control harder.

---

# 3. Agent response contract

The final answer should contain both conversational text and machine-readable UI instructions.

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field


class EvidenceReference(BaseModel):
    source_name: str
    dataset_release_id: int | None = None
    observed_at: str | None = None
    label: str
    url: str | None = None


class MapAction(BaseModel):
    action: Literal[
        "set_view",
        "highlight_locations",
        "set_filters",
        "open_location",
        "open_comparison",
    ]
    payload: dict


class ResultCard(BaseModel):
    card_type: Literal[
        "location",
        "score_breakdown",
        "comparison",
        "pedestrian_chart",
        "business_mix",
        "development",
        "warning",
    ]
    title: str
    data: dict


class AgentResponse(BaseModel):
    answer: str
    cards: list[ResultCard] = []
    map_actions: list[MapAction] = []
    evidence: list[EvidenceReference] = []
    assumptions: list[str] = []
    suggested_prompts: list[str] = []
```

A conversational response might therefore:

1. Stream a textual explanation.
2. Highlight three cells on the map.
3. Render three location cards.
4. Show a comparison chart.
5. Display data-source and confidence references.

---

# 4. Chat and map interaction

The map should remain the primary workspace. Chat acts as a copilot.

```text
┌──────────────────────────────────────────────┬─────────────────────────┐
│                                              │ RetailScout Assistant   │
│                                              │                         │
│                 Interactive map              │ User message            │
│                                              │ Assistant explanation   │
│        highlighted cells and locations       │ Location cards          │
│                                              │ Comparison chart        │
│                                              │ Suggested actions       │
├──────────────────────────────────────────────┴─────────────────────────┤
│ Filters, timeline, business profile and selected locations            │
└────────────────────────────────────────────────────────────────────────┘
```

The agent should automatically receive relevant application context:

```json
{
  "project_id": "project_123",
  "business_profile": "cafe",
  "selected_location_ids": ["cell_abc"],
  "map_bounds": {
    "west": 144.94,
    "south": -37.83,
    "east": 144.99,
    "north": -37.79
  },
  "active_filters": {
    "minimum_score": 60,
    "daypart": "weekday_morning"
  },
  "visible_layers": [
    "scores",
    "pedestrian_sensors",
    "developments"
  ]
}
```

This allows:

> “Why is this area stronger than the one to its north?”

without forcing the user to identify both cells manually.

### Generative UI

Tool outputs should render through predefined React components:

```text
search_locations result      → LocationResultsList
compare_locations result     → LocationComparison
get_pedestrian_profile       → PedestrianChart
get_nearby_businesses        → BusinessMixCard
update_project_preferences   → PreferenceChangeCard
```

Vercel’s AI SDK supports connecting tool results to React components and persisting structured UI messages. It is useful if you want its chat hooks and generative-UI conventions. ([AI SDK][3])

However, because your agent orchestration is in Python, I would not move the actual tools into Next.js. Either:

* Build a small custom React streaming hook for FastAPI, or
* Use a thin Next.js chat transport that forwards streams from FastAPI.

Do not define half the tools in TypeScript and half in Python.

---

# 5. Streaming design

Use a streaming POST endpoint:

```text
POST /api/v1/chat/stream
```

Return server-sent events such as:

```text
event: run.started
event: message.delta
event: tool.started
event: tool.completed
event: ui.action
event: message.completed
event: run.failed
```

Example:

```json
{
  "event": "tool.started",
  "tool": "search_locations",
  "label": "Searching café locations"
}
```

Then:

```json
{
  "event": "ui.action",
  "action": {
    "action": "highlight_locations",
    "payload": {
      "location_ids": ["cell_a", "cell_b", "cell_c"]
    }
  }
}
```

Show user-friendly activity such as:

> Analysing weekday pedestrian activity…

Do not show private model reasoning or a raw chain of thought.

---

# 6. Data grounding

## Structured data stays in PostGIS

Use direct domain queries for:

* Scores
* Counts
* Distances
* Rankings
* Pedestrian observations
* Business establishments
* Transport
* Development projects
* Employment
* Saved locations

Do not embed millions of location cells and use vector search to find the “best” cells. This is a structured filtering and ranking problem.

## RAG is for documents

Use retrieval for:

* RetailScout methodology
* Metric definitions
* Data limitations
* Council dataset documentation
* Planning and licensing information
* User-uploaded business plans
* Generated reports
* Relevant council policy documents

For an MVP, add:

```text
knowledge.document
knowledge.document_section
knowledge.embedding
```

Postgres full-text search plus `pgvector` is sufficient for a relatively small document collection. The pgvector extension provides vector types and approximate indexes such as HNSW and IVFFlat. ([GitHub][4])

Every retrieved section should include:

```text
document ID
source URL
title
section heading
publication date
retrieval date
validity period
jurisdiction
```

The model must treat retrieved content as evidence, not instructions.

---

# 7. Score explanations

Do not ask the model to look at raw score columns and invent an explanation.

Create a deterministic explanation object during score computation:

```json
{
  "location_id": "cell_abc",
  "score": 78,
  "score_version": "cafe-v1",
  "feature_version": "2026-07",
  "components": [
    {
      "name": "weekday_morning_traffic",
      "raw_value": 1250,
      "percentile": 0.89,
      "normalised_score": 89,
      "weighted_contribution": 17.8
    },
    {
      "name": "competition",
      "raw_value": 14,
      "percentile": 0.76,
      "normalised_score": 39,
      "weighted_contribution": 7.8
    }
  ],
  "strengths": [
    {
      "code": "HIGH_WEEKDAY_MORNING_TRAFFIC",
      "evidence": {
        "percentile": 0.89
      }
    }
  ],
  "risks": [
    {
      "code": "HIGH_CAFE_DENSITY",
      "evidence": {
        "count_400m": 14
      }
    }
  ],
  "confidence": {
    "level": "medium",
    "reasons": [
      "Nearest pedestrian sensor is 180 metres away"
    ]
  }
}
```

The LLM turns that into language appropriate for the user.

This provides three benefits:

* Explanations remain consistent with the actual score.
* You can test them without an LLM.
* Another model can be substituted without changing the scoring logic.

---

# 8. Conversation state and memory

Use three different forms of state.

## Application context

Always injected from the app:

* Current project
* Business profile
* Selected locations
* Active filters
* Map viewport
* Score version
* User permissions

This is authoritative and should not be inferred from old chat messages.

## Thread memory

Stores the conversation and recent tool activity.

LangGraph checkpointing can persist each conversation by `thread_id`, allowing a thread to resume after another request or failure. Its official Postgres checkpointer is suitable for durable production state. ([Docs by LangChain][5])

Long conversations should be periodically summarised while retaining:

* User decisions
* Referenced location IDs
* Active constraints
* Outstanding questions
* Saved assumptions

Do not repeatedly send the entire chat history.

## Long-term preferences

Only store explicit, useful preferences such as:

```text
Preferred business type: café
Primary demand period: weekday breakfast
Maximum preferred competitor count: 10 within 400m
Transport requirement: within 800m of a station
```

Do not silently infer or retain sensitive personal details.

---

# 9. Database additions

```sql
CREATE TABLE app.chat_thread (
    thread_id       uuid PRIMARY KEY,
    user_id         uuid,
    project_id      uuid REFERENCES app.project(project_id),
    title           text,
    status          text NOT NULL DEFAULT 'active',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.chat_message (
    message_id      uuid PRIMARY KEY,
    thread_id       uuid NOT NULL REFERENCES app.chat_thread(thread_id),
    role             text NOT NULL,
    parts            jsonb NOT NULL,
    status           text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit.agent_run (
    run_id           uuid PRIMARY KEY,
    thread_id        uuid NOT NULL,
    message_id       uuid,
    model_provider   text NOT NULL,
    model_name       text NOT NULL,
    prompt_version   text NOT NULL,
    score_version    text,
    started_at       timestamptz NOT NULL,
    completed_at     timestamptz,
    input_tokens     integer,
    output_tokens    integer,
    latency_ms       integer,
    status           text NOT NULL,
    error_code       text
);

CREATE TABLE audit.tool_execution (
    tool_execution_id uuid PRIMARY KEY,
    run_id             uuid NOT NULL REFERENCES audit.agent_run(run_id),
    tool_name          text NOT NULL,
    tool_arguments     jsonb NOT NULL,
    result_metadata    jsonb,
    started_at         timestamptz NOT NULL,
    completed_at       timestamptz,
    status             text NOT NULL,
    error_code         text
);
```

Store tool-result metadata and references, but avoid duplicating massive result payloads inside every message.

Keep LangGraph checkpoint tables in a separate schema such as:

```text
agent_state
```

---

# 10. Write actions and approval

Read-only actions can execute automatically:

* Search locations
* Explain scores
* Compare candidates
* Move the map
* Open charts
* Retrieve methodology

Reversible, low-risk actions can generally execute and show an undo option:

* Save a location
* Add to a comparison
* Change a temporary map filter

Require confirmation for:

* Permanently changing project scoring preferences
* Removing saved locations
* Deleting a project
* Sharing or publishing a report
* Later paid data purchases or external submissions

LangGraph supports pausing execution before selected tool calls and resuming after the user approves, edits or rejects the proposed action. ([Docs by LangChain][6])

---

# 11. Guardrails

Implement these outside the prompt:

### Tool security

* No arbitrary SQL
* No arbitrary URLs
* Pydantic validation for every tool input
* City of Melbourne geographic bounds
* Maximum result counts
* Database timeouts
* User/project ownership checks
* Separate read and write tools

### Factuality

* Quantitative claims require evidence references
* No source means no numerical claim
* Include score and feature versions
* Include source dates
* State when coverage is weak
* Distinguish observed, estimated and projected metrics

### Recommendation language

The agent should say:

> Based on the selected criteria, this is one of the stronger analysed locations.

Not:

> This café will be successful.

RetailScout cannot initially observe important variables such as:

* Rent
* Premises condition
* Lease terms
* Customer spending
* Venue visibility
* Local reputation
* Operator capability
* Detailed zoning or permit eligibility

These omissions should be surfaced in recommendations.

### Prompt injection

Council documents, business descriptions and user uploads are untrusted content.

* Never allow retrieved documents to redefine tools or system behaviour.
* Strip or isolate instructions found inside retrieved text.
* Tools should return data, not executable prompts.
* Avoid passing complete source documents when only a relevant section is needed.

---

# 12. Evaluation

Create an offline test set before launch.

## Core evaluation categories

| Category             | Example                                                      |
| -------------------- | ------------------------------------------------------------ |
| Search correctness   | Does the shortlist satisfy every hard constraint?            |
| Ranking fidelity     | Do returned locations match deterministic backend ranking?   |
| Explanation fidelity | Are all stated numbers present in the tool result?           |
| Comparison quality   | Does the explanation correctly describe differences?         |
| UI accuracy          | Does “show the top three” highlight exactly three locations? |
| Context handling     | Does “this location” resolve to the selected map cell?       |
| Source attribution   | Are score version and data dates correct?                    |
| Uncertainty          | Does the agent disclose weak pedestrian coverage?            |
| Safety               | Does it avoid guarantees of commercial success?              |
| Permission control   | Are sensitive actions confirmed?                             |

Start with approximately:

```text
50 location-search queries
30 score-explanation queries
20 comparison queries
20 map-control queries
20 methodology questions
20 multi-turn conversations
```

Use deterministic Python graders wherever possible. Use model-based grading only for qualities such as clarity, usefulness and whether uncertainty was communicated appropriately. Current evaluation APIs support both executable Python graders and model-based graders. ([OpenAI Platform][7])

---

# 13. Suggested project structure

```text
backend/app/
├── agent/
│   ├── agent.py
│   ├── state.py
│   ├── context.py
│   ├── prompts/
│   │   ├── system.md
│   │   └── explanation.md
│   ├── tools/
│   │   ├── location_search.py
│   │   ├── score.py
│   │   ├── pedestrian.py
│   │   ├── businesses.py
│   │   ├── transport.py
│   │   ├── developments.py
│   │   ├── projects.py
│   │   └── map_actions.py
│   ├── schemas/
│   │   ├── requests.py
│   │   ├── responses.py
│   │   └── events.py
│   ├── middleware/
│   │   ├── authorisation.py
│   │   ├── context_injection.py
│   │   ├── evidence_validation.py
│   │   ├── tool_limits.py
│   │   └── logging.py
│   └── evaluation/
│       ├── datasets/
│       ├── graders/
│       └── runner.py
│
├── api/
│   └── chat.py
│
├── services/
│   ├── location_search.py
│   ├── scoring.py
│   ├── explanation.py
│   └── comparison.py
│
└── repositories/
```

---

# 14. MVP scope

For the first version, implement only:

1. Explain the selected location.
2. Search for locations using conversational criteria.
3. Compare up to three locations.
4. Highlight results and modify filters on the map.
5. Answer methodology and data-source questions.
6. Save locations to the active project.
7. Persist chat threads.
8. Show evidence, source dates and confidence.
9. Log agent runs and tool calls.
10. Run an offline evaluation suite.

Defer:

* Multi-agent architecture
* Autonomous background research
* Voice conversation
* General web browsing
* Natural-language SQL
* Automatic business-plan generation
* Financial revenue forecasting
* Fully autonomous project modification
* Complex long-term user memory

## Final architecture decision

For RetailScout’s City of Melbourne MVP:

```text
One LangChain create_agent
        │
        ├── Runs inside FastAPI
        ├── Uses Postgres-backed thread persistence
        ├── Calls narrow typed domain tools
        ├── Never accesses SQL directly
        ├── Returns structured text, cards and map actions
        └── Uses RAG only for documents and methodology

PostGIS
        │
        ├── Performs filtering
        ├── Performs spatial search
        ├── Returns ranked candidates
        └── Remains the source of truth for every score

Next.js
        │
        ├── Streams agent events
        ├── Renders predefined components
        ├── Applies validated map actions
        └── Keeps the map as the primary interface
```

The most important principle is:

> **The agent interprets user intent and communicates results. The deterministic RetailScout platform performs the actual analysis.**

[1]: https://docs.langchain.com/oss/python/langchain/agents?utm_source=chatgpt.com "Agents - Docs by LangChain"
[2]: https://docs.langchain.com/oss/python/langchain/structured-output?utm_source=chatgpt.com "Structured output - Docs by LangChain"
[3]: https://ai-sdk.dev/docs/ai-sdk-ui/generative-user-interfaces?utm_source=chatgpt.com "AI SDK UI: Generative User Interfaces"
[4]: https://github.com/pgvector/pgvector?utm_source=chatgpt.com "GitHub - pgvector/pgvector: Open-source vector similarity search for Postgres · GitHub"
[5]: https://docs.langchain.com/oss/python/langchain/short-term-memory?utm_source=chatgpt.com "Short-term memory - Docs by LangChain"
[6]: https://docs.langchain.com/oss/python/langchain/human-in-the-loop?utm_source=chatgpt.com "Human-in-the-loop - Docs by LangChain"
[7]: https://platform.openai.com/docs/api-reference/graders?api-mode=chat&utm_source=chatgpt.com "Graders | OpenAI API Reference"
