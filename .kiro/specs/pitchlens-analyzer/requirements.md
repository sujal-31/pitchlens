# Requirements Document

## Introduction

PitchLens is an AI-powered Startup Pitch Deck Analyzer that enables users to upload pitch deck PDFs and receive investor-grade scorecards. The system uses a multi-agent architecture (CrewAI) with specialized scoring agents for market opportunity, team strength, business model viability, and competitive landscape. The platform provides per-category scores with reasoning, improvement suggestions, follow-up chat via RAG, evaluation history, and real-time streaming of analysis progress.

## Glossary

- **System**: The PitchLens application as a whole, encompassing backend and frontend
- **Backend**: The FastAPI server responsible for API endpoints, orchestration, and data persistence
- **Frontend**: The React+TypeScript+Vite+Tailwind single-page application
- **Extractor_Agent**: The CrewAI agent responsible for parsing PDF content into structured text sections
- **Market_Scorer**: The CrewAI agent that evaluates market opportunity, TAM/SAM/SOM, and market timing
- **Team_Scorer**: The CrewAI agent that evaluates founder backgrounds, team composition, and relevant experience
- **Business_Model_Scorer**: The CrewAI agent that evaluates revenue model, unit economics, and scalability
- **Competition_Scorer**: The CrewAI agent that evaluates competitive positioning, differentiation, and moat
- **Verdict_Aggregator**: The CrewAI agent that combines individual scores into a final scorecard with overall verdict
- **Scorecard**: A structured evaluation result containing per-category scores (1-10), reasoning, and suggestions
- **Deck**: A pitch deck PDF document uploaded by a user
- **RAG_Engine**: The retrieval-augmented generation component that enables follow-up questions over deck content
- **Auth_Service**: The JWT-based authentication and authorization service
- **Rate_Limiter**: The middleware that enforces per-user request rate limits
- **Injection_Guard**: The component that detects and blocks prompt injection attempts in user inputs
- **WebSocket_Stream**: The WebSocket connection used to stream real-time analysis progress to the Frontend

## Requirements

### Requirement 1: User Authentication

**User Story:** As a user, I want to register and log in securely, so that my evaluations are private and persistent.

#### Acceptance Criteria

1. WHEN a user submits registration credentials containing a valid email address and a password of at least 8 characters, THE Auth_Service SHALL create a new user account and return a JWT access token that expires after 15 minutes
2. IF a user submits registration credentials with an already-registered email or a password shorter than 8 characters, THEN THE Auth_Service SHALL reject the request with an error message indicating the validation failure without revealing whether the email is already in use
3. WHEN a user submits valid login credentials, THE Auth_Service SHALL return a JWT access token that expires after 15 minutes and a refresh token that expires after 7 days
4. WHEN a user submits invalid login credentials, THE Auth_Service SHALL return a 401 Unauthorized response without revealing whether the email or password was incorrect
5. WHEN a JWT token has expired, THE Auth_Service SHALL reject the request with a 401 response and the Frontend SHALL redirect to the login page
6. WHEN a valid refresh token is submitted, THE Auth_Service SHALL issue a new JWT access token without requiring re-authentication
7. IF an expired or revoked refresh token is submitted, THEN THE Auth_Service SHALL reject the request with a 401 response and require the user to re-authenticate

### Requirement 2: PDF Upload and Validation

**User Story:** As a user, I want to upload a pitch deck PDF, so that it can be analyzed by the system.

#### Acceptance Criteria

