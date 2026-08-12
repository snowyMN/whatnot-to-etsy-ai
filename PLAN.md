## Updated Plan: Controlled Local AI Workflow

Goal: turn the project into a portfolio-quality example of practical AI engineering for ecommerce and resale. The system should show clean boundaries between factual analysis, marketing reasoning, writing, validation, observability, and human approval while staying simple enough to run locally.

### Architecture
Whatnot import -> Raw listing + cached images -> Product Analysis Agent -> Verified Product Facts -> Marketing Strategy Agent -> Marketplace-neutral Listing Writer -> Listing Validator -> Human Review UI -> Future Marketplace Adapters

### Current Milestone
- ProductAnalysisAgent runs on local multimodal model input.
- MarketingStrategyAgent is separate from factual analysis.
- ListingWriter consumes verified facts plus strategy.
- ListingValidator checks for unsupported claims and review issues.
- Review UI surfaces AI workflow steps, prompt versions, strategy, draft, and validation.
- Human approval remains the final gate.

### Next Milestones
- Add deterministic marketplace adapters without automatic publishing.
- Add more validator rules and local eval fixtures.
- Add README screenshots and architecture walkthrough.
- Connect future listing performance data back to strategy evaluation.

### Constraints
- Do not collapse all responsibilities into one prompt.
- Do not trust free-form model output.
- Do not auto-publish.
- Do not overengineer with autonomous agents or live tool use before there is a business need.
