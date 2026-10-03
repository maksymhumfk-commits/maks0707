"""Tests for the current review request - FozPay feature verification"""
import os
import random
import string
import pytest
import requests

def _load_backend_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if not url:
        env_path = '/app/frontend/.env'
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith('REACT_APP_BACKEND_URL='):
                    url = line.split('=', 1)[1].strip()
                    break
    return url.rstrip('/') if url else ''
BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "psymaks249@gmail.com"
ADMIN_PASS = "FozPay2025Admin!"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# --- Registration gating -----------------------------------------
def test_registration_status_public():
    r = requests.get(f"{API}/auth/registration-status", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)


def test_admin_registration_toggle_flow(admin_headers):
    # Get current
    def unwrap(j):
        return j.get("data", j) if isinstance(j, dict) else j

    r = requests.get(f"{API}/admin/registration", headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    assert "enabled" in unwrap(r.json())

    # Enable
    r = requests.put(f"{API}/admin/registration", headers=admin_headers, json={"enabled": True}, timeout=10)
    assert r.status_code == 200, r.text
    assert unwrap(r.json()).get("enabled") is True

    # Register works
    rand = ''.join(random.choices(string.ascii_lowercase+string.digits, k=8))
    email = f"newclient+{rand}@test.com"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "secret123", "name": "Test"}, timeout=15)
    assert r.status_code == 200, f"register should succeed: {r.status_code} {r.text}"
    assert "access_token" in r.json()

    # Disable
    r = requests.put(f"{API}/admin/registration", headers=admin_headers, json={"enabled": False}, timeout=10)
    assert r.status_code == 200
    assert unwrap(r.json()).get("enabled") is False
    rand2 = ''.join(random.choices(string.ascii_lowercase+string.digits, k=8))
    r = requests.post(f"{API}/auth/register", json={"email": f"blocked+{rand2}@test.com", "password": "secret123", "name": "X"}, timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# --- Platform fees 0 ---------------------------------------------
def test_platform_fees_all_zero(admin_headers):
    r = requests.get(f"{API}/admin/platform-fees", headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    if isinstance(data, dict) and "data" in data and "deposit_fee" in data.get("data", {}):
        data = data["data"]
    assert data.get("deposit_fee") == 0
    assert data.get("withdrawal_fee_api") == 0
    assert data.get("withdrawal_fee_cabinet") == 0
    # Check iso dict values if present
    for key in ("deposit_fee_by_iso", "withdrawal_fee_api_by_iso", "withdrawal_fee_cabinet_by_iso",
                "deposit_fee_iso", "withdrawal_fee_api_iso", "withdrawal_fee_cabinet_iso",
                "swap_fee_by_iso"):
        iso = data.get(key)
        if isinstance(iso, dict):
            for k, v in iso.items():
                assert v == 0, f"{key}[{k}] expected 0 got {v}"


# --- Balance chart ranges ----------------------------------------
@pytest.mark.parametrize("rng,expected_count", [("1Д", 24), ("1Т", 7), ("1М", 30), ("1Р", 12)])
def test_balance_chart_ranges(admin_headers, rng, expected_count):
    r = requests.get(f"{API}/me/chart", headers=admin_headers, params={"range": rng}, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json().get("data")
    assert isinstance(data, list), f"data not a list: {r.json()}"
    assert len(data) == expected_count, f"range {rng}: expected {expected_count} points, got {len(data)}"
    for p in data:
        assert "t" in p and "value" in p
    # Label format sanity
    first_t = data[0]["t"]
    if rng == "1Д":
        assert ":" in first_t  # HH:00
    elif rng in ("1Т", "1М"):
        assert first_t.count(".") == 1 and len(first_t) == 5  # dd.mm
    elif rng == "1Р":
        assert first_t.count(".") == 1 and len(first_t) == 5  # mm.yy


# --- Strict withdrawal address validation ------------------------
def test_withdraw_invalid_evm_address(admin_headers):
    # Polygon = network_id 6 => EVM
    r = requests.post(f"{API}/wallet/withdraw", headers=admin_headers,
                      json={"currency": "USDT", "network_id": 6, "amount": 1, "address": "0x123"}, timeout=15)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    assert "EVM" in r.text, f"error should mention EVM: {r.text}"


def test_withdraw_wrong_length_evm_address(admin_headers):
    r = requests.post(f"{API}/wallet/withdraw", headers=admin_headers,
                      json={"currency": "USDT", "network_id": 6, "amount": 1,
                            "address": "0x1234567890abcdef1234567890abcdef1234567"}, timeout=15)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_withdraw_address_with_spaces(admin_headers):
    r = requests.post(f"{API}/wallet/withdraw", headers=admin_headers,
                      json={"currency": "USDT", "network_id": 6, "amount": 1,
                            "address": "  0x1234567890abcdef1234567890abcdef12345678  "}, timeout=15)
    # Spaces should be rejected OR normalized then address is valid.
    # Per request: "well-formed-but-wrong-length or spaced address must also be rejected"
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# Cleanup already done inside test_admin_registration_toggle_flow (leaves disabled)