1. WHEN an authenticated user uploads a valid PDF file of 50 pages or fewer and 20 MB or less, THE Backend SHALL accept the file, store it in persistent storage associated with the authenticated user, and return a unique deck identifier
2. IF a user uploads a file that is not a valid PDF or contains zero extractable pages, THEN THE Backend SHALL reject the upload with an error message indicating the reason for rejection
3. IF a user uploads a PDF exceeding 20 MB, THEN THE Backend SHALL reject the upload with an error message indicating the file size limit has been exceeded
4. IF a user uploads a PDF exceeding 50 pages, THEN THE Backend SHALL reject the upload with an error message indicating the page limit has been exceeded
5. WHEN a PDF is successfully stored, THE Extractor_Agent SHALL parse the PDF into structured text sections within 30 seconds for files up to 50 pages
6. IF an unauthenticated user attempts to upload a file, THEN THE Backend SHALL reject the request with an authentication-required error
7. IF the Backend fails to store the uploaded PDF in persistent storage, THEN THE Backend SHALL return a storage-failure error and SHALL NOT return a deck identifier

### Requirement 3: PDF Text Extraction

**User Story:** As a system operator, I want pitch deck content reliably extracted, so that scoring agents receive accurate input.

#### Acceptance Criteria

1. WHEN the Extractor_Agent receives a valid PDF of 50 pages or fewer and 20 MB or less, THE Extractor_Agent SHALL extract all readable text content and identify section boundaries based on heading styles, font-size changes, or page breaks within 30 seconds
2. WHEN the Extractor_Agent encounters a PDF with embedded images but no selectable text, THE Extractor_Agent SHALL return a partial-extraction warning indicating the page numbers that lack text content
3. IF the Extractor_Agent fails to parse a PDF due to corruption, THEN THE Extractor_Agent SHALL return an extraction-failed error with the failure reason and preserve any previously extracted content from the pipeline unchanged
4. WHEN extraction completes successfully, THE Extractor_Agent SHALL produce a structured output containing extracted sections mapped to scoring categories (market, team, business model, competition), with any content that does not map to a defined category placed in an "uncategorized" section
5. IF extraction does not complete within 30 seconds, THEN THE Extractor_Agent SHALL terminate the extraction, return the structured output for any content successfully processed before the timeout, and include a timeout warning indicating the page reached at time of termination

### Requirement 4: Market Opportunity Scoring

**User Story:** As a user, I want an expert evaluation of the market opportunity in my deck, so that I understand how investors would perceive it.

#### Acceptance Criteria

1. WHEN the Market_Scorer receives extracted deck content, THE Market_Scorer SHALL produce an integer score from 1 to 10 for market opportunity
2. WHEN the Market_Scorer produces a score, THE Market_Scorer SHALL provide a reasoning paragraph of 50 to 500 words explaining the score by addressing TAM/SAM/SOM presence and specificity, market timing indicators, and growth potential evidence found in the deck
3. WHEN the Market_Scorer produces a score, THE Market_Scorer SHALL provide 1 to 3 improvement suggestions, each specific to the deck content and referencing a gap or weakness identified in the reasoning
4. IF the extracted content contains no identifiable market information, THEN THE Market_Scorer SHALL assign a score of 1 and provide a reasoning paragraph stating that market information is missing from the deck
5. IF the extracted content contains partial market information where one or more of TAM/SAM/SOM, market timing, or growth potential evidence is absent, THEN THE Market_Scorer SHALL note each missing element in the reasoning paragraph

### Requirement 5: Team Strength Scoring

**User Story:** As a user, I want an expert evaluation of my team presentation, so that I can strengthen how I position my team for investors.

#### Acceptance Criteria

1. WHEN the Team_Scorer receives extracted deck content, THE Team_Scorer SHALL produce an integer score from 1 to 10 for team strength
2. THE Team_Scorer SHALL provide a reasoning paragraph of 50 to 300 words explaining the score based on founder backgrounds, relevant experience, and team completeness
3. THE Team_Scorer SHALL provide 1 to 3 improvement suggestions, where each suggestion references a specific gap or weakness identified in the team presentation and includes a concrete recommended action
4. IF the extracted content contains no identifiable team information, THEN THE Team_Scorer SHALL assign a score of 1 and state that team information is missing
5. IF the extracted content contains partial team information, THEN THE Team_Scorer SHALL assign a score from 2 to 10 based on the quality of available team information and note which team details are missing

