# Changelog

All notable changes to SaathiCare are recorded here.

## [0.1.0] - 2026-08-28

### Added

- Survivor-facing Android-compatible PWA: onboarding, account access, daily wellbeing check-in, journal, trend history, profile editing, SOS/support and resource views.
- Counselor portal: dashboard metrics, people search, risk history, counselor notes, alerts, review status, and resource-library management.
- FastAPI + SQLite service with token authentication and documented REST endpoints.
- Explainable Random Forest screening-risk prototype trained solely on deterministic synthetic questionnaire data.
- Safety disclaimers, architecture documentation, database schema, local setup instructions, and seeded demonstration users.

### Safety

- All predictions are explicitly presented as screening risk estimates, not diagnoses.
- The project contains no real patient or victim data.
