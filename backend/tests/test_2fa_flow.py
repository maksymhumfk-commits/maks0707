"""End-to-end tests for the 2FA setup/enable/disable flow (bug-fix verification)."""
import os
import base64
import pytest
import pyotp
import requests

def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    return (url or "").rstrip("/")

BASE_URL = _load_backend_url()
ADMIN_EMAIL = "psymaks249@gmail.com"
ADMIN_PASSWORD = "FozPay2025Admin!"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token")
    assert token
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _ensure_disabled(auth):
    """If 2FA already enabled from a prior run, disable it so tests start clean."""
    st = auth.get(f"{BASE_URL}/api/security/2fa/status", timeout=15).json()
    if st.get("data", {}).get("enabled"):
        # we don't know the secret; force-disable via re-setup is impossible without otp.
        # Attempt disable using any TOTP — will fail; test will be skipped from clean state.
        pytest.skip("2FA already enabled from previous run; manual cleanup needed")


def test_status_endpoint(auth):
    r = auth.get(f"{BASE_URL}/api/security/2fa/status", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] is True
    assert "enabled" in body["data"]


def test_setup_returns_qr_no_500(auth):
    _ensure_disabled(auth)
    r = auth.post(f"{BASE_URL}/api/security/2fa/setup", timeout=20)
    assert r.status_code == 200, f"SETUP returned {r.status_code}: {r.text}"
    data = r.json()["data"]
    assert data["secret"] and len(data["secret"]) >= 16
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    qr = data["qr_data_url"]
    assert qr.startswith("data:image/png;base64,") or qr.startswith("data:image/svg+xml;base64,"), qr[:60]
    # verify base64 payload decodes
    b64 = qr.split(",", 1)[1]
    raw = base64.b64decode(b64)
    assert len(raw) > 50


def test_enable_with_invalid_code_returns_400(auth):
    # ensure a pending secret exists
    auth.post(f"{BASE_URL}/api/security/2fa/setup", timeout=20)
    r = auth.post(f"{BASE_URL}/api/security/2fa/enable",
                  json={"otp": "000000"}, timeout=15)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    assert "Невірний" in r.text or "invalid" in r.text.lower()


def test_enable_and_disable_full_flow(auth):
    # Fresh setup
    r = auth.post(f"{BASE_URL}/api/security/2fa/setup", timeout=20)
    assert r.status_code == 200
    secret = r.json()["data"]["secret"]

    # Enable using valid TOTP
    code = pyotp.TOTP(secret).now()
    r = auth.post(f"{BASE_URL}/api/security/2fa/enable", json={"otp": code}, timeout=15)
    assert r.status_code == 200, f"enable failed: {r.status_code} {r.text}"
    assert r.json()["status"] is True

    # Status shows enabled
    st = auth.get(f"{BASE_URL}/api/security/2fa/status", timeout=15).json()
    assert st["data"]["enabled"] is True

    # Disable with valid code (cleanup)
    code2 = pyotp.TOTP(secret).now()
    r = auth.post(f"{BASE_URL}/api/security/2fa/disable", json={"otp": code2}, timeout=15)
    assert r.status_code == 200, f"disable failed: {r.status_code} {r.text}"

    st = auth.get(f"{BASE_URL}/api/security/2fa/status", timeout=15).json()
    assert st["data"]["enabled"] is False
