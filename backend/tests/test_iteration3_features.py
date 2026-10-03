"""Iteration 3 (Jan 2026) backend tests for FozPay request:
- Public registration toggle + gating
- Balance chart ranges (1Д/1Т/1М/1Р)
- Platform fees all 0
- Payout address validation (EVM 400)
- Checkout invoice creation (for UI test)
"""
import os
import time
import urllib.parse
import pytest
import requests
from pathlib import Path

# Load REACT_APP_BACKEND_URL from frontend/.env
env_path = Path("/app/frontend/.env")
for line in env_path.read_text().splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
        break
else:
    raise RuntimeError("REACT_APP_BACKEND_URL not found")

ADMIN_EMAIL = "psymaks249@gmail.com"
ADMIN_PASSWORD = "FozPay2025Admin!"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# -------------------- Registration toggle --------------------
class TestRegistrationToggle:
    def _set(self, admin_h, enabled: bool):
        r = requests.put(f"{BASE_URL}/api/admin/registration",
                         headers=admin_h, json={"enabled": enabled}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["enabled"] is enabled

    def test_status_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/auth/registration-status", timeout=20)
        assert r.status_code == 200
        assert "enabled" in r.json()

    def test_disabled_blocks_register(self, admin_h):
        self._set(admin_h, False)
        r = requests.get(f"{BASE_URL}/api/auth/registration-status", timeout=20)
        assert r.json()["enabled"] is False
        r = requests.post(f"{BASE_URL}/api/auth/register",
                          json={"email": f"test_blocked_{int(time.time())}@example.com",
                                "password": "secret123"}, timeout=20)
        assert r.status_code == 403

    def test_enabled_allows_register_then_disable(self, admin_h):
        self._set(admin_h, True)
        r = requests.get(f"{BASE_URL}/api/auth/registration-status", timeout=20)
        assert r.json()["enabled"] is True
        email = f"TEST_reg_{int(time.time())}@example.com"
        r = requests.post(f"{BASE_URL}/api/auth/register",
                          json={"email": email, "password": "secret123", "name": "Test"}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert data["user"]["email"] == email.lower()
        assert data["user"].get("role") in (None, "user")
        # cleanup user
        from pymongo import MongoClient
        # revert
        self._set(admin_h, False)
        r2 = requests.get(f"{BASE_URL}/api/auth/registration-status", timeout=20)
        assert r2.json()["enabled"] is False


# -------------------- Balance chart ranges --------------------
class TestBalanceChart:
    @pytest.mark.parametrize("rng,expected", [("1Д", 24), ("1Т", 7), ("1М", 30), ("1Р", 12)])
    def test_chart_points(self, admin_h, rng, expected):
        q = urllib.parse.quote(rng)
        r = requests.get(f"{BASE_URL}/api/me/chart?range={q}", headers=admin_h, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert isinstance(data, list)
        assert len(data) == expected, f"range {rng} expected {expected} got {len(data)}"
        assert all("t" in p and "value" in p for p in data)


# -------------------- Platform fees are 0 --------------------
class TestPlatformFees:
    def test_all_fees_zero(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/platform-fees", headers=admin_h, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json().get("data", r.json())
        assert float(d.get("deposit_fee", 0)) == 0
        assert float(d.get("withdrawal_fee_cabinet", 0)) == 0
        assert float(d.get("withdrawal_fee_api", 0)) == 0
        for iso, v in (d.get("deposit_fee_by_iso") or {}).items():
            assert float(v) == 0, f"deposit_fee_by_iso {iso}={v}"
        for iso, v in (d.get("withdrawal_fee_by_iso") or {}).items():
            assert float(v.get("cabinet", 0)) == 0, f"withdrawal cabinet {iso}"
            assert float(v.get("api", 0)) == 0, f"withdrawal api {iso}"


# -------------------- Payout address validation --------------------
class TestPayoutAddressValidation:
    def test_malformed_evm_rejected(self, admin_h):
        r = requests.post(f"{BASE_URL}/api/wallet/withdraw", headers=admin_h,
                          json={"currency": "USDT", "network_id": 6, "amount": 1,
                                "address": "0x123"}, timeout=20)
        assert r.status_code == 400, r.text
        assert "EVM" in r.text or "Некоректна" in r.text

    def test_valid_evm_passes_format_check(self, admin_h):
        # well-formed address; may fail on insufficient balance, which is fine
        valid = "0x1111111111111111111111111111111111111111"
        r = requests.post(f"{BASE_URL}/api/wallet/withdraw", headers=admin_h,
                          json={"currency": "USDT", "network_id": 6, "amount": 1000000,
                                "address": valid}, timeout=20)
        # must not be an address-format error
        assert "Некоректна EVM" not in r.text, r.text


# -------------------- Checkout invoice (used by UI test) --------------------
class TestInvoiceForCheckout:
    def test_create_invoice(self, admin_h):
        r = requests.post(f"{BASE_URL}/api/invoices", headers=admin_h,
                          json={"order_id": f"TST_{int(time.time())}", "price": 5,
                                "payment_currency_iso": "USDT",
                                "description": "iter3 test"}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json().get("data", r.json())
        assert data.get("id")
        # keep id for frontend test
        Path("/tmp/iter3_invoice_id.txt").write_text(data["id"])
