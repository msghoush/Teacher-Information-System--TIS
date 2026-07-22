from dataclasses import dataclass


@dataclass(frozen=True)
class CommercialStateSnapshot:
    """M8B-1 data contract only; commercial resolution is introduced later."""

    workspace_uuid: str
    workspace_classification: str
    workspace_lifecycle_status: str
    resolution_status: str = "foundation_only"
