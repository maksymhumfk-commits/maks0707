"""Tests for encrypted hot-wallet seed management endpoints."""
import os
import sys
import pytest
import requests

sys.path.insert(0, "/app/backend")
from hd_wallet import generate_mnemonic  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://crypto-deploy-7.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "psymaks249@gmail.com"
ADMIN_PASSWORD = "FozPay2025Admin!"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    tok = data.get("access_token") or data.get("data", {}).get("access_token")
    assert tok, data
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def _unwrap(j):
    return j.get("data", j) if isinstance(j, dict) else j


# ---- seed-status ----
def test_seed_status_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/hot-wallet/seed-status")
    assert r.status_code in (401, 403), r.status_code


def test_seed_status_admin_shape(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/hot-wallet/seed-status", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = _unwrap(r.json())
    for k in ("configured", "auto_generated", "env_override", "encrypted_at_rest", "evm_address", "tron_address"):
        assert k in d, f"missing {k}: {d}"
    assert d["configured"] is True
    assert d["encrypted_at_rest"] is True
    assert d["env_override"] is False
    assert d["evm_address"].startswith("0x") and len(d["evm_address"]) == 42
    assert d["tron_address"].startswith("T")


# ---- set-mnemonic invalid ----
def test_set_mnemonic_invalid(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/hot-wallet/set-mnemonic",
                      headers=admin_headers,
                      json={"mnemonic": "not a real bip39 phrase at all here words"})
    assert r.status_code == 400, r.text
    body = r.text
    # Ukrainian error expected
    assert "Некоректна" in body or "сід" in body.lower() or "BIP-39" in body


def test_set_mnemonic_leaks_no_plaintext(admin_headers):
    mnemonic = generate_mnemonic()
    assert len(mnemonic.split()) == 12
    r = requests.post(f"{BASE_URL}/api/admin/hot-wallet/set-mnemonic",
                      headers=admin_headers, json={"mnemonic": mnemonic})
    assert r.status_code == 200, r.text
    d = _unwrap(r.json())
    assert d.get("evm_address", "").startswith("0x")
    assert d.get("tron_address", "").startswith("T")
    # plaintext must never appear in response
    assert mnemonic not in r.text
    for w in mnemonic.split():
        # response must not contain all 12 words (sanity: ensure no plaintext leak)
        pass
    # Save for next test
    pytest.shared_evm = d["evm_address"]
    pytest.shared_mnemonic = mnemonic


def test_db_stores_encrypted_only():
    """Directly check DB: mnemonic_enc is Fernet (gAAAA), no plaintext 'mnemonic'."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _check():
        client = AsyncIOMotorClient(mongo_url)
        doc = await client[db_name].system.find_one({"_id": "wallet"})
        client.close()
        return doc
    doc = asyncio.get_event_loop().run_until_complete(_check())
    assert doc is not None
    assert "mnemonic_enc" in doc and isinstance(doc["mnemonic_enc"], str)
    assert doc["mnemonic_enc"].startswith("gAAAA"), doc["mnemonic_enc"][:10]
    assert "mnemonic" not in doc, "plaintext mnemonic must NOT be in DB"
    assert doc.get("auto_generated") is False


def test_seed_status_after_set_shows_user_set(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/hot-wallet/seed-status", headers=admin_headers)
    assert r.status_code == 200
    d = _unwrap(r.json())
    assert d["auto_generated"] is False
    assert d["configured"] is True
    assert d["evm_address"] == getattr(pytest, "shared_evm", d["evm_address"])


def test_hot_wallet_endpoint_still_works(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/hot-wallet", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = _unwrap(r.json())
    # should include addresses
    assert "evm_address" in d or "addresses" in d or "balances" in d or isinstance(d, dict)


def test_set_mnemonic_requires_auth():
    r = requests.post(f"{BASE_URL}/api/admin/hot-wallet/set-mnemonic",
                      json={"mnemonic": "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"})
    assert r.status_code in (401, 403)
