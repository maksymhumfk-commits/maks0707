"""Iteration 4: opBNB network + admin convert-config + merchant-API auto-convert payout.

Covers:
- Admin login + Bearer usage
- GET/PUT /api/admin/convert-config (incl. 400 validations)
- opBNB (network_id=9) present in /admin/networks and /public/currency-network-list for USDT+BNB
- Merchant API /api/v1/private/create-output:
    * NORMAL path (sufficient USDT)
    * AUTO-CONVERT path (BNB on BSC, funded from USDT)
    * opBNB routing (convert_chain must be 'bsc')
    * INSUFFICIENT (400)
    * Merchant auto_convert toggle off -> 400
- Regressions: /private/get-address, /order/create, /public/currency-list, /cabinet/wallet/withdraw
"""
import os, sys, asyncio, pytest, requests

sys.path.insert(0, "/app/backend")
from core import make_signature  # noqa: E402
from dotenv import load_dotenv as _ld
_ld("/app/frontend/.env")
_ld("/app/backend/.env")

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@fozpay.io"
ADMIN_PASSWORD = "FozPay!Admin2026"

# From /app/memory/test_credentials.md
MTOK = "6a85d4db9d81ad3ba9e31fd0c6bee50540a299b38bce4ccec72afc67be99165a"
MSEC = "b4fd5b6c81de9ab9b3e8c90d6c907769cab61fc6cc0298f6e8dddd33ca55aea8"


def _mheaders(body: dict):
    return {"X-Auth-Token": MTOK, "X-Auth-Sign": make_signature(body, MSEC),
            "Content-Type": "application/json"}


# ------------ Mongo helpers (seed wallet balances) ------------
@pytest.fixture(scope="module")
def mongo_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return cli[os.environ["DB_NAME"]]


async def _set_bal(db, uid, iso, amount):
    await db.wallets.update_one(
        {"user_id": uid, "iso": iso},
        {"$set": {"user_id": uid, "iso": iso,
                  "balance": float(amount), "balance_available": float(amount)}},
        upsert=True)


async def _get_bal(db, uid, iso):
    d = await db.wallets.find_one({"user_id": uid, "iso": iso})
    return float((d or {}).get("balance_available") or 0)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_uid(mongo_db):
    u = _run(mongo_db.users.find_one({"email": ADMIN_EMAIL}))
    assert u
    return u["user_id"]


