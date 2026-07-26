"""
Система лицензирования для MindType.
Поддерживает trial период и бессрочные лицензии.
"""

from .entitlement import (
    EntitlementClaims,
    EntitlementLeaseVerifier,
    LeaseValidationError,
)
from .license_manager import LicenseManager, LicenseStatus
from .key_validator import KeyValidator
from .trial import TrialManager

__all__ = [
    "LicenseManager",
    "LicenseStatus",
    "KeyValidator",
    "TrialManager",
]


