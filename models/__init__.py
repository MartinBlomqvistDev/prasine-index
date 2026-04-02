# Public API for the Prasine Index domain model layer. Importing from this package
# gives access to all Pydantic v2 models, enumerations, and type aliases used
# across the agent pipeline. All inter-agent data exchange must use these models;
# raw strings and untyped dicts are not permitted at agent boundaries.

from models.claim import (
    Claim,
    ClaimCategory,
    ClaimLifecycle,
    ClaimStatus,
    SourceType,
)
from models.company import (
    Company,
    CompanyContext,
    ScoreTrend,
)
from models.evidence import (
    Evidence,
    EvidenceSource,
    EvidenceType,
    VerificationResult,
)
from models.lobbying import (
    LobbyingRecord,
    LobbyingStance,
)
from models.score import (
    GreenwashingScore,
    ScoreCategory,
    ScoreVerdict,
)
from models.trace import (
    AgentName,
    AgentOutcome,
    AgentTrace,
)

__all__ = [
    # trace
    "AgentName",
    "AgentOutcome",
    "AgentTrace",
    # claim
    "Claim",
    "ClaimCategory",
    "ClaimLifecycle",
    "ClaimStatus",
    # company
    "Company",
    "CompanyContext",
    # evidence
    "Evidence",
    "EvidenceSource",
    "EvidenceType",
    # score
    "GreenwashingScore",
    # lobbying
    "LobbyingRecord",
    "LobbyingStance",
    "ScoreCategory",
    "ScoreTrend",
    "ScoreVerdict",
    "SourceType",
    "VerificationResult",
]
