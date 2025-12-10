"""
Система лицензирования для MindType.
Поддерживает trial период и бессрочные лицензии.
"""

from .license_manager import LicenseManager, LicenseStatus
from .key_validator import KeyValidator, generate_license_key
from .trial import TrialManager

__all__ = [
    "LicenseManager",
    "LicenseStatus",
    "KeyValidator",
    "generate_license_key",
    "TrialManager",
]



