"""Provider-agnostic financial research data access backed by OpenBB."""

from .canonical import (
    AssetIdentity,
    AssetResearchData,
    CanonicalAssetType,
    DataQuality,
    FreshnessStatus,
    FundamentalsData,
    MacroSeries,
    PriceSeries,
    QualityStatus,
    ResearchProvenance,
)
from .openbb_client import (
    OpenBBResearchClient,
    ResearchConfigurationError,
    ResearchData,
    ResearchError,
    ResearchInvalidSymbolError,
    ResearchMissingCredentialError,
    ResearchNoDataError,
    ResearchProviderError,
    ResearchProviderSettings,
    ResearchRateLimitError,
    ResearchUnsupportedEndpointError,
)
from .service import CanonicalResearchService
from .serialization import canonical_json, to_jsonable

__all__ = [
    "OpenBBResearchClient",
    "CanonicalResearchService",
    "AssetIdentity",
    "AssetResearchData",
    "CanonicalAssetType",
    "DataQuality",
    "FreshnessStatus",
    "FundamentalsData",
    "MacroSeries",
    "PriceSeries",
    "QualityStatus",
    "ResearchProvenance",
    "canonical_json",
    "to_jsonable",
    "ResearchConfigurationError",
    "ResearchData",
    "ResearchError",
    "ResearchInvalidSymbolError",
    "ResearchMissingCredentialError",
    "ResearchNoDataError",
    "ResearchProviderError",
    "ResearchProviderSettings",
    "ResearchRateLimitError",
    "ResearchUnsupportedEndpointError",
]
