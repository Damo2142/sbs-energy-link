"""
SBS EnergyLink - License / Tier System
Reads /etc/sbs-energylink/license.key to determine product tier.

Part numbers:
  SBS-EL-BESS-001  — EnergyLink BESS (Tesla Megapack only)
  SBS-EL-UNIV-001  — EnergyLink Universal (any Modbus device)
  SBS-EL-PRO-001   — EnergyLink Pro (Universal + Excel import)

The license file is written during first_boot.sh provisioning.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

LICENSE_PATH = "/etc/sbs-energylink/license.key"

VALID_PART_NUMBERS = {
    "SBS-EL-BESS-001": "bess",
    "SBS-EL-UNIV-001": "universal",
    "SBS-EL-PRO-001": "pro",
}

TIER_NAMES = {
    "bess": "BESS",
    "universal": "UNIVERSAL",
    "pro": "PRO",
}


@dataclass
class License:
    product: str = ""
    serial: str = ""
    tier: str = "bess"
    issued: str = ""
    site: str = ""
    valid: bool = False
    path: str = LICENSE_PATH

    @property
    def tier_name(self) -> str:
        return TIER_NAMES.get(self.tier, "BESS")

    @property
    def is_universal_or_pro(self) -> bool:
        return self.tier in ("universal", "pro")

    @property
    def is_pro(self) -> bool:
        return self.tier == "pro"


def load_license() -> License:
    """Load license from /etc/sbs-energylink/license.key.

    DEV_MODE with no license file defaults to PRO tier.
    Missing license in production defaults to BESS (safe default).
    """
    lic = License()

    if not os.path.exists(LICENSE_PATH):
        if os.environ.get("DEV_MODE") == "1":
            log.info("DEV_MODE: no license file, defaulting to PRO tier")
            lic.tier = "pro"
            lic.product = "SBS-EL-PRO-001"
            lic.serial = "DEV-0000"
            lic.valid = True
            return lic
        log.warning(
            f"License file not found at {LICENSE_PATH} — "
            f"defaulting to BESS tier"
        )
        lic.tier = "bess"
        lic.valid = False
        return lic

    try:
        with open(LICENSE_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip().upper()
                val = val.strip()
                if key == "PRODUCT":
                    lic.product = val
                elif key == "SERIAL":
                    lic.serial = val
                elif key == "TIER":
                    lic.tier = val if val in TIER_NAMES else "bess"
                elif key == "ISSUED":
                    lic.issued = val
                elif key == "SITE":
                    lic.site = val

        # Validate product number matches tier
        expected_tier = VALID_PART_NUMBERS.get(lic.product)
        if expected_tier and expected_tier == lic.tier:
            lic.valid = True
        elif expected_tier:
            log.warning(
                f"License product {lic.product} expects tier "
                f"'{expected_tier}' but got '{lic.tier}'"
            )
            lic.tier = expected_tier
            lic.valid = True
        else:
            log.warning(f"Unknown product number: {lic.product}")
            lic.valid = False

        log.info(
            f"License loaded: {lic.product} / {lic.serial} / "
            f"tier={lic.tier_name} / valid={lic.valid}"
        )
        return lic

    except Exception as e:
        log.error(f"Failed to read license file: {e}")
        lic.valid = False
        return lic