### Requirement 6: Business Model Scoring

**User Story:** As a user, I want an expert evaluation of my business model, so that I can refine my revenue strategy before pitching.

#### Acceptance Criteria

1. WHEN the Business_Model_Scorer receives extracted deck content, THE Business_Model_Scorer SHALL produce an integer score from 1 to 10 for business model viability within 30 seconds of receiving the input
2. THE Business_Model_Scorer SHALL provide a reasoning paragraph of 50 to 300 words explaining the score, addressing each of the following factors: revenue model clarity, unit economics, and scalability
3. THE Business_Model_Scorer SHALL provide 1 to 3 improvement suggestions, each specific to the content of the evaluated deck and referencing a concrete aspect of the business model that can be changed or added
4. IF the extracted content contains no identifiable business model information, THEN THE Business_Model_Scorer SHALL assign a score of 1 and state that business model information is missing
5. IF the extracted content contains partial business model information where one or more of revenue model, unit economics, or scalability is absent, THEN THE Business_Model_Scorer SHALL assign a score from 2 to 10 based on the factors present and note which factors are missing in the reasoning paragraph

### Requirement 7: Competition Analysis Scoring

**User Story:** As a user, I want an expert evaluation of my competitive positioning, so that I can better articulate my differentiation.

#### Acceptance Criteria

1. WHEN the Competition_Scorer receives extracted deck content, THE Competition_Scorer SHALL produce an integer score from 1 to 10 for competitive positioning
2. THE Competition_Scorer SHALL provide a reasoning paragraph of 50 to 300 words explaining the score, referencing competitive landscape awareness, differentiation, and defensibility
3. THE Competition_Scorer SHALL provide 1 to 3 improvement suggestions, each containing a specific action the user can take to improve their competitive positioning in the deck
4. IF the extracted content contains no identifiable competition information, THEN THE Competition_Scorer SHALL assign a score of 1 and state that competition information is missing
5. IF the extracted content contains partial competition information covering fewer than three of the evaluation dimensions (competitive landscape awareness, differentiation, defensibility), THEN THE Competition_Scorer SHALL include a note identifying which dimensions are missing from the deck

### Requirement 8: Agent Orchestration

**User Story:** As a system operator, I want agents to execute in the correct order with parallel scoring, so that analysis is both accurate and fast.

#### Acceptance Criteria

1. WHEN a deck analysis is initiated, THE Backend SHALL execute the Extractor_Agent first, then execute Market_Scorer, Team_Scorer, Business_Model_Scorer, and Competition_Scorer in parallel, then execute the Verdict_Aggregator after all four scoring agents have either completed successfully or exhausted their retry attempt
2. WHEN all four scoring agents complete successfully, THE Verdict_Aggregator SHALL combine all individual scores into a final Scorecard
3. IF any scoring agent fails during execution, THEN THE Backend SHALL retry that agent once within 30 seconds and, if still failing, mark that category as failed and proceed to the Verdict_Aggregator with available scores to produce a partial Scorecard containing an error indicator for the failed category
4. IF the Extractor_Agent fails to produce structured output, THEN THE Backend SHALL immediately cancel any queued or in-progress scoring agents, abort the analysis pipeline, and return an extraction-failure error to the caller
5. THE Backend SHALL complete the full analysis pipeline (extraction through aggregation), including any retry attempts, within 120 seconds for a deck of up to 20 pages and up to 20 MB in file size

### Requirement 9: Verdict Aggregation

**User Story:** As a user, I want a combined scorecard with an overall verdict, so that I get a holistic view of my pitch deck quality.

#### Acceptance Criteria

