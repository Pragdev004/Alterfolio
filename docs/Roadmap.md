# Alterfolio Roadmap

_Last updated: 2026-07-27_

## Vision
Build an AI-powered investor copilot/twin that records user trades, models alternative decisions, and continuously explains performance drivers with market/news context.

## Near-term (0-2 months)

- Stabilize backend domain boundaries (trade, portfolio, AI workflow).
- Expand test coverage for AI tool-calling paths.
- Harden provider error handling/retries for market + news integrations.
- Add baseline auth strategy proposal and implementation plan.
- Ship API documentation and developer onboarding quickstart.

## Mid-term (2-4 months)

- Introduce frontend MVP for portfolio/trade visibility + AI insights.
- Add background jobs for heavy analysis workflows.
- Support richer portfolio analytics (risk concentration, sector exposure).
- Persist AI analysis history for longitudinal comparisons.

## Longer-term (4-8 months)

- Implement “AI twin” simulation and shadow-trade comparisons.
- Add decision-quality scoring and post-trade review loops.
- Enable configurable strategy personas / policy constraints.
- Prepare for multi-user tenancy and production hardening.

## Ongoing tracks

- Reliability: observability, alerts, SLOs.
- Quality: unit/integration contract tests, CI gates.
- Security: secret handling, authn/authz, auditability.
- Product: UX validation and feedback loops.

## Roadmap maintenance rules

When scope changes:
1. Update this roadmap.
2. Reflect concrete checkpoints in `docs/milestones.md`.
3. Record meaningful tradeoffs in `docs/decisions.md`.
