# Implementation Plan: PitchLens Analyzer

## Overview

Build an AI-powered pitch deck analysis platform with a FastAPI backend orchestrating CrewAI agents for multi-dimension scoring, a React+TypeScript frontend with real-time WebSocket streaming, and a RAG-based follow-up chat. Implementation progresses from foundational infrastructure through core services, agent layer, real-time streaming, and frontend, finishing with integration wiring.

## Tasks

- [x] 1. Set up project structure and core interfaces
  - [x] 1.1 Create backend project structure with FastAPI application scaffold
    - Create directory layout: `app/`, `app/api/`, `app/services/`, `app/agents/`, `app/middleware/`, `app/models/`, `app/db/`, `tests/`
    - Initialize FastAPI app with CORS, lifespan events, and router mounting
    - Add `requirements.txt` with dependencies: fastapi, uvicorn, sqlalchemy, asyncpg, pydantic, python-jose, bcrypt, PyPDF2, crewai, hypothesis, httpx, pytest
    - Create `.env.example` with `LLM_API_KEY`, `LLM_BASE_URL`, `MODEL_ID`, `DATABASE_URL`, `JWT_SECRET`
    - _Requirements: 8.1, 2.1_

  - [x] 1.2 Create Pydantic models and TypeScript interfaces
    - Implement all Pydantic models: `RegisterRequest`, `LoginRequest`, `TokenResponse`, `DeckUploadResponse`, `ExtractedSection`, `ExtractedContent`, `CategoryScore`, `Scorecard`, `ChatRequest`, `ChatResponse`, `EvaluationListItem`, `PaginatedEvaluations`, `PipelineStage`, `WSEvent`
    - Create TypeScript type files: `src/types/auth.ts`, `src/types/scorecard.ts`, `src/types/websocket.ts`, `src/types/chat.ts`
    - _Requirements: 16.1, 16.2, 9.4_

  - [x] 1.3 Create database schema and migration setup
    - Write SQLAlchemy models for: `users`, `refresh_tokens`, `decks`, `analyses`, `scorecards`, `chat_sessions`, `chat_messages`, `deck_embeddings`, `rate_limit_events`
    - Create initial migration script with all tables and indexes
    - Enable pgvector extension in migration
    - _Requirements: 12.1, 2.1_