1. WHEN the Verdict_Aggregator receives all four category scores, THE Verdict_Aggregator SHALL compute an overall integer score from 1 to 10 using equal weighting (25% per category) rounded to the nearest integer
2. THE Verdict_Aggregator SHALL produce a final verdict summary paragraph of 100 to 500 words synthesizing strengths and weaknesses across all categories
3. THE Verdict_Aggregator SHALL rank the categories from strongest to weakest by descending numeric score, using alphabetical order to break ties
4. THE Scorecard SHALL contain: overall score, per-category scores, per-category reasoning, per-category suggestions, overall verdict summary, and category ranking
5. IF the Verdict_Aggregator receives fewer than four category scores due to agent failures, THEN THE Verdict_Aggregator SHALL compute the overall score using equal weighting across available categories and note which categories are missing

### Requirement 10: Real-Time Progress Streaming

**User Story:** As a user, I want to see analysis progress in real time, so that I know the system is working and can follow along.

#### Acceptance Criteria

1. WHEN a deck analysis begins, THE Backend SHALL establish a WebSocket_Stream connection to the Frontend within 2 seconds of analysis initiation
2. WHILE the analysis pipeline is executing, THE Backend SHALL send progress events through the WebSocket_Stream indicating the current stage (extracting, scoring_market, scoring_team, scoring_business_model, scoring_competition, aggregating) within 1 second of each stage transition and SHALL send heartbeat events at least every 5 seconds while a stage is actively processing
3. WHEN a scoring agent completes, THE Backend SHALL stream that agent's partial result to the Frontend within 2 seconds of completion
4. IF the WebSocket connection drops, THEN THE Frontend SHALL attempt reconnection with exponential backoff (starting at 1 second, maximum 3 attempts) and THE Backend SHALL resume streaming from the current pipeline state upon reconnection
5. IF all reconnection attempts fail, THEN THE Frontend SHALL display an error message and offer a manual refresh option to retrieve the final result via REST API

### Requirement 11: Follow-Up Chat (RAG)

**User Story:** As a user, I want to ask follow-up questions about my deck after analysis, so that I can dive deeper into specific feedback.

#### Acceptance Criteria

1. WHEN a user sends a follow-up question of 1000 characters or fewer for an analyzed deck, THE RAG_Engine SHALL retrieve relevant sections from the deck and provide an answer within 15 seconds
2. THE RAG_Engine SHALL ground all answers in the actual deck content and scoring results, citing which deck section or score category the answer references
3. WHEN a user asks a question that cannot be answered using the deck content or scoring results, THE RAG_Engine SHALL respond indicating that the question is outside the scope of the deck analysis
4. THE RAG_Engine SHALL maintain conversation context for up to 20 messages within a single chat session for coherent multi-turn dialogue
5. IF the RAG_Engine fails to retrieve relevant content or encounters an internal error, THEN THE RAG_Engine SHALL return a service-error response indicating the failure without exposing internal details
6. THE RAG_Engine SHALL NOT expose internal system metadata, debugging information, or implementation details in any response to the user

### Requirement 12: Evaluation History

**User Story:** As a user, I want to view my past evaluations, so that I can track improvements across deck iterations.

#### Acceptance Criteria

1. THE Backend SHALL persist every completed Scorecard associated with the authenticated user and deck, including a creation timestamp
2. WHEN a user requests evaluation history, THE Backend SHALL return a paginated list of past Scorecards sorted by creation date descending, with a default page size of 20 items, where each list item includes the deck name, overall score, and creation timestamp
3. WHEN a user selects a past evaluation, THE Frontend SHALL display the full Scorecard with all per-category scores, reasoning, suggestions, overall verdict summary, and category ranking
4. IF a user attempts to access an evaluation that does not belong to them, THEN THE Backend SHALL return a 403 Forbidden response without revealing whether the evaluation exists, and SHALL log the unauthorized access attempt with timestamp and user identifier for security monitoring
5. WHEN a user requests evaluation history and no past evaluations exist, THE Backend SHALL return an empty list with zero total count
6. WHEN a user requests evaluation history with a deck identifier filter, THE Backend SHALL return only evaluations associated with that specific deck

### Requirement 13: Rate Limiting

