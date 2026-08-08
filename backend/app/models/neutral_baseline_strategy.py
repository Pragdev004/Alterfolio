from dataclasses import dataclass


@dataclass(frozen=True)
class NeutralBaselineStrategyDefinition:
    key: str
    version: str


MAINTAIN_CURRENT_ALLOCATION_STRATEGY = NeutralBaselineStrategyDefinition(
    key="maintain_current_allocation",
    version="1.0",
)
