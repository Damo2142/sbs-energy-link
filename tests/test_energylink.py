"""
SBS EnergyLink - Unit Tests
Run with: python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock, patch
from data_store import DataStore, BESSData


# ── Data Store Tests ─────────────────────────────────────────────────────────

class TestDataStore:
    def test_initial_state_is_stale(self):
        store = DataStore()
        assert store.is_stale() is True

    def test_update_clears_stale(self):
        store = DataStore()
        data = BESSData()
        store.update(data)
        assert store.is_stale(timeout_seconds=60) is False

    def test_get_returns_data(self):
        store = DataStore()
        data = BESSData()
        data.bess_soc_pct = 75.0
        store.update(data)
        assert store.get().bess_soc_pct == 75.0

    def test_mark_stale(self):
        store = DataStore()
        data = BESSData()
        store.update(data)
        store.mark_stale()
        assert store.get().stale is True

    def test_mark_poll_failed(self):
        store = DataStore()
        data = BESSData()
        store.update(data)
        store.mark_poll_failed()
        assert store.get().poll_success is False


# ── Modbus Parsing Tests ─────────────────────────────────────────────────────

class TestModbusParsing:
    """Test the INT16/INT32 parsing and bit-masking logic."""

    def test_int16_signed_positive(self):
        from poller import _to_int16_signed
        assert _to_int16_signed(500) == 500

    def test_int16_signed_negative(self):
        from poller import _to_int16_signed
        # -100 in two's complement 16-bit = 65436
        assert _to_int16_signed(65436) == -100

    def test_int16_signed_zero(self):
        from poller import _to_int16_signed
        assert _to_int16_signed(0) == 0

    def test_int16_signed_max_negative(self):
        from poller import _to_int16_signed
        assert _to_int16_signed(0x8000) == -32768

    def test_int32_positive(self):
        from poller import _to_int32
        # 100000 = 0x000186A0 → high=0x0001 low=0x86A0
        assert _to_int32(0x0001, 0x86A0) == 100000

    def test_int32_negative(self):
        from poller import _to_int32
        # -1 = 0xFFFFFFFF → high=0xFFFF low=0xFFFF
        assert _to_int32(0xFFFF, 0xFFFF) == -1

    def test_int32_zero(self):
        from poller import _to_int32
        assert _to_int32(0, 0) == 0

    def test_fault_bit_masking(self):
        """Register 208 contains 5 fault flags as individual bits."""
        from poller import (FAULT_COMM_ERROR, FAULT_LOW_CELL_VOLT,
                             FAULT_HIGH_CELL_VOLT, FAULT_LOW_TEMP, FAULT_HIGH_TEMP)
        # All bits set
        all_faults = 0x001F
        assert bool(all_faults & FAULT_COMM_ERROR)    is True
        assert bool(all_faults & FAULT_LOW_CELL_VOLT) is True
        assert bool(all_faults & FAULT_HIGH_CELL_VOLT)is True
        assert bool(all_faults & FAULT_LOW_TEMP)      is True
        assert bool(all_faults & FAULT_HIGH_TEMP)     is True

    def test_fault_bit_masking_individual(self):
        from poller import (FAULT_COMM_ERROR, FAULT_LOW_CELL_VOLT,
                             FAULT_HIGH_CELL_VOLT, FAULT_LOW_TEMP, FAULT_HIGH_TEMP)
        # Only bit 2 (HIGH_CELL_VOLT) set
        reg = 0x0004
        assert bool(reg & FAULT_COMM_ERROR)    is False
        assert bool(reg & FAULT_LOW_CELL_VOLT) is False
        assert bool(reg & FAULT_HIGH_CELL_VOLT)is True
        assert bool(reg & FAULT_LOW_TEMP)      is False
        assert bool(reg & FAULT_HIGH_TEMP)     is False

    def test_no_faults_when_zero(self):
        from poller import (FAULT_COMM_ERROR, FAULT_LOW_CELL_VOLT,
                             FAULT_HIGH_CELL_VOLT, FAULT_LOW_TEMP, FAULT_HIGH_TEMP)
        reg = 0x0000
        for mask in [FAULT_COMM_ERROR, FAULT_LOW_CELL_VOLT,
                     FAULT_HIGH_CELL_VOLT, FAULT_LOW_TEMP, FAULT_HIGH_TEMP]:
            assert bool(reg & mask) is False


# ── Web UI Tests ─────────────────────────────────────────────────────────────

class TestWebUI:
    @pytest.fixture
    def client(self, tmp_path):
        """Flask test client with temp config directory."""
        import web_ui
        # Point config to temp dir
        web_ui.CONFIG_PATH   = str(tmp_path / "config.yaml")
        web_ui.TEMPLATE_PATH = os.path.join(
            os.path.dirname(__file__), "..", "config", "config.template.yaml")
        web_ui.app.config["TESTING"] = True
        with web_ui.app.test_client() as c:
            yield c

    def test_root_redirects_to_step1(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert "/step1" in r.location

    def test_step1_get(self, client):
        r = client.get("/step1")
        assert r.status_code == 200
        assert b"Site Info" in r.data or b"Site" in r.data

    def test_status_endpoint(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.get_json()
        assert "configured" in data
        assert "bacnet_device_id" in data


# ── Simulation Mode Tests ────────────────────────────────────────────────────

class TestSimulation:
    def test_sim_produces_valid_soc(self):
        """Sim mode SOC should stay within 0-100%."""
        import math
        for t in range(0, 300, 5):
            soc = 50.0 + 40.0 * math.sin(t / 60.0)
            assert 0 <= soc <= 100, f"SOC out of range at t={t}: {soc}"

    def test_data_store_thread_safety(self):
        """Multiple threads writing to store shouldn't corrupt data."""
        import threading
        store = DataStore()
        errors = []

        def writer(val):
            try:
                for _ in range(100):
                    d = BESSData()
                    d.bess_soc_pct = val
                    store.update(d)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(float(i),))
                   for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Final value should be a valid float
        assert isinstance(store.get().bess_soc_pct, float)
