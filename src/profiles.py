"""
SBS EnergyLink - Device Profile Loader
Loads Modbus register profiles from config/device_profiles/*.yaml.

Profiles define the register map for a specific Modbus device type.
Drop a YAML file in the directory and it appears in the wizard selector
automatically — no code changes needed.
"""

import logging
import os
from typing import Optional

import yaml

log = logging.getLogger(__name__)

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SRC_DIR)
PROFILES_DIR = os.path.join(_PROJECT_DIR, "config", "device_profiles")


def list_profiles() -> list[dict]:
    """Return list of available profiles with metadata (no registers).

    Returns:
        [{"file": "tesla_bess.yaml", "name": "Tesla BESS / EPMS",
          "manufacturer": "Tesla", "model": "Megapack"}, ...]
    """
    profiles = []
    if not os.path.isdir(PROFILES_DIR):
        return profiles

    for fname in sorted(os.listdir(PROFILES_DIR)):
        if not fname.endswith((".yaml", ".yml")):
            continue
        try:
            path = os.path.join(PROFILES_DIR, fname)
            with open(path) as f:
                data = yaml.safe_load(f)
            profiles.append({
                "file": fname,
                "name": data.get("name", fname),
                "manufacturer": data.get("manufacturer", ""),
                "model": data.get("model", ""),
                "register_count": len(data.get("registers", [])),
            })
        except Exception as e:
            log.warning(f"Skipping invalid profile {fname}: {e}")

    return profiles


def load_profile(filename: str) -> Optional[dict]:
    """Load a full profile by filename.

    Returns the complete YAML dict including registers, or None if
    the file doesn't exist or is invalid.
    """
    path = os.path.join(PROFILES_DIR, filename)
    if not os.path.isfile(path):
        log.error(f"Profile not found: {path}")
        return None

    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        log.error(f"Failed to load profile {filename}: {e}")
        return None


def load_profile_by_name(name: str) -> Optional[dict]:
    """Load a profile by its display name."""
    for p in list_profiles():
        if p["name"] == name:
            return load_profile(p["file"])
    return None
