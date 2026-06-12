"""
Service layer — business logic between CLI/API and storage.

Rules:
- All workspace-scoped services take RequestContext as first argument.
- Global services (report_service) do NOT take ctx.
- Services are pure Python; no FastAPI, no HTTP.
- Core analyzers (role_analyzer, extractor, classifier) are NOT called here —
  they belong in analysis_service (Sprint 3).
"""