- [x] 2. Implement authentication service
  - [x] 2.1 Implement user registration and login
    - Create `app/services/auth.py` with `register()`, `login()`, `refresh_token()` functions
    - Password hashing with bcrypt, JWT signing with HS256
    - Access token TTL 15 minutes, refresh token TTL 7 days
    - Auth error responses must not reveal email existence or which credential failed
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 2.2 Implement JWT middleware and token refresh
    - Create dependency `get_current_user` that validates JWT from Authorization header
    - Implement refresh token endpoint that issues new access token
    - Handle expired/revoked refresh tokens with 401 response
    - _Requirements: 1.5, 1.6, 1.7_

  - [x] 2.3 Create auth API routes
    - Create `app/api/auth.py` with routes: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`
    - Wire to auth service, validate request bodies, return `TokenResponse`
    - _Requirements: 1.1, 1.3, 1.6_

  - [ ]* 2.4 Write unit tests for auth service
    - Test JWT generation/verification with specific expiry values
    - Test password validation edge cases (exactly 8 chars, unicode, special chars)
    - Test error responses don't reveal email existence
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Implement rate limiter middleware
  - [x] 3.1 Implement sliding window rate limiter
    - Create `app/middleware/rate_limiter.py` with in-memory sliding window counters
    - Per-user tracking for authenticated requests (10/hour analysis, 60/min general)
    - Per-IP tracking for unauthenticated endpoints (20/5-min for auth endpoints)
    - Return 429 with `Retry-After` header on limit breach
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 3.2 Write property test for rate limiter enforcement
    - **Property 8: Rate Limiter Enforcement**
    - Generate request sequences with varying timestamps; verify requests at/below limit succeed and first request exceeding limit gets 429 with valid Retry-After header
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5**

- [x] 4. Implement prompt injection guard
  - [x] 4.1 Implement injection guard scanner
    - Create `app/services/injection_guard.py` with pattern-based scanner
    - Detect: role-override instructions, system-prompt extraction, delimiter escapes, instruction-override commands
    - Return generic security-violation error without revealing which rule triggered
    - Log attempts with timestamp, user ID, first 500 chars of input
    - Latency budget: <200ms; fail-closed if guard is unavailable
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 4.2 Write property test for injection detection
    - **Property 9: Prompt Injection Detection and Blocking**
    - Generate strings with embedded injection patterns; verify all are blocked with generic error and logged
    - **Validates: Requirements 14.1, 14.2, 14.3**

  - [ ]* 4.3 Write property test for injection guard fail-closed behavior
    - **Property 10: Injection Guard Fail-Closed**
    - Mock guard to raise errors; verify requests are rejected with service-unavailable rather than forwarded
    - **Validates: Requirements 14.5**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement PDF upload and validation
  - [x] 6.1 Implement PDF upload endpoint and file validation
    - Create `POST /api/decks` endpoint accepting multipart file upload
    - Validate: file is valid PDF, ≤20 MB, ≤50 pages (using PyPDF2)
    - Store file in persistent storage, create `decks` DB record
    - Return `DeckUploadResponse` with deck_id and analysis_id
    - Reject unauthenticated requests with auth-required error
    - On storage failure, return error without issuing deck_id
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7_

  - [ ]* 6.2 Write property test for PDF upload validation
    - **Property 13: PDF Upload Validation**
    - Generate files of varying sizes and types; verify non-PDF, >20MB, and >50 page files are rejected without storage or deck_id
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

- [x] 7. Implement CrewAI agent layer
  - [x] 7.1 Implement Extractor Agent
    - Create `app/agents/extractor.py` with CrewAI Agent configuration
    - Parse PDF bytes using PyPDF2, identify section boundaries (headings, font changes, page breaks)
    - Map sections to categories: market, team, business_model, competition, uncategorized
    - Handle partial extraction (images without text) with warnings
    - 30-second timeout with partial results on timeout
    - Return `ExtractedContent` model
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 7.2 Implement Market Scorer Agent
    - Create `app/agents/market_scorer.py` with CrewAI Agent
    - Score market opportunity 1-10 evaluating TAM/SAM/SOM, market timing, growth potential
    - Produce `CategoryScore` with reasoning (50-500 words) and 1-3 suggestions
    - Handle missing market info (score=1) and partial info
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 7.3 Implement Team Scorer Agent
    - Create `app/agents/team_scorer.py` with CrewAI Agent
    - Score team strength 1-10 evaluating founder backgrounds, experience, completeness
    - Produce `CategoryScore` with reasoning (50-300 words) and 1-3 suggestions
    - Handle missing/partial team info
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 7.4 Implement Business Model Scorer Agent
    - Create `app/agents/business_model_scorer.py` with CrewAI Agent
    - Score business model 1-10 evaluating revenue model, unit economics, scalability
    - Produce `CategoryScore` with reasoning (50-300 words) and 1-3 suggestions
    - Handle missing/partial business model info; 30-second timeout
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 7.5 Implement Competition Scorer Agent
    - Create `app/agents/competition_scorer.py` with CrewAI Agent
    - Score competitive positioning 1-10 evaluating landscape awareness, differentiation, defensibility
    - Produce `CategoryScore` with reasoning (50-300 words) and 1-3 suggestions
    - Handle missing/partial competition info
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 7.6 Implement Verdict Aggregator Agent
    - Create `app/agents/verdict_aggregator.py` with CrewAI Agent
    - Compute overall score as mean of available scores rounded to nearest integer
    - Produce verdict summary (100-500 words), category ranking (descending score, alphabetical tie-break)
    - Handle partial scorecards (fewer than 4 categories) with failed_categories list
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 7.7 Write property test for CategoryScore schema validation
    - **Property 5: CategoryScore Schema Validation**
    - Generate scores, reasoning lengths, and suggestion counts at boundaries; verify schema enforcement
    - **Validates: Requirements 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3**

  - [ ]* 7.8 Write property test for overall score computation
    - **Property 3: Overall Score Computation**
    - Generate 1-4 tuples of integers in [1,10]; verify mean rounded to nearest integer and failed categories tracked
    - **Validates: Requirements 9.1, 9.5**

  - [ ]* 7.9 Write property test for category ranking sort order
    - **Property 4: Category Ranking Sort Order**
    - Generate category-score pairs with ties; verify descending score order with alphabetical tie-break
    - **Validates: Requirements 9.3**

- [x] 8. Implement pipeline orchestrator
  - [x] 8.1 Implement pipeline orchestrator service
    - Create `app/services/orchestrator.py` managing analysis lifecycle
    - Sequential: Extractor → Parallel: [4 scorers] → Verdict Aggregator
    - Retry logic: 1 retry per scorer on failure with 30-second timeout per retry
    - Total pipeline timeout: 120 seconds
    - Abort pipeline if Extractor fails (cancel downstream agents)
    - Update `analyses` table status at each stage transition
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 8.2 Write property test for pipeline execution order
    - **Property 6: Pipeline Execution Order Invariant**
    - Use mocked agents; generate random completion/failure sequences; verify Extractor before scorers, scorers before aggregator, no scoring on Extractor failure
    - **Validates: Requirements 8.1, 8.4**

  - [ ]* 8.3 Write property test for scorer retry behavior
    - **Property 7: Scorer Retry on Failure**
    - Generate failure scenarios; verify exactly one retry within 30s and failed category marking on persistent failure
    - **Validates: Requirements 8.3**

- [x] 9. Implement scorecard serialization and persistence
  - [x] 9.1 Implement scorecard serialization, validation, and DB persistence
    - Create `app/services/scorecard_service.py` with serialize/deserialize/validate functions
    - Validate JSON against schema before persisting (reject non-conforming documents)
    - Store full scorecard_json in scorecards table
    - Descriptive parsing errors for malformed or missing fields
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [ ]* 9.2 Write property test for scorecard round-trip serialization
    - **Property 1: Scorecard Serialization Round-Trip**
    - Generate random valid Scorecards; verify serialize→deserialize produces equal objects
    - **Validates: Requirements 16.1, 16.2, 16.3**

  - [ ]* 9.3 Write property test for malformed scorecard rejection
    - **Property 2: Malformed Scorecard JSON Rejection**
    - Generate JSON with randomly missing/invalid fields; verify descriptive error identifying the problem field
    - **Validates: Requirements 16.4, 16.5**

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement WebSocket real-time streaming
  - [x] 11.1 Implement WebSocket manager and event streaming
    - Create `app/services/ws_manager.py` managing per-analysis WebSocket connections
    - Event types: `stage_change`, `heartbeat`, `partial_result`, `complete`, `error`
    - Emit events at stage transitions within 1 second, heartbeats every 5 seconds
    - Support JWT auth via query param for WebSocket connections
    - Handle reconnection: resume from current pipeline state
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 11.2 Integrate WebSocket with pipeline orchestrator
    - Wire orchestrator stage transitions to WebSocket event emissions
    - Stream partial results as each scorer completes
    - Pipeline continues regardless of WebSocket connection state
    - _Requirements: 10.2, 10.3, 10.4_

- [x] 12. Implement RAG engine and chat
  - [x] 12.1 Implement RAG engine with pgvector
    - Create `app/services/rag_engine.py`
    - Chunk extracted deck content into ~500-token segments
    - Generate and store embeddings in pgvector via `deck_embeddings` table
    - On query: retrieve top-k relevant chunks, construct context, send to LLM
    - Maintain session context (up to 20 messages, evict oldest when exceeding cap)
    - Ground answers in deck content and scoring results with citations
    - Return out-of-scope response for questions outside deck content
    - Never expose system metadata or implementation details
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 12.2 Create chat API endpoint
    - Implement `POST /api/decks/{deck_id}/chat` with JWT auth
    - Validate message length (≤1000 chars)
    - Route through injection guard before RAG processing
    - Return `ChatResponse` with response and cited_sections
    - _Requirements: 11.1, 11.2_

  - [ ]* 12.3 Write property test for chat context window cap
    - **Property 15: Chat Context Window Cap**
    - Generate message sequences of varying lengths; verify context capped at 20, oldest evicted, all persisted
    - **Validates: Requirements 11.4**

- [x] 13. Implement evaluation history
  - [x] 13.1 Implement evaluation history endpoints
    - Create `GET /api/evaluations` with pagination (default page_size=20), sorted by creation date descending
    - Create `GET /api/evaluations/{eval_id}` returning full scorecard
    - Filter by deck_id when provided
    - Return 403 without resource existence hint for cross-user access
    - Log unauthorized access attempts
    - Return empty list with zero total when no evaluations exist
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ]* 13.2 Write property test for evaluation history pagination
    - **Property 11: Evaluation History Pagination and Sorting**
    - Generate evaluation lists of varying sizes; verify correct pagination, descending date sort, user isolation
    - **Validates: Requirements 12.2, 12.4**

  - [ ]* 13.3 Write property test for deck filter
    - **Property 12: Evaluation History Deck Filter**
    - Generate evaluations across random deck IDs; verify filter returns only matching deck evaluations
    - **Validates: Requirements 12.6**

  - [ ]* 13.4 Write property test for cross-user access denial
    - **Property 16: Cross-User Evaluation Access Denied**
    - Generate user/evaluation ownership pairs; verify 403 for cross-user without revealing existence
    - **Validates: Requirements 12.4**

- [x] 14. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Implement frontend application
  - [x] 15.1 Set up React+TypeScript+Vite+Tailwind project with routing and theme
    - Initialize Vite project with React and TypeScript
    - Configure Tailwind CSS with dark mode (class strategy)
    - Set up React Router with routes: `/login`, `/register`, `/upload`, `/analysis/:id`, `/history`, `/scorecard/:id`
    - Implement `ThemeToggle` component respecting OS preference, persisting to localStorage
    - _Requirements: 15.1, 15.2_

  - [x] 15.2 Implement auth pages and token management
    - Create Login and Register pages with form validation
    - Implement token storage, auto-attach to requests, redirect on expiry
    - Create auth context/hook for app-wide auth state
    - _Requirements: 1.1, 1.3, 1.5_

  - [x] 15.3 Implement PDF upload component
    - Create drag-and-drop upload with progress bar
    - Client-side validation: file type (PDF only), size (≤20MB)
    - On success, navigate to analysis progress view
    - _Requirements: 2.1, 15.2_

  - [x] 15.4 Implement WebSocket analysis progress component
    - Create WebSocket client connecting to `/ws/analysis/{analysis_id}`
    - Display current pipeline stage with animated indicators
    - Show partial results as scorers complete
    - Reconnection with exponential backoff (1s start, max 3 attempts)
    - Fallback to REST on connection failure with manual refresh option
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 15.6_

  - [x] 15.5 Implement scorecard display component
    - Render score gauges with color coding (1-3 red, 4-6 amber, 7-10 green)
    - Expandable reasoning and suggestions per category
    - Overall verdict summary and category ranking
    - Error state for invalid scores outside 1-10 range
    - _Requirements: 15.3, 15.4, 9.4_

  - [ ]* 15.6 Write property test for score color range mapping
    - **Property 14: Score Color Range Mapping**
    - Generate integers 1-10; verify 1-3→low, 4-6→mid, 7-10→high with no overlap or gaps
    - Note: Implement this as a Python test validating the color mapping logic (can also be mirrored in Vitest)
    - **Validates: Requirements 15.3**

  - [x] 15.7 Implement chat interface component
    - Message thread with user/assistant distinction
    - Character counter (1000 char limit)
    - Loading states during RAG retrieval
    - Display cited sections in responses
    - _Requirements: 11.1, 11.2, 15.2_

  - [x] 15.8 Implement evaluation history view
    - Paginated list of past evaluations with deck name, score, date
    - Deck name filter
    - Click-through to full scorecard
    - Empty state when no evaluations
    - _Requirements: 12.2, 12.3, 12.5, 15.2_

  - [x] 15.9 Ensure responsive layout across breakpoints
    - Test and adjust layout from 375px to 2560px
    - All interactive elements reachable without horizontal scrolling
    - Text readable without zooming, no content clipped or overlapped
    - _Requirements: 15.5_

- [x] 16. Integration wiring and final endpoint connections
  - [x] 16.1 Wire deck upload to pipeline orchestrator triggering
    - On successful upload, create analysis record and trigger orchestrator
    - Return 202 Accepted with deck_id and analysis_id
    - Frontend connects WebSocket after receiving 202
    - _Requirements: 2.1, 8.1, 10.1_

  - [x] 16.2 Wire scorecard retrieval endpoint
    - Implement `GET /api/decks/{deck_id}/scorecard` returning persisted scorecard
    - Enforce ownership (user can only access own scorecards)
    - _Requirements: 9.4, 12.4_

  - [x] 16.3 Wire injection guard into chat and upload pipelines
    - Apply injection guard to chat messages before RAG processing
    - Apply injection guard to extracted deck content before passing to agents
    - _Requirements: 14.1, 14.2, 14.5_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties defined in the design's Correctness Properties section
- Unit tests validate specific examples and edge cases
- Backend uses Python (FastAPI, CrewAI, Hypothesis); Frontend uses TypeScript (React, Vite, Tailwind, Vitest)
- LLM configuration is via environment variables: `LLM_API_KEY`, `LLM_BASE_URL`, `MODEL_ID`
- All core implementation tasks are complete; only optional property-based test tasks remain

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.2", "4.2", "4.3"] },
    { "id": 3, "tasks": ["6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1", "7.2", "7.3", "7.4", "7.5", "7.6"] },
    { "id": 5, "tasks": ["7.7", "7.8", "7.9", "8.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "11.1"] },
    { "id": 8, "tasks": ["11.2", "12.1"] },
    { "id": 9, "tasks": ["12.2", "12.3", "13.1"] },
    { "id": 10, "tasks": ["13.2", "13.3", "13.4"] },
    { "id": 11, "tasks": ["15.1"] },
    { "id": 12, "tasks": ["15.2", "15.3"] },
    { "id": 13, "tasks": ["15.4", "15.5", "15.6", "15.7", "15.8"] },
    { "id": 14, "tasks": ["15.9", "16.1", "16.2", "16.3"] }
  ]
}
```