**User Story:** As a system operator, I want to limit request rates per user, so that the system remains available and cost-effective.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL enforce a maximum of 10 deck analysis requests per user within a sliding 1-hour window
2. THE Rate_Limiter SHALL enforce a maximum of 60 API requests per user per sliding 1-minute window for all non-analysis endpoints excluding authentication endpoints
3. WHEN a user exceeds the rate limit, THE Rate_Limiter SHALL return a 429 Too Many Requests response with a Retry-After header indicating the number of seconds until the user may retry
4. THE Rate_Limiter SHALL track limits per authenticated user, not per IP address
5. FOR unauthenticated endpoints (registration, login), THE Rate_Limiter SHALL enforce a maximum of 20 requests per IP address per sliding 5-minute window

### Requirement 14: Prompt Injection Protection

**User Story:** As a system operator, I want to guard against prompt injection attacks, so that malicious inputs cannot manipulate agent behavior.

#### Acceptance Criteria

1. WHEN user input is received (chat messages or deck content passed to agents), THE Injection_Guard SHALL scan the input for prompt injection patterns including role-override instructions, system-prompt extraction attempts, delimiter escape sequences, and instruction-override commands
2. IF the Injection_Guard detects a prompt injection attempt, THEN THE Injection_Guard SHALL block the request, discard the malicious input before it reaches any agent, and return a security-violation error to the user without revealing which detection rule was triggered
3. THE Injection_Guard SHALL log all detected injection attempts with timestamp, user identifier, and the first 500 characters of the offending input for security auditing
4. THE Injection_Guard SHALL operate without adding more than 200ms latency to any request
5. IF the Injection_Guard is unavailable or encounters an internal error during scanning, THEN THE Backend SHALL reject the request and return a service-unavailable error rather than forwarding unscanned input to agents

### Requirement 15: Frontend User Interface

**User Story:** As a user, I want a clean, responsive interface with dark mode, so that I can comfortably use the tool in any environment.

#### Acceptance Criteria

1. THE Frontend SHALL provide a dark mode and a light mode with a visible toggle control, defaulting to the operating system preference when no stored preference exists, and persisting the user's choice in local storage
2. THE Frontend SHALL display the upload interface, analysis progress, scorecard results, and chat on a single-page application without full page reloads
3. WHEN a Scorecard is displayed, THE Frontend SHALL render each category score as a numeric value (1-10) with a filled bar or gauge proportional to the score, where scores 1-3 display a low-range color, 4-6 display a mid-range color, and 7-10 display a high-range color, accompanied by the reasoning text and suggestion list
4. IF a category score falls outside the valid 1-10 range, THEN THE Frontend SHALL display an error state for that category instead of rendering the score visualization
5. THE Frontend SHALL be responsive on screen widths from 375px to 2560px such that all interactive elements are reachable without horizontal scrolling, all text remains readable without zooming, and no content is clipped or overlapped
6. WHEN the system is processing an analysis, THE Frontend SHALL display a loading state showing the current pipeline stage name (extracting, scoring market, scoring team, scoring business model, scoring competition, aggregating) as received from the WebSocket_Stream

### Requirement 16: Scorecard Serialization (Round-Trip)

**User Story:** As a developer, I want Scorecards to serialize and deserialize reliably, so that data integrity is maintained across storage and retrieval.

#### Acceptance Criteria

1. THE Backend SHALL serialize Scorecard objects to JSON for storage and API responses using a defined schema that includes all Scorecard fields
2. THE Backend SHALL deserialize stored JSON back into Scorecard objects without data loss, preserving all numeric scores, string fields, arrays, and nested structures
3. FOR ALL valid Scorecard objects, serializing then deserializing SHALL produce an object where every field is equal to the original (round-trip property)
4. WHEN a Scorecard JSON document is malformed or missing required fields, THE Backend SHALL return a descriptive parsing error identifying which field is invalid or absent
5. THE Backend SHALL validate Scorecard JSON against the defined schema before persisting, rejecting any document that does not conform