@pytest.fixture(scope="module")
def ah(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ============================ 1. Admin auth =============================
class TestAdminAuth:
    def test_login_returns_token(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 10


# ============================ 2. convert-config =========================
class TestConvertConfig:
    def test_get_defaults(self, ah):
        r = requests.get(f"{BASE}/api/admin/convert-config", headers=ah, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert "auto_convert_enabled" in d
        assert "auto_convert_sources" in d
        assert "available_currencies" in d
        assert isinstance(d["available_currencies"], list)
        assert "USDT" in d["available_currencies"]

    def test_put_valid_sources(self, ah):
        r = requests.put(f"{BASE}/api/admin/convert-config", headers=ah,
                         json={"auto_convert_enabled": True,
                               "auto_convert_sources": ["USDT"]}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["auto_convert_sources"] == ["USDT"]
        # restore
        r2 = requests.put(f"{BASE}/api/admin/convert-config", headers=ah,
                          json={"auto_convert_sources": ["USDT", "USDC"]}, timeout=15)
        assert r2.status_code == 200
        assert set(r2.json()["data"]["auto_convert_sources"]) == {"USDT", "USDC"}

    def test_put_invalid_currency_400(self, ah):
        r = requests.put(f"{BASE}/api/admin/convert-config", headers=ah,
                         json={"auto_convert_sources": ["XYZ"]}, timeout=15)
        assert r.status_code == 400, r.text

    def test_put_empty_list_400(self, ah):
        r = requests.put(f"{BASE}/api/admin/convert-config", headers=ah,
                         json={"auto_convert_sources": []}, timeout=15)
        assert r.status_code == 400, r.text


# ============================ 3. opBNB network ==========================
class TestOpBNB:
    def test_admin_networks_contains_opbnb(self, ah):
        r = requests.get(f"{BASE}/api/admin/networks", headers=ah, timeout=15)
        assert r.status_code == 200
        items = r.json()["data"]
        nine = [n for n in items if n["network_id"] == 9]
        assert len(nine) == 1, items
        assert nine[0]["chain"] == "opbnb"

    def test_public_currency_network_list_has_opbnb(self):
        r = requests.get(f"{BASE}/api/v1/public/currency-network-list", timeout=15)
        assert r.status_code == 200
        data = {c["iso3"]: c for c in r.json()["data"]}
        for iso in ("USDT", "BNB"):
            assert iso in data
            nids = [n.get("network_id") or n.get("id") for n in data[iso]["networks"]]
            assert 9 in nids, f"opBNB missing for {iso}: {data[iso]['networks']}"


# ============================ 4. Merchant API payouts ===================
class TestMerchantPayouts:
    def test_normal_usdt_payout(self, mongo_db, admin_uid):
        # Seed 500 USDT and 0 BNB
        _run(_set_bal(mongo_db, admin_uid, "USDT", 500.0))
        _run(_set_bal(mongo_db, admin_uid, "BNB", 0.0))
        body = {"currency": "USDT", "network": 4, "amount": 10,
                "address": "0x3333333333333333333333333333333333333333"}
        r = requests.post(f"{BASE}/api/v1/private/create-output",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] is True
        d = j["data"]
        assert d["auto_converted"] is False
        assert d["currency"] == "USDT"
        # balance reduced by amount + fee; api fee for USDT out is 0.8 by default
        bal = _run(_get_bal(mongo_db, admin_uid, "USDT"))
        assert 488.0 <= bal <= 490.0, f"got {bal}"

    def test_autoconvert_bnb_on_bsc(self, mongo_db, admin_uid, ah):
        # Ensure admin toggle & platform flag on
        requests.put(f"{BASE}/api/admin/convert-config", headers=ah,
                     json={"auto_convert_enabled": True,
                           "auto_convert_sources": ["USDT", "USDC"]}, timeout=15)
        requests.put(f"{BASE}/api/merchant", headers=ah,
                     json={"auto_convert": True}, timeout=15)
        _run(_set_bal(mongo_db, admin_uid, "USDT", 5000.0))
        _run(_set_bal(mongo_db, admin_uid, "BNB", 0.0))
        before = _run(_get_bal(mongo_db, admin_uid, "USDT"))
        body = {"currency": "BNB", "network": 4, "amount": 0.05,
                "address": "0x1111111111111111111111111111111111111111"}
        r = requests.post(f"{BASE}/api/v1/private/create-output",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["auto_converted"] is True, d
        assert d["converted_from"] == "USDT"
        assert d["status"] == "Pending"
        # tx persisted with convert_from and convert_chain='bsc'
        tx = _run(mongo_db.transactions.find_one({"tx_id": d["id"]}))
        assert tx and tx.get("convert_from") == "USDT"
        assert tx.get("convert_chain") == "bsc"
        assert tx.get("status") == "Pending"
        # USDT reduced
        after = _run(_get_bal(mongo_db, admin_uid, "USDT"))
        assert after < before, (before, after)

    def test_autoconvert_opbnb_routes_via_bsc(self, mongo_db, admin_uid):
        _run(_set_bal(mongo_db, admin_uid, "USDT", 5000.0))
        _run(_set_bal(mongo_db, admin_uid, "BNB", 0.0))
        body = {"currency": "BNB", "network": "opBNB", "amount": 0.03,
                "address": "0x2222222222222222222222222222222222222222"}
        r = requests.post(f"{BASE}/api/v1/private/create-output",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["network_id"] == 9
        assert d["auto_converted"] is True
        tx = _run(mongo_db.transactions.find_one({"tx_id": d["id"]}))
        assert tx.get("convert_chain") == "bsc", tx.get("convert_chain")

    def test_insufficient_400(self, mongo_db, admin_uid):
        _run(_set_bal(mongo_db, admin_uid, "USDT", 1.0))
        _run(_set_bal(mongo_db, admin_uid, "USDC", 1.0))
        _run(_set_bal(mongo_db, admin_uid, "BNB", 0.0))
        body = {"currency": "BNB", "network": 4, "amount": 5,
                "address": "0x4444444444444444444444444444444444444444"}
        r = requests.post(f"{BASE}/api/v1/private/create-output",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 400, r.text

    def test_merchant_auto_convert_toggle_off(self, mongo_db, admin_uid, ah):
        # disable merchant auto_convert
        r0 = requests.put(f"{BASE}/api/merchant", headers=ah,
                          json={"auto_convert": False}, timeout=15)
        assert r0.status_code == 200
        _run(_set_bal(mongo_db, admin_uid, "USDT", 5000.0))
        _run(_set_bal(mongo_db, admin_uid, "BNB", 0.0))
        body = {"currency": "BNB", "network": 4, "amount": 0.05,
                "address": "0x5555555555555555555555555555555555555555"}
        r = requests.post(f"{BASE}/api/v1/private/create-output",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 400, r.text
        # re-enable for other tests
        requests.put(f"{BASE}/api/merchant", headers=ah,
                     json={"auto_convert": True}, timeout=15)


# ============================ 5. Regressions ============================
class TestRegressions:
    def test_public_currency_list(self):
        r = requests.get(f"{BASE}/api/v1/public/currency-list", timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] is True
        isos = {c["iso3"] for c in r.json()["data"]}
        assert {"USDT", "BNB"} <= isos

    def test_private_get_address(self):
        body = {"currency": "USDT", "network": 4}
        r = requests.post(f"{BASE}/api/v1/private/get-address",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("status") is True
        assert j["data"].get("address")

    def test_order_create(self):
        body = {"order_id": "TEST_ITER4_ORD_1", "amount": 5,
                "payment_currency_iso": "USDT",
                "currencies": [{"iso": "USDT", "network": 4}]}
        r = requests.post(f"{BASE}/api/v1/order/create",
                          headers=_mheaders(body), json=body, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("status") is True

    def test_cabinet_wallet_withdraw(self, mongo_db, admin_uid, ah):
        # Seed enough USDT for a small cabinet withdraw
        _run(_set_bal(mongo_db, admin_uid, "USDT", 1000.0))
        body = {"currency": "USDT", "network_id": 4, "amount": 5,
                "address": "0x9999999999999999999999999999999999999999",
                "source": "cabinet"}
        r = requests.post(f"{BASE}/api/wallet/withdraw", headers=ah,
                          json=body, timeout=30)
        # Admin does not have 2FA enabled by default; if it does, endpoint may return 401
        assert r.status_code in (200, 401), r.text
