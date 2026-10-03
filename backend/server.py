import os
import asyncio
import logging
import random
import re
import string
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Body
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from core import (
    db, hash_password, verify_password, create_access_token, set_auth_cookie,
    set_session_cookie, clear_auth_cookies, get_current_user, exchange_emergent_session,
    make_signature, new_token, new_secret,
)
import catalog
from catalog import (
    CURRENCIES, NETWORKS, FIAT_CURRENCIES, FIAT_RATES_USD, PRICES_USD, PRICE_CHANGE,
    STATUS_MAP, STATUS_NAME_TO_ID, networks_for, commission_for,
)
from hd_wallet import generate_mnemonic, seed_from_mnemonic, derive_address, is_valid_mnemonic
from wallet_crypto import encrypt_mnemonic, decrypt_mnemonic
from admin_router import (
    admin_router, sec_router,
    get_platform_settings, add_to_pool, is_network_enabled, check_user_2fa,
    deposit_fee_for, swap_fee_percent_for, withdrawal_fee_for,
    convert_sources_for, auto_convert_enabled, registration_enabled,
    confirmations_required,
)
import aml as aml_mod
import binance_prices
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fozpay")

app = FastAPI(title="FozPay API")
_seed = {"bytes": None}


@app.middleware("http")
async def _collapse_double_slashes(request: Request, call_next):
    """Tolerate merchant apiUrl values with a trailing slash (which yield URLs like
    `/api//v1/private/create-output`). Collapse repeated slashes so routing still
    matches instead of returning 404 Not Found."""
    path = request.scope.get("path", "")
    if "//" in path:
        fixed = re.sub(r"/{2,}", "/", path)
        request.scope["path"] = fixed
        request.scope["raw_path"] = fixed.encode("utf-8")
    return await call_next(request)



# ============================ helpers ============================
def now_ts() -> int:
    return int(time.time())


def gen_id(n=8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def client_ip_of(request: Request) -> str:
    """Real client IP behind the k8s ingress: first entry of X-Forwarded-For,
    then X-Real-IP, then the socket peer."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip", "")
    if xri:
        return xri.strip()
    return request.client.host if request.client else ""


async def next_index(chain: str) -> int:
    doc = await db.counters.find_one_and_update(
        {"_id": chain}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return doc["seq"]


async def ensure_seed():
    if _seed["bytes"] is not None:
        return
    env_m = os.environ.get("WALLET_MNEMONIC", "").strip()
    if env_m:
        mnemonic = env_m
    else:
        sysdoc = await db.system.find_one({"_id": "wallet"})
        if sysdoc and sysdoc.get("mnemonic_enc"):
            # Основний шлях: зашифрований мнемонік у БД
            mnemonic = decrypt_mnemonic(sysdoc["mnemonic_enc"])
        elif sysdoc and sysdoc.get("mnemonic"):
            # Міграція legacy: був відкритий мнемонік → шифруємо й прибираємо plaintext
            mnemonic = sysdoc["mnemonic"]
            await db.system.update_one(
                {"_id": "wallet"},
                {"$set": {"mnemonic_enc": encrypt_mnemonic(mnemonic)},
                 "$unset": {"mnemonic": ""}})
            logger.warning("Migrated plaintext mnemonic in DB to encrypted (mnemonic_enc).")
        else:
            mnemonic = generate_mnemonic()
            await db.system.update_one(
                {"_id": "wallet"},
                {"$set": {"mnemonic_enc": encrypt_mnemonic(mnemonic),
                          "auto_generated": True}}, upsert=True)
            logger.warning("Generated new HD wallet mnemonic (encrypted in DB).")
    _seed["bytes"] = seed_from_mnemonic(mnemonic)
    # Hot wallet = HD EVM address at index 0 (per-user deposit addresses start at
    # index 1, see next_index). Its private key is derivable from the encrypted
    # seed, so the platform can auto-fund gas and sweep deposits to it on every EVM
    # network without any hardcoded/plaintext treasury key. Respects an explicit
    # TREASURY_EVM override from the environment if one is provided.
    import recovery as _rec
    if not os.environ.get("TREASURY_EVM"):
        hot_evm = derive_address(_seed["bytes"], "ethereum", 0)["address"]
        _rec.TREASURY_EVM = hot_evm
        logger.info(f"Hot wallet EVM address (HD index 0): {hot_evm}")


async def allocate_address(user_id: str, iso: str, network_id: int, invoice_id=None) -> dict:
    await ensure_seed()
    net = NETWORKS.get(network_id)
    if not net:
        raise HTTPException(400, "Network not found")
    chain = net["chain"]
    if invoice_id is None:
        existing = await db.addresses.find_one(
            {"user_id": user_id, "iso": iso, "network_id": network_id, "invoice_id": None},
            {"_id": 0})
        if existing:
            return existing
    idx = await next_index("evm" if chain in ("ethereum", "bsc", "polygon", "arbitrum") else chain)
    d = derive_address(_seed["bytes"], chain, idx)
    doc = {"user_id": user_id, "iso": iso, "network_id": network_id, "chain": chain,
           "index": idx, "address": d["address"], "path": d["path"],
           "invoice_id": invoice_id, "time_create": now_ts()}
    await db.addresses.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def credit_balance(user_id: str, iso: str, amount: float, available: bool = True):
    inc = {"balance": amount}
    if available:
        inc["balance_available"] = amount
    await db.wallets.update_one(
        {"user_id": user_id, "iso": iso}, {"$inc": inc}, upsert=True)


async def get_balance(user_id: str, iso: str) -> dict:
    w = await db.wallets.find_one({"user_id": user_id, "iso": iso}, {"_id": 0})
    if not w:
        return {"iso": iso, "balance": 0.0, "balance_available": 0.0}
    return {"iso": iso, "balance": round(w.get("balance", 0.0), 8),
            "balance_available": round(w.get("balance_available", 0.0), 8)}


async def add_transaction(user_id: str, ttype: str, iso: str, network_id, amount,
                          status="Done", address=None, txid=None, description="",
                          order_id=None, invoice_id=None, usd=None,
                          fee=0.0, fee_iso=None, gross_amount=None, source="cabinet"):
    tx = {
        "tx_id": uuid.uuid4().hex[:12], "user_id": user_id, "type": ttype, "iso": iso,
        "network_id": network_id, "amount": round(float(amount), 8),
        "gross_amount": round(float(gross_amount if gross_amount is not None else amount), 8),
        "fee": round(float(fee or 0.0), 8),
        "fee_iso": fee_iso or iso,
        "source": source,
        "usd_value": usd if usd is not None else catalog.usd_value(iso, amount),
        "status": status, "address": address, "txid": txid,
        "explorer_url": catalog.explorer_tx_url(network_id, txid), "description": description,
        "order_id": order_id, "invoice_id": invoice_id, "created_ts": now_ts(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.transactions.insert_one(dict(tx))
    tx.pop("_id", None)
    return tx


async def get_merchant(user_id: str) -> dict:
    m = await db.merchants.find_one({"user_id": user_id}, {"_id": 0})
    if not m:
        m = {
            "merchant_id": int(now_ts()), "user_id": user_id, "name": "My Merchant",
            "home_url": "", "result_url": "", "token": new_token(), "secret": new_secret(),
            "brand_color": "#2563EB", "logo_url": "", "description": "", "is_default": True,
            "allowed_ips": [], "auto_convert": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.merchants.insert_one(dict(m))
        m.pop("_id", None)
    return m


def resolve_fee(merchant: dict, iso: str, direction: str) -> dict:
    """Merchant-configured earning fee for 'in' (deposits/invoices) or 'out' (withdrawals)."""
    fees = (merchant or {}).get("fees") or {}
    row = fees.get(iso) or fees.get("default") or {}
    if direction == "in":
        return {"percent": float(row.get("in_percent") or 0), "fixed": float(row.get("in_fixed") or 0)}
    return {"percent": float(row.get("out_percent") or 0), "fixed": float(row.get("out_fixed") or 0)}


def invoice_public(inv: dict) -> dict:
    return {k: inv.get(k) for k in [
        "id", "order_id", "status", "status_id", "price", "payment_currency_iso",
        "include_commission", "description", "link", "currencies", "redirect_url",
        "time_create", "time_expired", "pay_info", "amount_paid", "usd_value",
        "pay_hash", "pay_explorer", "conf_required", "conf_current"]}


# Map internal invoice statuses to the vocabulary the receiver (BoxExchanger
# fozpay module) accepts (it lowercases and checks against
# paid/overpayment/canceled/deleted/error/expired/partially).
WEBHOOK_STATUS_MAP = {"Completed": "Paid", "Cancelled": "Canceled", "In Process": "Partially"}


def webhook_status(s: str) -> str:
    return WEBHOOK_STATUS_MAP.get(s, s)


def webhook_headers(merchant: dict, sign: str) -> dict:
    # The receiver reads req.headers["token"] and req.headers["sign"] (lowercase).
    # X-Auth-* kept for backward compatibility with other integrators.
    return {
        "Content-Type": "application/json",
        "token": merchant.get("token", ""),
        "sign": sign,
        "X-Auth-Token": merchant.get("token", ""),
        "X-Auth-Sign": sign,
        "User-Agent": "FozPay-Webhook/1.0",
    }


async def send_webhook(merchant: dict, inv: dict, cur_iso=None, amount=0.0):
    url = merchant.get("result_url")
    if not url:
        logger.info(f"webhook skip inv={inv.get('id')}: merchant has NO result_url configured")
        return
    rate = PRICES_USD.get(cur_iso, 0.0) if cur_iso else 0.0
    status = webhook_status(inv["status"])
    payload = {
        "id": inv["id"], "order_id": inv["order_id"], "currency": cur_iso or "",
        "payment_currency": inv["payment_currency_iso"], "status": status,
        "amount": amount, "amount_send": amount, "price": inv["price"],
        "price_send": round(amount * rate, 2), "rate": rate,
        # total_sum_price is the accepted amount the receiver compares to its
        # expected order amount — it must be the crypto amount actually paid.
        "total_sum_price": amount, "commission": 0,
        "address": (inv.get("pay_info") or {}).get("address", ""),
        "network_type": (inv.get("pay_info") or {}).get("network", ""),
        "time_create": inv["time_create"], "time_update": now_ts(),
        "time_done": now_ts() if status in ("Paid", "Overpayment") else None,
        "time_expired": inv.get("time_expired"), "time_send": now_ts(),
        "time_receive": None, "include_commission": inv.get("include_commission", 0),
    }
    try:
        sign = make_signature(payload, merchant.get("secret", ""))
    except Exception:
        sign = ""
    headers = webhook_headers(merchant, sign)
    last_err = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                r = await c.post(url, json=payload, headers=headers)
            logger.info(f"webhook sent inv={inv.get('id')} url={url} attempt={attempt} "
                        f"status={r.status_code} resp={r.text[:200]}")
            await db.invoices.update_one({"id": inv.get("id")}, {"$set": {
                "webhook_status": r.status_code, "webhook_sent_ts": now_ts(),
                "webhook_response": r.text[:500], "webhook_url": url}})
            if 200 <= r.status_code < 300:
                return
            last_err = f"HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:
            last_err = str(e)
            logger.info(f"webhook attempt {attempt} failed inv={inv.get('id')} url={url}: {e}")
        await asyncio.sleep(2 * attempt)
    await db.invoices.update_one({"id": inv.get("id")}, {"$set": {
        "webhook_status": "failed", "webhook_error": str(last_err),
        "webhook_sent_ts": now_ts(), "webhook_url": url}})
    logger.warning(f"webhook FAILED after 3 attempts inv={inv.get('id')} url={url}: {last_err}")


# ============================ auth router ============================
auth_router = APIRouter(prefix="/api/auth")


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str
    otp: Optional[str] = None


@auth_router.get("/registration-status")
async def registration_status():
    """Public: lets the login page know whether self-registration is open."""
    plat = await get_platform_settings()
    return {"status": True, "enabled": registration_enabled(plat)}


@auth_router.post("/register")
async def register(payload: RegisterIn, response: Response):
    # Публічна реєстрація за замовчуванням вимкнена. Адмін вмикає її перемикачем
    # у Налаштування → Користувачі.
    plat = await get_platform_settings()
    if not registration_enabled(plat):
        raise HTTPException(403, "Реєстрація вимкнена. Зверніться до адміністратора FozPay для створення акаунта.")
    email = payload.email.lower().strip()
    if not email or not payload.password:
        raise HTTPException(400, "Email та пароль обов'язкові")
    if len(payload.password) < 6:
        raise HTTPException(400, "Пароль має містити щонайменше 6 символів")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Користувач з таким email вже існує")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user = {"user_id": user_id, "email": email, "name": payload.name or email.split("@")[0],
            "password_hash": hash_password(payload.password), "auth_provider": "password",
            "role": "user", "picture": "", "created_at": datetime.now(timezone.utc).isoformat()}
    await db.users.insert_one(dict(user))
    await get_merchant(user_id)
    token = create_access_token(user_id, email)
    set_auth_cookie(response, token)
    user.pop("password_hash", None)
    user.pop("_id", None)
    return {"user": user, "access_token": token}


@auth_router.post("/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Невірний email або пароль")
    tf = user.get("two_fa") or {}
    if tf.get("enabled"):
        if not payload.otp:
            raise HTTPException(401, {"error": "2FA_REQUIRED", "message": "Потрібен код Google Authenticator"})
        import pyotp
        if not pyotp.TOTP(tf.get("secret", "")).verify(str(payload.otp).replace(" ", ""), valid_window=1):
            raise HTTPException(401, {"error": "2FA_INVALID", "message": "Невірний код 2FA"})
    token = create_access_token(user["user_id"], email)
    set_auth_cookie(response, token)
    user.pop("password_hash", None)
    user.pop("_id", None)
    return {"user": user, "access_token": token}


class SessionIn(BaseModel):
    session_id: str


@auth_router.post("/google/session")
async def google_session(payload: SessionIn, response: Response):
    data = await exchange_emergent_session(payload.session_id)
    email = data["email"].lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        plat = await get_platform_settings()
        if not registration_enabled(plat):
            raise HTTPException(403, "Реєстрація вимкнена. Зверніться до адміністратора FozPay для створення акаунта.")
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {"user_id": user_id, "email": email, "name": data.get("name", ""),
                "picture": data.get("picture", ""), "auth_provider": "google",
                "created_at": datetime.now(timezone.utc).isoformat()}
        await db.users.insert_one(dict(user))
        await get_merchant(user_id)
    else:
        user_id = user["user_id"]
    stoken = data["session_token"]
    await db.user_sessions.update_one(
        {"session_token": stoken},
        {"$set": {"user_id": user_id, "session_token": stoken,
                  "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                  "created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    set_session_cookie(response, stoken)
    user.pop("password_hash", None)
    return {"user": user}


@auth_router.get("/me")
async def me(request: Request):
    return await get_current_user(request)


@auth_router.post("/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"status": "ok"}


# ============================ cabinet router ============================
cab = APIRouter(prefix="/api")


@cab.get("/prices")
async def prices():
    return {"status": True, "data": [
        {"iso": iso, "name": CURRENCIES[iso]["name"], "color": CURRENCIES[iso]["color"],
         "price": PRICES_USD[iso], "change": PRICE_CHANGE.get(iso, 0.0)}
        for iso in CURRENCIES]}


async def _balance_chart(uid: str, rng: str = "1М") -> list:
    """Cumulative USD balance over time from real deposit/withdraw history, bucketed
    by range: 1Д (24h hourly), 1Т (7d daily), 1М (30d daily), 1Р (12m monthly)."""
    all_tx = await db.transactions.find(
        {"user_id": uid, "type": {"$in": ["deposit", "withdraw"]}}, {"_id": 0}
    ).sort("created_ts", 1).to_list(5000)
    now = datetime.now(timezone.utc)

    def delta(tx):
        return (-1 if tx.get("type") == "withdraw" else 1) * float(tx.get("usd_value", 0.0) or 0.0)

    points = []
    if rng == "1Д":
        buckets = {}
        for tx in all_tx:
            k = datetime.fromtimestamp(tx.get("created_ts", 0), tz=timezone.utc).replace(
                minute=0, second=0, microsecond=0)
            buckets[k] = buckets.get(k, 0.0) + delta(tx)
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
        running = sum(v for k, v in buckets.items() if k < start)
        for i in range(24):
            k = start + timedelta(hours=i)
            running += buckets.get(k, 0.0)
            points.append({"t": k.strftime("%H:00"), "value": round(max(running, 0.0), 2)})
    elif rng == "1Р":
        buckets = {}
        for tx in all_tx:
            d = datetime.fromtimestamp(tx.get("created_ts", 0), tz=timezone.utc)
            buckets[(d.year, d.month)] = buckets.get((d.year, d.month), 0.0) + delta(tx)
        months = []
        for i in range(11, -1, -1):
            mm, yy = now.month - i, now.year
            while mm <= 0:
                mm += 12
                yy -= 1
            months.append((yy, mm))
        running = sum(v for k, v in buckets.items() if k < months[0])
        for (yy, mm) in months:
            running += buckets.get((yy, mm), 0.0)
            points.append({"t": f"{mm:02d}.{yy % 100:02d}", "value": round(max(running, 0.0), 2)})
    else:
        days = 7 if rng == "1Т" else 30
        buckets = {}
        for tx in all_tx:
            d = datetime.fromtimestamp(tx.get("created_ts", 0), tz=timezone.utc).date()
            buckets[d] = buckets.get(d, 0.0) + delta(tx)
        start = (now - timedelta(days=days - 1)).date()
        running = sum(v for d, v in buckets.items() if d < start)
        for i in range(days - 1, -1, -1):
            d = (now - timedelta(days=i)).date()
            running += buckets.get(d, 0.0)
            points.append({"t": d.strftime("%d.%m"), "value": round(max(running, 0.0), 2)})
    return points


@cab.get("/me/summary")
async def summary(request: Request):
    user = await get_current_user(request)
    uid = user["user_id"]
    wallets = await db.wallets.find({"user_id": uid}, {"_id": 0}).to_list(100)
    assets, total, available = [], 0.0, 0.0
    for iso in CURRENCIES:
        w = next((x for x in wallets if x["iso"] == iso), None)
        bal = w.get("balance", 0.0) if w else 0.0
        avail = w.get("balance_available", 0.0) if w else 0.0
        usd = catalog.usd_value(iso, bal)
        total += usd
        available += catalog.usd_value(iso, avail)
        assets.append({"iso": iso, "name": CURRENCIES[iso]["name"], "color": CURRENCIES[iso]["color"],
                       "balance": round(bal, 8), "balance_available": round(avail, 8),
                       "price": PRICES_USD[iso], "usd_value": usd})
    txs = await db.transactions.find({"user_id": uid}, {"_id": 0}).sort("created_ts", -1).to_list(10)
    chart = await _balance_chart(uid, "1М")
    return {"status": True, "total_usd": round(total, 2), "available_usd": round(available, 2),
            "assets": assets, "recent": txs, "chart": chart}


@cab.get("/me/chart")
async def me_chart(request: Request, range: str = "1М"):
    user = await get_current_user(request)
    return {"status": True, "data": await _balance_chart(user["user_id"], range)}


@cab.get("/me/pending-deposits")
async def pending_deposits(request: Request):
    """Deposits detected on-chain but still waiting for the required confirmations."""
    user = await get_current_user(request)
    rows = await db.addr_credits.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(200)
    out = []
    for r in rows:
        need = r.get("conf_required")
        cur = r.get("conf_current")
        pend = float(r.get("pending_balance", 0) or 0)
        bal = float(r.get("balance", 0) or 0)
        if need and cur is not None and pend > bal + 1e-9 and cur < need:
            out.append({"iso": r["iso"], "network": r.get("network", r.get("chain", "")),
                        "amount": round(pend - bal, 8), "conf_current": int(cur),
                        "conf_required": int(need)})
    return {"status": True, "data": out}


@cab.get("/transactions")
async def transactions(request: Request):
    user = await get_current_user(request)
    txs = await db.transactions.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_ts", -1).to_list(200)
    return {"status": True, "data": txs}


@cab.get("/payouts")
async def list_payouts(request: Request):
    """Payout requests (заявки) created via the merchant API — visible in the cabinet."""
    user = await get_current_user(request)
    prs = await db.payout_requests.find(
        {"user_id": user["user_id"]}, {"_id": 0}).sort("created_ts", -1).to_list(200)
    out = []
    for pr in prs:
        pr = await _sync_payout_status(pr)
        tx = await db.transactions.find_one({"tx_id": pr.get("tx_id")}, {"_id": 0}) if pr.get("tx_id") else None
        out.append(payout_public(pr, tx))
    return {"status": True, "data": out}


async def _refund_payout(pr: dict):
    """Reverse the ledger debit + pool credit of a payout's linked withdraw tx and
    mark that tx Cancelled so the payout worker skips it."""
    tx_id = pr.get("tx_id")
    if not tx_id:
        return
    tx = await db.transactions.find_one({"tx_id": tx_id}, {"_id": 0})
    if not tx or tx.get("status") == "Cancelled":
        return
    debit_iso = tx.get("debit_iso") or tx.get("iso")
    debit_amount = float(tx.get("debit_amount") or tx.get("gross_amount") or 0)
    if debit_iso and debit_amount > 0:
        await credit_balance(pr["user_id"], debit_iso, debit_amount)
    pool_iso = tx.get("pool_iso")
    pool_amount = float(tx.get("pool_amount") or 0)
    if pool_iso and pool_amount:
        await add_to_pool(pool_iso, -pool_amount, network_id=tx.get("pool_network_id"))
    await db.transactions.update_one(
        {"tx_id": tx_id}, {"$set": {"status": "Cancelled",
                                    "description": (tx.get("description", "") + " [скасовано, повернено]").strip()}})


async def _find_payout(user_id: str, pid: str):
    return await db.payout_requests.find_one(
        {"user_id": user_id, "$or": [{"pr_id": pid}, {"tx_id": pid}, {"order_id": pid}]}, {"_id": 0})


@cab.post("/payouts/{pid}/cancel")
async def cancel_payout(request: Request, pid: str):
    """Cancel a payout request that has NOT been paid on-chain yet, refunding any
    debited balance. Blocked once the payout is done/paid."""
    user = await get_current_user(request)
    pr = await _find_payout(user["user_id"], pid)
    if not pr:
        raise HTTPException(404, "Заявку не знайдено")
    pr = await _sync_payout_status(pr)
    if pr.get("status") in ("done", "cancelled"):
        raise HTTPException(400, "Заявку вже завершено — скасування недоступне")
    tx = await db.transactions.find_one({"tx_id": pr.get("tx_id")}, {"_id": 0}) if pr.get("tx_id") else None
    if tx and tx.get("status") == "Done":
        raise HTTPException(400, "Виплату вже надіслано on-chain — скасування недоступне")
    await _refund_payout(pr)
    await db.payout_requests.update_one(
        {"pr_id": pr["pr_id"]}, {"$set": {"status": "cancelled", "updated_ts": now_ts()}})
    pr = await db.payout_requests.find_one({"pr_id": pr["pr_id"]}, {"_id": 0})
    return {"status": True, "message": "Заявку скасовано, кошти повернено на баланс",
            "data": payout_public(pr)}


@cab.delete("/payouts/{pid}")
async def delete_payout(request: Request, pid: str):
    """Delete a payout request from the system. If it was still active (not paid),
    refund the debited balance first."""
    user = await get_current_user(request)
    pr = await _find_payout(user["user_id"], pid)
    if not pr:
        raise HTTPException(404, "Заявку не знайдено")
    pr = await _sync_payout_status(pr)
    tx = await db.transactions.find_one({"tx_id": pr.get("tx_id")}, {"_id": 0}) if pr.get("tx_id") else None
    if tx and tx.get("status") == "Done":
        raise HTTPException(400, "Виплату вже надіслано on-chain — видалення недоступне")
    if pr.get("status") not in ("done", "cancelled"):
        await _refund_payout(pr)
    await db.payout_requests.delete_one({"pr_id": pr["pr_id"]})
    return {"status": True, "message": "Заявку видалено з системи"}


@cab.get("/wallet")
async def wallet(request: Request):
    user = await get_current_user(request)
    uid = user["user_id"]
    out = []
    for iso, cur in CURRENCIES.items():
        b = await get_balance(uid, iso)
        out.append({"iso": iso, "name": cur["name"], "color": cur["color"],
                    "price": PRICES_USD[iso], "balance": b["balance"],
                    "balance_available": b["balance_available"],
                    "usd_value": catalog.usd_value(iso, b["balance"]),
                    "networks": networks_for(iso)})
    return {"status": True, "data": out}


class DepositAddrIn(BaseModel):
    currency: str
    network_id: int


@cab.post("/wallet/deposit-address")
async def deposit_address(request: Request, payload: DepositAddrIn):
    user = await get_current_user(request)
    iso = payload.currency.upper()
    if iso not in CURRENCIES or payload.network_id not in CURRENCIES[iso]["networks"]:
        raise HTTPException(400, "Currency/network not available")
    if not await is_network_enabled(payload.network_id):
        net_name = NETWORKS.get(payload.network_id, {}).get("name", str(payload.network_id))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена суперадміністратором")
    addr = await allocate_address(user["user_id"], iso, payload.network_id)
    net = NETWORKS[payload.network_id]
    plat = await get_platform_settings()
    return {"status": True, "data": {"address": addr["address"], "currency": iso,
            "network_id": payload.network_id, "network": net["name"], "network_iso": net["iso"],
            "platform_deposit_fee": deposit_fee_for(plat, iso)}}


class WithdrawIn(BaseModel):
    currency: str
    network_id: int
    amount: float
    address: str
    otp: Optional[str] = None
    source: Optional[str] = "cabinet"   # "cabinet" or "api"


def _swap_chain_for(chain):
    """Chain on which the REAL 1inch auto-convert swap is executed for a withdrawal."""
    return chain


async def _prepare_withdraw(uid, iso, network_id, amount, address, src, merchant):
    """Shared withdrawal preparation for BOTH the cabinet and the merchant API.

    Debits the requested currency if the balance is sufficient. Otherwise, when
    auto-convert is enabled (merchant toggle + platform flag), debits a configured
    SOURCE currency (USDT/USDC/...) whose balance is enough, and records a
    `convert_from`/`convert_amount` so the payout worker performs a REAL on-chain
    1inch swap into the requested currency before sending it.
    Returns a dict with the pending transaction and fee breakdown."""
    if iso not in CURRENCIES:
        raise HTTPException(400, "Currency not available")
    nid_ok = network_id in NETWORKS and network_id in CURRENCIES[iso]["networks"]
    if not nid_ok:
        raise HTTPException(400, "Мережа недоступна для цієї валюти")
    if not await is_network_enabled(network_id):
        net_name = NETWORKS.get(network_id, {}).get("name", str(network_id))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена суперадміністратором")
    if amount <= 0:
        raise HTTPException(400, "Invalid amount")
    if not address:
        raise HTTPException(400, "address required")
    address = _validate_payout_address(iso, network_id, address)

    bal = await get_balance(uid, iso)
    ofee = resolve_fee(merchant, iso, "out")
    merchant_fee = amount * ofee["percent"] / 100 + ofee["fixed"]
    plat = await get_platform_settings()
    platform_fee = float(withdrawal_fee_for(plat, iso, network_id, src))
    total_fee = round(merchant_fee + platform_fee, 8)
    total = round(amount + total_fee, 8)

    convert_from = None
    convert_amount = 0.0
    convert_chain = None

    if total <= bal["balance_available"]:
        # Enough of the requested currency — normal path.
        await credit_balance(uid, iso, -total)
        await add_to_pool(iso, platform_fee, network_id=network_id)
        debit_iso, debit_amount, pool_iso, pool_amount = iso, total, iso, platform_fee
    else:
        # AUTO-CONVERT: not enough of the requested currency. Try to fund it from a
        # configured source currency and perform a REAL on-chain swap on payout.
        chain = NETWORKS.get(network_id, {}).get("chain")
        swap_chain = _swap_chain_for(chain)
        if not (bool(merchant.get("auto_convert", True)) and auto_convert_enabled(plat)):
            raise HTTPException(400, "Недостатньо коштів на балансі (з урахуванням комісії)")
        if swap_chain not in ("ethereum", "bsc", "polygon", "arbitrum"):
            raise HTTPException(400, "Недостатньо коштів на балансі (з урахуванням комісії)")
        price_iso = PRICES_USD.get(iso, 0.0)
        if price_iso <= 0:
            raise HTTPException(400, "Недостатньо коштів і немає курсу для конвертації")
        chosen = None
        tried = []
        for s_iso in convert_sources_for(plat):
            s_iso = s_iso.upper()
            if s_iso == iso:
                continue
            # both source and target must be swappable on the swap chain via 1inch
            if not _iso_evm_repr(swap_chain, s_iso) or not _iso_evm_repr(swap_chain, iso):
                continue
            price_src = PRICES_USD.get(s_iso, 0.0)
            if price_src <= 0:
                continue
            # source needed to buy `amount` of iso (+2% slippage/gas buffer) + fee
            src_for_amount = round(amount * price_iso / price_src, 8)
            src_fee = round(platform_fee * price_iso / price_src, 8)
            src_needed = round(src_for_amount + src_fee, 8)
            s_bal = await get_balance(uid, s_iso)
            tried.append(f"{s_iso} (треба ~{src_needed}, є {s_bal['balance_available']})")
            if src_needed <= s_bal["balance_available"]:
                chosen = (s_iso, src_for_amount, src_fee, src_needed)
                break
        if not chosen:
            hint = "; ".join(tried) if tried else "немає доступних валют-джерел"
            raise HTTPException(
                400, f"Недостатньо {iso}. Авто-конвертація неможлива: {hint}")
        s_iso, src_for_amount, src_fee, src_needed = chosen
        await credit_balance(uid, s_iso, -src_needed)
        await add_to_pool(s_iso, src_fee, network_id=network_id)
        convert_from = s_iso
        convert_amount = src_for_amount
        convert_chain = swap_chain
        debit_iso, debit_amount, pool_iso, pool_amount = s_iso, src_needed, s_iso, src_fee

    tx = await add_transaction(uid, "withdraw", iso, network_id, amount,
                               status="Pending", address=address,
                               description=(f"Withdraw {iso} — авто-конвертація з {convert_amount} {convert_from}"
                                            if convert_from else f"Withdraw {iso} (комісія {total_fee} {iso})"),
                               fee=total_fee, fee_iso=iso,
                               gross_amount=total, source=src)
    if convert_from:
        await db.transactions.update_one({"tx_id": tx["tx_id"]},
            {"$set": {"convert_from": convert_from, "convert_amount": convert_amount,
                      "convert_chain": convert_chain}})
    # Record exactly what was debited so a cancellation can refund it precisely.
    await db.transactions.update_one({"tx_id": tx["tx_id"]},
        {"$set": {"debit_iso": debit_iso, "debit_amount": round(debit_amount, 8),
                  "pool_iso": pool_iso, "pool_amount": round(pool_amount, 8),
                  "pool_network_id": network_id}})
    return {"tx": tx, "total_fee": total_fee, "platform_fee": platform_fee,
            "merchant_fee": round(merchant_fee, 8), "convert_from": convert_from,
            "convert_amount": convert_amount, "total": round(total, 8),
            "debit_iso": debit_iso, "debit_amount": round(debit_amount, 8)}


@cab.post("/wallet/withdraw")
async def withdraw(request: Request, payload: WithdrawIn):
    user = await get_current_user(request)
    uid = user["user_id"]
    iso = payload.currency.upper()
    if iso not in CURRENCIES:
        raise HTTPException(400, "Currency not available")
    # 2FA gate for withdrawal
    if not await check_user_2fa(user, payload.otp):
        raise HTTPException(401, {"error": "2FA_REQUIRED",
                                  "message": "Потрібен код Google Authenticator для підтвердження виведення"})
    merchant = await get_merchant(uid)
    src = "api" if (payload.source or "").lower() == "api" else "cabinet"
    res = await _prepare_withdraw(uid, iso, payload.network_id, payload.amount,
                                  payload.address, src, merchant)
    return {"status": True, "data": res["tx"], "commission": res["total_fee"],
            "platform_fee": res["platform_fee"], "merchant_fee": res["merchant_fee"],
            "converted_from": res["convert_from"] or "",
            "converted_amount": res["convert_amount"] if res["convert_from"] else 0,
            "total_debited": res["total"]}


class ExchangeIn(BaseModel):
    from_iso: str
    to_iso: str
    amount: float


@cab.post("/wallet/exchange")
async def exchange(request: Request, payload: ExchangeIn):
    user = await get_current_user(request)
    uid = user["user_id"]
    fi, ti = payload.from_iso.upper(), payload.to_iso.upper()
    if fi not in CURRENCIES or ti not in CURRENCIES or fi == ti:
        raise HTTPException(400, "Invalid pair")
    bal = await get_balance(uid, fi)
    if payload.amount <= 0 or payload.amount > bal["balance_available"]:
        raise HTTPException(400, "Недостатньо коштів на балансі")
    # REAL on-chain swap via the hot wallet (1inch). Supported only for EVM pairs
    # that live on the same network (e.g. ETH/USDT/USDC on Ethereum, BNB/USDT on BSC).
    await ensure_seed()
    hot_pk = derive_evm_privkey(_seed["bytes"], 0)
    from eth_account import Account as _Acct
    hot_addr = _Acct.from_key(hot_pk).address
    # Pick the EVM chain where the hot wallet actually holds the source funds
    # (user may have deposited USDT on Polygon — the swap must run on Polygon).
    chain = await asyncio.to_thread(_best_swap_chain, fi, ti, payload.amount, hot_addr)
    if not chain:
        raise HTTPException(
            400,
            f"Реальний обмін {fi} → {ti} недоступний on-chain. Підтримуються лише "
            "EVM-пари на одній мережі (ETH/USDT/USDC на Ethereum, BNB/USDT/USDC на "
            "BSC, USDT↔USDC на Polygon/Arbitrum тощо).")
    result = await asyncio.to_thread(_swap_exact, chain, fi, ti, payload.amount, hot_pk)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Обмін не виконано"))
    received_gross = float(result["received"])
    if received_gross <= 0:
        raise HTTPException(400, "Обмін повернув 0 — перевірте ліквідність/суму")
    plat = await get_platform_settings()
    swap_pct = swap_fee_percent_for(plat, fi)  # % комісія платформи (задає адмін)
    fee_ti = round(received_gross * (swap_pct / 100.0), 8)
    received = round(received_gross - fee_ti, 8)
    # Ledger: debit source, credit real received amount of target.
    await credit_balance(uid, fi, -payload.amount)
    await credit_balance(uid, ti, received)
    if fee_ti > 0:
        await add_to_pool(ti, fee_ti)
    swap_nid = {"ethereum": 1, "bsc": 4, "polygon": 6, "arbitrum": 7}.get(chain)
    await add_transaction(uid, "exchange", fi, swap_nid, payload.amount, status="Done",
                          txid=result.get("tx"),
                          description=f"Exchange {fi} → {ti} on {chain} (real swap, fee {swap_pct}%)",
                          usd=round(payload.amount * PRICES_USD.get(fi, 0.0), 2))
    tx = await add_transaction(uid, "exchange", ti, swap_nid, received, status="Done",
                               txid=result.get("tx"),
                               description=f"Received {ti} from {fi} (on-chain swap)")
    return {"status": True, "data": {"received": received, "gross_received": round(received_gross, 8),
            "rate": round(received / payload.amount, 8) if payload.amount else 0,
            "fee_ti": fee_ti, "fee_percent": swap_pct, "chain": chain,
            "txid": result.get("tx"), "tx": tx}}


# ---------- invoices (cabinet) ----------
class InvoiceIn(BaseModel):
    order_id: str = ""
    payment_currency_iso: str = "USD"
    price: float = 0
    include_commission: int = 1
    description: str = ""
    currencies: list = []
    time_expired: int = 0
    redirect_url: str = ""


async def _create_invoice(user, merchant, data: dict) -> dict:
    inv_id = gen_id()
    # Currency the merchant expects payment IN (crypto ticker like USDT/BTC/ETH).
    pci = (data.get("payment_currency_iso") or "USDT").upper()
    if pci not in CURRENCIES:
        raise HTTPException(400, f"payment_currency_iso must be one of: {', '.join(CURRENCIES.keys())}")
    # Build accepted (iso, network) pairs — filter out networks disabled by superadmin
    curs = data.get("currencies") or []
    net_settings = await db.system.find_one({"_id": "network_settings"}) or {"enabled": {}}
    enabled_map = net_settings.get("enabled", {})
    if not curs:
        curs = []
        for iso, c in CURRENCIES.items():
            for nid in c["networks"]:
                if enabled_map.get(str(nid), True):
                    curs.append({"iso": iso, "network": nid})
    else:
        # Validate + filter by admin-enabled networks
        filtered = []
        for row in curs:
            iso = row.get("iso", "").upper()
            nid = int(row.get("network"))
            if iso in CURRENCIES and nid in CURRENCIES[iso]["networks"] and enabled_map.get(str(nid), True):
                filtered.append({"iso": iso, "network": nid})
        curs = filtered
    if not curs:
        raise HTTPException(400, "Немає доступних мереж — усі вимкнено суперадміністратором")
    order_id = data.get("order_id") or gen_id(6)
    frontend = os.environ.get("FRONTEND_URL", "")
    inv = {
        "id": inv_id, "user_id": user["user_id"], "merchant_id": merchant["merchant_id"],
        "order_id": str(order_id), "payment_currency_iso": pci,
        "price": float(data.get("price", 0)), "include_commission": int(data.get("include_commission", 1)),
        "description": data.get("description", ""), "status_id": 0, "status": "Created",
        "currencies": curs, "link": f"{frontend}/checkout/{inv_id}",
        "redirect_url": data.get("redirect_url", ""),
        "time_create": now_ts(),
        "time_expired": int(data.get("time_expired")) if data.get("time_expired") else now_ts() + 3600,
        "pay_info": None, "amount_paid": 0.0, "usd_value": 0.0,
    }
    await db.invoices.insert_one(dict(inv))
    inv.pop("_id", None)
    return inv


@cab.get("/invoices")
async def list_invoices(request: Request):
    user = await get_current_user(request)
    invs = await db.invoices.find({"user_id": user["user_id"]}, {"_id": 0}).sort("time_create", -1).to_list(200)
    return {"status": True, "data": [invoice_public(i) for i in invs]}


@cab.post("/invoices")
async def create_invoice_cab(request: Request, payload: InvoiceIn):
    user = await get_current_user(request)
    merchant = await get_merchant(user["user_id"])
    inv = await _create_invoice(user, merchant, payload.model_dump())
    return {"status": True, "data": invoice_public(inv)}


@cab.post("/invoices/{inv_id}/cancel")
async def cancel_invoice(request: Request, inv_id: str):
    user = await get_current_user(request)
    inv = await db.invoices.find_one({"id": inv_id, "user_id": user["user_id"]})
    if not inv:
        raise HTTPException(404, "Not found")
    await db.invoices.update_one({"id": inv_id}, {"$set": {"status": "Cancelled", "status_id": 3}})
    return {"status": True}


# ---------- contacts ----------
class ContactIn(BaseModel):
    name: str
    address: str
    network_id: int
    currency: str = ""


@cab.get("/contacts")
async def list_contacts(request: Request):
    user = await get_current_user(request)
    cs = await db.contacts.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"status": True, "data": cs}


@cab.post("/contacts")
async def add_contact(request: Request, payload: ContactIn):
    user = await get_current_user(request)
    c = {"contact_id": uuid.uuid4().hex[:10], "user_id": user["user_id"], "name": payload.name,
         "address": payload.address, "network_id": payload.network_id, "currency": payload.currency.upper(),
         "network": NETWORKS.get(payload.network_id, {}).get("name", ""),
         "created_at": datetime.now(timezone.utc).isoformat()}
    await db.contacts.insert_one(dict(c))
    c.pop("_id", None)
    return {"status": True, "data": c}


@cab.delete("/contacts/{cid}")
async def del_contact(request: Request, cid: str):
    user = await get_current_user(request)
    await db.contacts.delete_one({"contact_id": cid, "user_id": user["user_id"]})
    return {"status": True}


# ---------- merchant settings ----------
class MerchantIn(BaseModel):
    name: str = None
    home_url: str = None
    result_url: str = None
    brand_color: str = None
    logo_url: str = None
    description: str = None
    auto_swap: bool = None
    auto_swap_to: str = None
    auto_convert: bool = None
    fees: dict = None
    allowed_ips: list = None


@cab.get("/merchant")
async def merchant_get(request: Request):
    user = await get_current_user(request)
    return {"status": True, "data": await get_merchant(user["user_id"])}


@cab.put("/merchant")
async def merchant_update(request: Request, payload: MerchantIn):
    user = await get_current_user(request)
    await get_merchant(user["user_id"])
    upd = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "allowed_ips" in upd:
        # Accept a list or a comma/space/newline-separated string; sanitize entries.
        raw = upd["allowed_ips"]
        if isinstance(raw, str):
            raw = re.split(r"[\s,]+", raw)
        upd["allowed_ips"] = [ip.strip() for ip in raw if isinstance(ip, str) and ip.strip()]
    if upd:
        await db.merchants.update_one({"user_id": user["user_id"]}, {"$set": upd})
    return {"status": True, "data": await get_merchant(user["user_id"])}


@cab.post("/merchant/regenerate")
async def merchant_regen(request: Request):
    user = await get_current_user(request)
    await get_merchant(user["user_id"])
    await db.merchants.update_one({"user_id": user["user_id"]},
                                  {"$set": {"token": new_token(), "secret": new_secret()}})
    return {"status": True, "data": await get_merchant(user["user_id"])}


@cab.post("/merchant/test-webhook")
async def merchant_test_webhook(request: Request):
    """Send a signed sample webhook to the merchant result_url so integrators (ewex, etc.)
    can verify delivery + signature immediately. Returns the HTTP status and response body."""
    user = await get_current_user(request)
    merchant = await get_merchant(user["user_id"])
    url = merchant.get("result_url")
    if not url:
        raise HTTPException(400, "Спочатку вкажіть URL для сповіщень (result_url) у налаштуваннях мерчанта")
    payload = {
        "id": "test_" + gen_id(6), "order_id": "TEST-ORDER", "currency": "USDT",
        "payment_currency": "USDT", "status": "Paid", "amount": 3.0, "amount_send": 3.0,
        "price": 3.0, "price_send": 3.0, "rate": PRICES_USD.get("USDT", 1.0),
        "total_sum_price": 3.0, "commission": 0, "address": "TEST", "network_type": "BEP-20",
        "time_create": now_ts(), "time_update": now_ts(), "time_done": now_ts(),
        "time_expired": None, "time_send": now_ts(), "time_receive": None,
        "include_commission": 0, "test": True,
    }
    sign = make_signature(payload, merchant.get("secret", ""))
    headers = webhook_headers(merchant, sign)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.post(url, json=payload, headers=headers)
        return {"status": True, "data": {"url": url, "http_status": r.status_code,
                "response": r.text[:1000], "sign": sign,
                "delivered": 200 <= r.status_code < 300}}
    except Exception as e:
        return {"status": False, "data": {"url": url, "error": str(e), "delivered": False}}


# ---------- public checkout ----------
@cab.get("/checkout/{inv_id}")
async def checkout_get(inv_id: str):
    inv = await db.invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
    return {"status": True, "data": {
        **invoice_public(inv),
        "merchant": {"name": merchant.get("name", ""), "brand_color": merchant.get("brand_color", "#2563EB"),
                     "logo_url": merchant.get("logo_url", "")} if merchant else {},
        "currency_meta": {iso: {"name": CURRENCIES[iso]["name"], "color": CURRENCIES[iso]["color"]} for iso in CURRENCIES},
        "network_meta": {str(k): v for k, v in NETWORKS.items()},
    }}


class CheckoutSelectIn(BaseModel):
    iso: str
    network_id: int


@cab.post("/checkout/{inv_id}/select")
async def checkout_select(inv_id: str, payload: CheckoutSelectIn):
    inv = await db.invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv["status"] in ("Paid", "Completed", "Cancelled", "Expired"):
        raise HTTPException(400, "Invoice not payable")
    iso = payload.iso.upper()
    if iso not in CURRENCIES or payload.network_id not in CURRENCIES[iso]["networks"]:
        raise HTTPException(400, "Currency/network not available")
    if not await is_network_enabled(payload.network_id):
        net_name = NETWORKS.get(payload.network_id, {}).get("name", str(payload.network_id))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена")
    addr = await allocate_address(inv["user_id"], iso, payload.network_id, invoice_id=inv_id)
    # Convert invoice price (denominated in a crypto ISO) to the chosen payment ISO via USD parity.
    pay_iso = (inv.get("payment_currency_iso") or "USDT").upper()
    if pay_iso not in PRICES_USD:
        raise HTTPException(400, f"Invoice currency {pay_iso} not supported")
    usd = float(inv["price"]) * PRICES_USD[pay_iso]
    amount = usd / PRICES_USD[iso] if PRICES_USD[iso] else 0.0
    merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
    infee = resolve_fee(merchant, iso, "in")
    merchant_fee = amount * infee["percent"] / 100 + infee["fixed"]
    # Include platform deposit fee in the amount the payer must send so recipient credit stays whole
    plat = await get_platform_settings()
    platform_fee = deposit_fee_for(plat, iso)
    amount_to_pay = amount
    net = NETWORKS[payload.network_id]
    pay_info = {"amount": round(amount, 8), "merchant_fee": round(merchant_fee, 8),
                "platform_fee": round(platform_fee, 8),
                "commission": round(merchant_fee + platform_fee, 8),
                "amount_to_pay": round(amount_to_pay, 8), "address": addr["address"],
                "currency": iso, "network": net["name"], "network_id": payload.network_id,
                "network_iso": net["iso"], "rate": PRICES_USD[iso],
                "confirmations": await confirmations_required(payload.network_id)}
    await db.invoices.update_one({"id": inv_id}, {"$set": {"pay_info": pay_info, "status": "In Process", "status_id": 6}})
    return {"status": True, "data": pay_info}


@cab.post("/checkout/{inv_id}/simulate-pay", deprecated=True)
async def checkout_simulate_removed(inv_id: str):
    """Симуляція оплат ВИМКНЕНА — всі платежі приймаються тільки з реального блокчейну."""
    raise HTTPException(410, "Симуляція оплат вимкнена. Надішліть реальні кошти на адресу checkout — deposit worker підтвердить транзакцію on-chain (Alchemy/TronGrid).")


@cab.get("/currencies")
async def crypto_currency_list(request: Request):
    """List of CRYPTO currencies available for invoices/deposits (fiat removed)."""
    await get_current_user(request)
    net_settings = await db.system.find_one({"_id": "network_settings"}) or {"enabled": {}}
    enabled_map = net_settings.get("enabled", {})
    out = []
    for iso, c in CURRENCIES.items():
        nets = []
        for nid in c["networks"]:
            if enabled_map.get(str(nid), True):
                nm = NETWORKS[nid]
                nets.append({"network_id": nid, "network_iso": nm["iso"], "name": nm["name"], "chain": nm["chain"]})
        if nets:
            out.append({"iso": iso, "name": c["name"], "color": c["color"], "networks": nets,
                        "price_usd": PRICES_USD.get(iso, 0)})
    return {"status": True, "data": out}


# ============================ public fozpay API ============================
pub = APIRouter(prefix="/api/v1/public")


@pub.get("/currency-list")
async def currency_list():
    """Public list of CRYPTO ISOs supported for invoices (fiat is deprecated)."""
    return {"status": True, "data": [
        {"id": CURRENCIES[iso]["id"], "name": CURRENCIES[iso]["name"], "iso3": iso}
        for iso in CURRENCIES]}


@pub.get("/currency-network-list")
async def currency_network_list():
    return {"status": True, "data": [
        {"name": CURRENCIES[iso]["name"], "iso3": iso, "icon": "",
         "networks": networks_for(iso)} for iso in CURRENCIES]}


# ============================ private fozpay API (signature) ============================
priv = APIRouter(prefix="/api/v1")


async def auth_merchant(request: Request):
    token = request.headers.get("X-Auth-Token")
    if not token:
        raise HTTPException(401, "Your request was made with invalid credentials.NONE headers")
    merchant = await db.merchants.find_one({"token": token}, {"_id": 0})
    if not merchant:
        raise HTTPException(401, "Your request was made with invalid credentials.NONE headers")
    # IP allow-list: if the merchant configured allowed IPs, only those may call the API.
    allowed = merchant.get("allowed_ips") or []
    if allowed:
        client_ip = client_ip_of(request)
        if client_ip not in allowed:
            logger.warning(f"merchant API blocked ip={client_ip} token=...{token[-6:]}")
            raise HTTPException(403, f"IP {client_ip} is not allowed for this merchant")
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        sign = request.headers.get("X-Auth-Sign", "")
        expected = make_signature(body, merchant["secret"])
        if sign != expected:
            raise HTTPException(400, "Signature is invalid")
    user = await db.users.find_one({"user_id": merchant["user_id"]}, {"_id": 0})
    return merchant, user, body


def coins_payload(merchant=None):
    data = {}
    for iso, c in CURRENCIES.items():
        infee = resolve_fee(merchant, iso, "in")
        outfee = resolve_fee(merchant, iso, "out")
        nets = {}
        for nid in c["networks"]:
            net = NETWORKS[nid]
            comm = commission_for(iso, nid)
            nets[net["name"]] = {
                "name": net["name"], "network_id": nid, "network_iso": net["iso"],
                "in": 1, "out": 1,
                "withdraw": {"commission": {"fixed": comm["withdraw"]["fixed"] + outfee["fixed"],
                                            "percent": comm["withdraw"]["percent"] + outfee["percent"],
                                            "min_fee": comm["withdraw"]["min_fee"]},
                             "min": comm["withdraw"]["min"]},
                "refill": {"commission": {"fixed": infee["fixed"],
                                          "percent": infee["percent"],
                                          "min_fee": comm["refill"]["min_fee"]},
                           "min": comm["refill"]["min"]},
            }
        data[iso] = {"id": c["id"], "name": c["name"], "iso3": iso, "networks": nets}
    return data


@priv.get("/private/coins")
async def private_coins(request: Request):
    merchant, _, _ = await auth_merchant(request)
    return {"status": True, "data": coins_payload(merchant), "token": merchant["token"]}


@priv.post("/private/get-address")
async def private_get_address(request: Request):
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    net_in = body.get("network")
    nid = _resolve_network(iso, net_in)
    if iso not in CURRENCIES or nid is None:
        return {"status": False, "error": "Currency not found", "token": merchant["token"]}
    addr = await allocate_address(user["user_id"], iso, nid)
    return {"status": True, "message": "", "data": {
        "address": addr["address"], "time_create": addr["time_create"],
        "network": NETWORKS[nid]["name"], "currency": {"iso": iso, "name": CURRENCIES[iso]["name"]}},
        "token": merchant["token"]}


def _resolve_network(iso, net_in):
    if iso not in CURRENCIES:
        return None
    allowed = CURRENCIES[iso]["networks"]
    if isinstance(net_in, int):
        return net_in if net_in in allowed else None
    if isinstance(net_in, str):
        for nid in allowed:
            if NETWORKS[nid]["name"].lower() == net_in.lower() or NETWORKS[nid]["iso"].lower() == net_in.lower():
                return nid
    if len(allowed) == 1:
        return allowed[0]
    return None


def _validate_payout_address(iso: str, network_id, address: str) -> str:
    """Strictly validate & canonicalize a payout address for its network. Rejects
    malformed addresses so a corrupted value can never be accepted via the API
    (e.g. a truncated/zero-padded address after a restart). Does not mutate a valid
    address beyond EVM checksum canonicalization."""
    a = (address or "").strip()
    if not a:
        raise HTTPException(400, "address required")
    if any(ch.isspace() for ch in a):
        raise HTTPException(400, f"Адреса містить недопустимі символи: {a}")
    chain = NETWORKS.get(network_id, {}).get("chain")
    if chain in ("ethereum", "bsc", "polygon", "arbitrum"):
        from web3 import Web3
        if not (a.startswith("0x") and len(a) == 42) or not Web3.is_address(a):
            raise HTTPException(400, f"Некоректна EVM-адреса: {a}")
        return Web3.to_checksum_address(a)
    if chain == "tron":
        if not (a.startswith("T") and len(a) == 34):
            raise HTTPException(400, f"Некоректна TRON-адреса: {a}")
        return a
    if chain in ("bitcoin", "litecoin"):
        if not (26 <= len(a) <= 62):
            raise HTTPException(400, f"Некоректна адреса {chain}: {a}")
        return a
    if chain == "solana":
        if not (32 <= len(a) <= 44):
            raise HTTPException(400, f"Некоректна Solana-адреса: {a}")
        return a
    return a


@priv.post("/order/create")
async def order_create(request: Request):
    merchant, user, body = await auth_merchant(request)
    if not body.get("order_id"):
        raise HTTPException(400, "order_id required")
    curs = []
    for c in body.get("currencies", []) or []:
        curs.append({"iso": str(c.get("iso", "")).upper(), "network": c.get("network")})
    pci = str(body.get("payment_currency_iso") or "USDT").upper()
    data = {"order_id": body.get("order_id"), "payment_currency_iso": pci,
            "price": body.get("price", 0), "include_commission": body.get("include_commission", 1),
            "description": body.get("description", ""), "currencies": curs,
            "time_expired": body.get("time_expired", 0), "redirect_url": body.get("redirect_url", "")}
    inv = await _create_invoice(user, merchant, data)
    return {"status": True, "message": "Success send request to create order.",
            "data": invoice_public(inv), "token": merchant["token"]}


@priv.post("/order/get")
async def order_get(request: Request):
    merchant, user, body = await auth_merchant(request)
    q = {"user_id": user["user_id"]}
    if body.get("order_id"):
        q["order_id"] = str(body["order_id"])
    inv = await db.invoices.find_one(q, {"_id": 0}, sort=[("time_create", -1)])
    if not inv:
        raise HTTPException(400, "Order not found")
    return {"status": True, "message": "Success get order data.",
            "data": invoice_public(inv), "token": merchant["token"]}


@priv.post("/merchant/balance")
async def merchant_balance(request: Request):
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    if iso not in CURRENCIES:
        raise HTTPException(400, "Currency not available")
    b = await get_balance(user["user_id"], iso)
    return {"status": True, "message": "", "data": {
        "balance": str(b["balance"]), "balance_available": str(b["balance_available"]),
        "currency": {"iso3": iso, "name": CURRENCIES[iso]["name"]}}, "token": merchant["token"]}


@priv.post("/merchant/pay-in")
async def merchant_pay_in(request: Request):
    """Create Pay-in v2 — returns pay_info with deposit address immediately."""
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    nid = _resolve_network(iso, body.get("network"))
    if iso not in CURRENCIES or nid is None:
        raise HTTPException(400, "Currency not available")
    if not await is_network_enabled(nid):
        net_name = NETWORKS.get(nid, {}).get("name", str(nid))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена суперадміністратором")
    amount = float(body.get("amount", 0))
    data = {"order_id": body.get("order_id") or gen_id(6), "payment_currency_iso": iso,
            "price": amount, "include_commission": body.get("include_commission", 0),
            "description": body.get("description", ""),
            "currencies": [{"iso": iso, "network": nid}],
            "redirect_url": body.get("redirect_url", "")}
    inv = await _create_invoice(user, merchant, data)
    addr = await allocate_address(user["user_id"], iso, nid, invoice_id=inv["id"])
    infee = resolve_fee(merchant, iso, "in")
    merchant_fee = amount * infee["percent"] / 100 + infee["fixed"]
    # Include platform fee so the recipient credit stays whole after platform deducts it
    plat = await get_platform_settings()
    platform_fee = deposit_fee_for(plat, iso)
    amount_to_pay = amount
    net = NETWORKS[nid]
    pay_info = {"commission": round(merchant_fee + platform_fee, 8),
                "merchant_fee": round(merchant_fee, 8),
                "platform_fee": round(platform_fee, 8),
                "amount_to_pay": round(amount_to_pay, 8),
                "amount": round(amount, 8), "address": addr["address"],
                "currency": iso, "network": net["name"], "network_id": nid, "rate": PRICES_USD[iso]}
    await db.invoices.update_one({"id": inv["id"]}, {"$set": {"pay_info": pay_info, "status": "In Process", "status_id": 6}})
    inv = await db.invoices.find_one({"id": inv["id"]}, {"_id": 0})
    return {"status": True, "message": "Success send request to create order.",
            "data": invoice_public(inv), "token": merchant["token"]}


# Internal payout_request status -> vocabulary the merchant module expects
# (it lowercases and buckets into keep-waiting / done / error).
PAYOUT_STATUS_MERCHANT = {
    "new": "pending", "awaiting_funds": "pending", "processing": "processing",
    "pending": "pending", "done": "done", "error": "error", "cancelled": "cancelled",
}


def _is_balance_error(msg) -> bool:
    return bool(re.search(r"недостат|insufficient|not enough|balance|funds", str(msg or ""), re.I))


def _payout_key(user_id: str, order_id: str, request_id) -> dict:
    """Idempotency key for a payout request: prefer order_id, else request_id."""
    if order_id:
        return {"user_id": user_id, "order_id": order_id}
    return {"user_id": user_id, "request_id": request_id}


async def _sync_payout_status(pr: dict) -> dict:
    """Reconcile a payout_request with its linked on-chain withdraw transaction."""
    tx_id = pr.get("tx_id")
    if not tx_id:
        return pr
    tx = await db.transactions.find_one({"tx_id": tx_id}, {"_id": 0})
    if not tx:
        return pr
    mapped = {"Done": "done", "Pending": "processing", "Cancelled": "cancelled"}.get(
        tx.get("status"), pr.get("status"))
    upd = {}
    if mapped and mapped != pr.get("status"):
        upd["status"] = mapped
    if tx.get("txid") and tx.get("txid") != pr.get("txid"):
        upd["txid"] = tx["txid"]
        upd["explorer_url"] = tx.get("explorer_url", "")
    if upd:
        upd["updated_ts"] = now_ts()
        await db.payout_requests.update_one(
            _payout_key(pr["user_id"], pr.get("order_id", ""), pr.get("request_id")),
            {"$set": upd})
        pr.update(upd)
    return pr


def payout_public(pr: dict, tx: dict = None) -> dict:
    tx = tx or {}
    return {
        "id": pr.get("tx_id") or pr.get("pr_id"),
        "pr_id": pr.get("pr_id"),
        "order_id": pr.get("order_id", ""),
        "request_id": pr.get("request_id"),
        "status": PAYOUT_STATUS_MERCHANT.get(pr.get("status", "pending"), "pending"),
        "internal_status": pr.get("status", "pending"),
        "currency": pr.get("currency", ""),
        "network": pr.get("network", ""),
        "network_id": pr.get("network_id"),
        "amount": pr.get("amount", 0),
        "address": pr.get("address", ""),
        "txid": tx.get("txid") or pr.get("txid") or "",
        "tx_hash": tx.get("txid") or pr.get("txid") or "",
        "hash": tx.get("txid") or pr.get("txid") or "",
        "explorer_url": tx.get("explorer_url") or pr.get("explorer_url") or "",
        "commission": pr.get("total_fee", 0),
        "platform_fee": pr.get("platform_fee", 0),
        "merchant_fee": pr.get("merchant_fee", 0),
        "auto_converted": bool(pr.get("convert_from")),
        "converted_from": pr.get("convert_from") or "",
        "converted_amount": pr.get("convert_amount") or 0,
        "total_debited": pr.get("total_debited") or pr.get("amount", 0),
        "error": pr.get("error", ""),
        "created_ts": pr.get("created_ts"),
        "updated_ts": pr.get("updated_ts"),
    }


async def _upsert_payout_request(user, merchant, iso, nid, amount, address,
                                 order_id, request_id, convert_currency) -> tuple:
    """Always persist the merchant payout request so it ENTERS our system
    immediately (visible in the cabinet/admin) — even before it is funded."""
    key = _payout_key(user["user_id"], order_id, request_id)
    existing = await db.payout_requests.find_one(key, {"_id": 0})
    pr_id = existing.get("pr_id") if existing else uuid.uuid4().hex[:12]
    base = {
        "user_id": user["user_id"], "merchant_id": merchant["merchant_id"],
        "order_id": order_id, "request_id": request_id,
        "currency": iso, "network_id": nid,
        "network": NETWORKS.get(nid, {}).get("name", "") if nid else "",
        "amount": round(amount, 8), "address": address,
        "convert_currency": convert_currency, "source": "api",
    }
    await db.payout_requests.update_one(key, {
        "$set": {**base, "updated_ts": now_ts()},
        "$setOnInsert": {"pr_id": pr_id, "status": "new", "tx_id": None,
                         "created_ts": now_ts(),
                         "created_at": datetime.now(timezone.utc).isoformat()},
    }, upsert=True)
    return key, existing, pr_id


@priv.post("/private/create-output")
async def private_create_output(request: Request):
    """Create a withdrawal (payout) via the merchant API. The request is ALWAYS
    recorded in our system first (payout_requests) so it is visible to the admin
    even before funding. If the merchant lacks the requested currency but has a
    configured source currency (e.g. USDT), the payout is funded by a REAL on-chain
    1inch swap — provided auto-convert is enabled (merchant toggle + platform flag).
    When the balance is not yet sufficient the request is kept as `awaiting_funds`
    and a background worker retries it once funds arrive."""
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    nid = _resolve_network(iso, body.get("network"))
    amount = float(body.get("amount", 0) or 0)
    address = str(body.get("address", "")).strip()
    order_id = str(body.get("order_id") or "")
    request_id = body.get("request_id")
    convert_currency = str(body.get("convert_currency") or "").upper()

    # Validate the destination address BEFORE persisting so a malformed/corrupted
    # address (e.g. truncated or zero-padded after a restart) is rejected up-front.
    if iso in CURRENCIES and nid is not None and address:
        address = _validate_payout_address(iso, nid, address)

    # Persist the заявка up-front (idempotent by order_id/request_id).
    key, existing, pr_id = await _upsert_payout_request(
        user, merchant, iso, nid, amount, address, order_id, request_id, convert_currency)

    async def _fail(status, http_code, msg):
        await db.payout_requests.update_one(
            key, {"$set": {"status": status, "error": msg, "updated_ts": now_ts()}})
        raise HTTPException(http_code, msg)

    # Permanent validation errors — recorded, then rejected.
    if iso not in CURRENCIES or nid is None:
        await _fail("error", 400, "Currency not available")
    if amount <= 0:
        await _fail("error", 400, "Invalid amount")
    if not address:
        await _fail("error", 400, "address required")

    # Idempotent: already funded/queued -> return current state.
    if existing and existing.get("tx_id"):
        pr = await _sync_payout_status(await db.payout_requests.find_one(key, {"_id": 0}))
        tx = await db.transactions.find_one({"tx_id": pr.get("tx_id")}, {"_id": 0})
        return {"status": True, "message": "Output already registered.",
                "data": payout_public(pr, tx), "token": merchant["token"]}

    # Try to fund/debit now.
    try:
        res = await _prepare_withdraw(user["user_id"], iso, nid, amount, address, "api", merchant)
    except HTTPException as e:
        msg = e.detail if isinstance(e.detail, str) else str(e.detail)
        if _is_balance_error(msg):
            # Not funded yet — keep the заявка pending; worker/merchant retry will fund it.
            await db.payout_requests.update_one(
                key, {"$set": {"status": "awaiting_funds", "error": msg, "updated_ts": now_ts()}})
        else:
            await db.payout_requests.update_one(
                key, {"$set": {"status": "error", "error": msg, "updated_ts": now_ts()}})
        raise

    tx = res["tx"]
    await db.payout_requests.update_one(key, {"$set": {
        "status": "processing", "tx_id": tx["tx_id"], "error": "",
        "total_fee": res["total_fee"], "platform_fee": res["platform_fee"],
        "merchant_fee": res["merchant_fee"],
        "convert_from": res["convert_from"] or "",
        "convert_amount": res["convert_amount"] if res["convert_from"] else 0,
        "total_debited": res["total"], "updated_ts": now_ts()}})
    pr = await db.payout_requests.find_one(key, {"_id": 0})
    data = payout_public(pr, tx)
    data["status"] = "Pending"  # merchant expects a keep-waiting status on creation
    return {"status": True, "message": "Success create output request.",
            "data": data, "token": merchant["token"]}


@priv.post("/private/view-output")
async def private_view_output(request: Request):
    """Status of a payout (заявка) by order_id (preferred) or id. Polled by the
    merchant module's cron to move the order to done/error."""
    merchant, user, body = await auth_merchant(request)
    order_id = str(body.get("order_id") or "")
    out_id = str(body.get("id") or body.get("output_id") or body.get("withdraw_id") or "")
    pr = None
    if order_id:
        pr = await db.payout_requests.find_one(
            {"user_id": user["user_id"], "order_id": order_id}, {"_id": 0},
            sort=[("created_ts", -1)])
    if not pr and out_id:
        pr = await db.payout_requests.find_one(
            {"user_id": user["user_id"], "$or": [{"pr_id": out_id}, {"tx_id": out_id}]},
            {"_id": 0})
    if not pr:
        raise HTTPException(400, "Output not found")
    pr = await _sync_payout_status(pr)
    tx = await db.transactions.find_one({"tx_id": pr.get("tx_id")}, {"_id": 0}) if pr.get("tx_id") else None
    return {"status": True, "message": "", "data": payout_public(pr, tx),
            "token": merchant["token"]}


# ============================ recovery (wrong-network) ============================
import recovery as rec_mod
from hd_wallet import derive_evm_privkey

rec = APIRouter(prefix="/api/recovery")


@rec.get("/scan")
async def recovery_scan(request: Request, address: str = None):
    user = await get_current_user(request)
    q = {"user_id": user["user_id"]}
    docs = await db.addresses.find(q, {"_id": 0}).to_list(500)
    evm_addrs, tron_addrs, btc_addrs = {}, set(), set()
    for d in docs:
        ch = d["chain"]
        if address and d["address"] != address:
            continue
        if ch in rec_mod.EVM or ch in ("ethereum", "polygon", "bsc", "arbitrum"):
            evm_addrs.setdefault(d["address"], d["index"])
        elif ch == "tron":
            tron_addrs.add(d["address"])
        elif ch == "bitcoin":
            btc_addrs.add(d["address"])
    findings = []
    for a, idx in list(evm_addrs.items())[:30]:
        res = await asyncio.to_thread(rec_mod.scan_evm_address, a)
        for r in res:
            r["index"] = idx
        findings.extend(res)
    for a in list(tron_addrs)[:20]:
        findings.extend(await asyncio.to_thread(rec_mod.scan_tron_address, a))
    for a in list(btc_addrs)[:20]:
        findings.extend(await asyncio.to_thread(rec_mod.scan_btc_address, a))
    return {"status": True, "treasury": rec_mod.TREASURY_EVM,
            "scanned": {"evm": len(evm_addrs), "tron": len(tron_addrs), "btc": len(btc_addrs)},
            "findings": findings}


class SweepIn(BaseModel):
    address: str
    chain: str
    kind: str
    contract: str = None
    to_address: str = None
    iso: str = None
    amount: float = None


@rec.post("/sweep")
async def recovery_sweep(request: Request, payload: SweepIn):
    user = await get_current_user(request)
    if payload.chain not in rec_mod.EVM:
        raise HTTPException(400, "Sweep підтримується лише для EVM-мереж (ETH/BSC/Polygon/Arbitrum)")
    doc = await db.addresses.find_one({"user_id": user["user_id"], "address": payload.address}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Адресу не знайдено")
    await ensure_seed()
    pk = derive_evm_privkey(_seed["bytes"], doc["index"])
    from eth_account import Account
    if Account.from_key(pk).address.lower() != payload.address.lower():
        raise HTTPException(400, "Приватний ключ не відповідає адресі (стара seed-фраза). Згенеруйте нову адресу.")
    tpk = rec_mod.treasury_privkey(_seed["bytes"])
    to_addr = payload.to_address or rec_mod.TREASURY_EVM
    if payload.amount and float(payload.amount) > 0:
        # Повернути КОНКРЕТНУ суму (а не весь баланс адреси).
        iso_sym = (payload.iso or rec_mod.EVM[payload.chain][2]).upper()
        result = await asyncio.to_thread(
            rec_mod.send_evm_amount, pk, payload.chain, iso_sym, to_addr, float(payload.amount), tpk)
    else:
        result = await asyncio.to_thread(
            rec_mod.sweep_evm, pk, payload.chain, payload.kind, payload.contract, to_addr, tpk)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Sweep failed"))
    await add_transaction(user["user_id"], "recovery", payload.kind == "native" and rec_mod.EVM[payload.chain][2] or "TOKEN",
                          rec_mod.EVM[payload.chain][1], 0, status="Done",
                          address=result["to"], txid=result["tx_hash"],
                          description=f"Recovery sweep {payload.chain} → treasury")
    return {"status": True, "data": result}


class SwapReq(BaseModel):
    address: str
    chain: str
    src_iso: str
    dst_iso: str


@rec.post("/swap")
async def recovery_swap(request: Request, payload: SwapReq):
    user = await get_current_user(request)
    if payload.chain not in rec_mod.EVM:
        raise HTTPException(400, "Swap підтримується лише для EVM-мереж")
    doc = await db.addresses.find_one({"user_id": user["user_id"], "address": payload.address}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Адресу не знайдено")
    await ensure_seed()
    pk = derive_evm_privkey(_seed["bytes"], doc["index"])
    tpk = rec_mod.treasury_privkey(_seed["bytes"])
    res = await asyncio.to_thread(_do_swap, pk, payload.chain, payload.src_iso.upper(), payload.dst_iso.upper(), tpk)
    if isinstance(res, dict) and res.get("ok") is False:
        raise HTTPException(400, res.get("error", "Swap failed"))
    return {"status": True, "data": res}
# ============================ hot wallet (admin) ============================
hotw = APIRouter(prefix="/api/admin")


async def _require_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Тільки для адміністратора FozPay")
    return user


async def _hot_wallet_addresses():
    await ensure_seed()
    evm = rec_mod.TREASURY_EVM or os.environ.get("TREASURY_EVM", "")
    tron = derive_address(_seed["bytes"], "tron", 0)["address"]
    return evm, tron


@hotw.get("/hot-wallet")
async def hot_wallet_get(request: Request):
    await _require_admin(request)
    evm, tron = await _hot_wallet_addresses()
    bals = await asyncio.to_thread(rec_mod.hot_wallet_balances, evm, tron)
    total_usd = round(sum(float(b.get("usd", 0) or 0) for b in bals), 2)
    return {"status": True, "data": {"evm_address": evm, "tron_address": tron,
                                     "balances": bals, "total_usd": total_usd}}


class HotWithdrawIn(BaseModel):
    chain: str
    iso: str
    to_address: str
    amount: float
    otp: Optional[str] = None


@hotw.post("/hot-wallet/withdraw")
async def hot_wallet_withdraw(request: Request, payload: HotWithdrawIn):
    user = await _require_admin(request)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    if payload.amount <= 0:
        raise HTTPException(400, "Некоректна сума")
    if payload.chain not in rec_mod.EVM:
        raise HTTPException(400, "Реальний вивід з гарячого гаманця підтримується для EVM-мереж (ETH/BSC/Polygon/Arbitrum). Для TRON/BTC — вручну оператором.")
    await ensure_seed()
    tpk = rec_mod.treasury_privkey(_seed["bytes"])
    if not tpk:
        raise HTTPException(400, "Не вдалося отримати приватний ключ гарячого гаманця (перевірте TREASURY_EVM/мнемонік)")
    res = await asyncio.to_thread(
        rec_mod.send_evm_amount, tpk, payload.chain, payload.iso.upper(),
        payload.to_address, payload.amount, tpk)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Не вдалося надіслати"))
    nid = rec_mod.EVM[payload.chain][1]
    await add_transaction("platform", "hot_withdraw", payload.iso.upper(), nid, payload.amount,
                          status="Done", address=payload.to_address, txid=res["tx_hash"],
                          description=f"Hot wallet payout {payload.chain}", source="platform")
    return {"status": True, "data": res}


# ---- secure hot-wallet seed management (encrypted in DB, never returned) ----
@hotw.get("/hot-wallet/seed-status")
async def hot_wallet_seed_status(request: Request):
    """Чи налаштовано сід гарячого гаманця. Сам сід НІКОЛИ не повертається."""
    await _require_admin(request)
    sysdoc = await db.system.find_one({"_id": "wallet"})
    configured = bool(sysdoc and sysdoc.get("mnemonic_enc"))
    auto = bool(sysdoc and sysdoc.get("auto_generated"))
    env_override = bool(os.environ.get("WALLET_MNEMONIC", "").strip())
    await ensure_seed()
    evm, tron = await _hot_wallet_addresses()
    return {"status": True, "data": {
        "configured": configured,
        "auto_generated": auto,          # True = згенеровано системою, варто замінити своїм
        "env_override": env_override,    # True = сід заданий у .env (небезпечно)
        "encrypted_at_rest": True,
        "evm_address": evm,
        "tron_address": tron,
    }}


class SetMnemonicIn(BaseModel):
    mnemonic: str
    otp: Optional[str] = None


@hotw.post("/hot-wallet/set-mnemonic")
async def hot_wallet_set_mnemonic(request: Request, payload: SetMnemonicIn):
    """Безпечно задати/замінити сід-фразу гарячого гаманця.
    Сід перевіряється (BIP-39), шифрується (Fernet) і зберігається в БД у полі
    mnemonic_enc. У відкритому вигляді ніде не зберігається і не повертається."""
    user = await _require_admin(request)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    if os.environ.get("WALLET_MNEMONIC", "").strip():
        raise HTTPException(400, "Задано WALLET_MNEMONIC у .env — приберіть його, "
                                 "щоб керувати сідом із зашифрованої БД.")
    mnemonic = " ".join(payload.mnemonic.strip().lower().split())
    if not is_valid_mnemonic(mnemonic):
        raise HTTPException(400, "Некоректна сід-фраза (BIP-39): перевірте слова й контрольну суму.")
    await db.system.update_one(
        {"_id": "wallet"},
        {"$set": {"mnemonic_enc": encrypt_mnemonic(mnemonic), "auto_generated": False},
         "$unset": {"mnemonic": ""}}, upsert=True)
    # Перечитати сід у памʼять (і оновити адресу гарячого гаманця)
    _seed["bytes"] = None
    await ensure_seed()
    evm, tron = await _hot_wallet_addresses()
    logger.warning("Hot wallet mnemonic updated by admin (encrypted in DB).")
    return {"status": True, "data": {"evm_address": evm, "tron_address": tron,
                                     "message": "Сід збережено в зашифрованому вигляді."}}
class AdminUserCreateIn(BaseModel):
    email: str
    password: str
    name: str = ""


class AdminUserPasswordIn(BaseModel):
    user_id: str
    password: str


@hotw.get("/users")
async def admin_users_list(request: Request):
    await _require_admin(request)
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(500)
    for u in users:
        wallets = await db.wallets.find({"user_id": u["user_id"]}, {"_id": 0}).to_list(100)
        balances = []
        total_usdt = 0.0
        for w in wallets:
            iso = w.get("iso")
            bal = float(w.get("balance", 0.0) or 0.0)
            if bal == 0:
                continue
            usd = round(bal * PRICES_USD.get(iso, 0.0), 2)
            total_usdt += usd
            balances.append({"iso": iso, "balance": round(bal, 8), "usd": usd})
        balances.sort(key=lambda x: -x["usd"])
        u["balances"] = balances
        u["balance_usdt"] = round(total_usdt, 2)
    return {"status": True, "data": users}


@hotw.post("/users")
async def admin_users_create(request: Request, payload: AdminUserCreateIn):
    await _require_admin(request)
    email = payload.email.lower().strip()
    if not email or not payload.password:
        raise HTTPException(400, "Email та пароль обов'язкові")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Користувач з таким email вже існує")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user = {"user_id": user_id, "email": email, "name": payload.name or email.split("@")[0],
            "password_hash": hash_password(payload.password), "auth_provider": "password",
            "role": "user", "picture": "", "created_at": datetime.now(timezone.utc).isoformat()}
    await db.users.insert_one(dict(user))
    await get_merchant(user_id)
    user.pop("password_hash", None)
    return {"status": True, "data": user}


@hotw.put("/users/password")
async def admin_users_password(request: Request, payload: AdminUserPasswordIn):
    await _require_admin(request)
    if not payload.password or len(payload.password) < 4:
        raise HTTPException(400, "Пароль занадто короткий")
    r = await db.users.update_one({"user_id": payload.user_id},
                                  {"$set": {"password_hash": hash_password(payload.password),
                                            "auth_provider": "password"}})
    if r.matched_count == 0:
        raise HTTPException(404, "Користувача не знайдено")
    return {"status": True, "message": "Пароль оновлено"}


@hotw.delete("/users/{uid}")
async def admin_users_delete(request: Request, uid: str):
    admin = await _require_admin(request)
    if uid == admin["user_id"]:
        raise HTTPException(400, "Не можна видалити власний акаунт")
    await db.users.delete_one({"user_id": uid})
    await db.merchants.delete_many({"user_id": uid})
    await db.wallets.delete_many({"user_id": uid})
    return {"status": True, "message": "Користувача видалено"}


async def sweep_to_hot_wallet(chain, iso, address):
    """Move a received deposit from the per-user address to the platform hot wallet.
    EVM: real on-chain sweep (auto-funds gas from hot wallet). Non-EVM: operator handles."""
    try:
        if chain not in rec_mod.EVM:
            return
        doc = await db.addresses.find_one({"address": address}, {"_id": 0})
        if not doc:
            return
        await ensure_seed()
        pk = derive_evm_privkey(_seed["bytes"], doc["index"])
        # Don't sweep the hot wallet into itself
        from eth_account import Account as _Acct
        if _Acct.from_key(pk).address.lower() == (rec_mod.TREASURY_EVM or "").lower():
            return
        tpk = rec_mod.treasury_privkey(_seed["bytes"])
        native = rec_mod.EVM[chain][2]
        kind = "native" if iso == native else "token"
        contract = None if kind == "native" else (rec_mod.TOKENS.get(chain, {}).get(iso) or [None])[0]
        if kind == "token" and not contract:
            return
        res = await asyncio.to_thread(
            rec_mod.sweep_evm, pk, chain, kind, contract, rec_mod.TREASURY_EVM, tpk)
        logger.info(f"sweep_to_hot_wallet {iso} {chain} {address}: {res}")
    except Exception as e:
        logger.info(f"sweep_to_hot_wallet failed: {e}")


def _evm_chains_for_iso(iso):
    """EVM chains where this ISO is either the native coin or a known token."""
    chains = []
    for ch, (sub, nid, native, cid) in rec_mod.EVM.items():
        if iso == native or iso in rec_mod.TOKENS.get(ch, {}):
            chains.append(ch)
    return chains


async def _credit_direct_deposit(a, iso, chain, nid, onchain):
    """Credit the delta of a detected on-chain deposit (per address+iso+chain) and sweep."""
    address = a["address"]
    seen = await db.addr_credits.find_one({"address": address, "iso": iso, "chain": chain})
    last = float(seen.get("balance", 0.0)) if seen else 0.0
    if onchain > last + 1e-9:
        if chain in rec_mod.EVM or chain in ("tron", "bitcoin"):
            need_conf = await confirmations_required(nid)
            confs, _ch = await asyncio.to_thread(rec_mod.incoming_confirmations, address, chain, iso)
            if confs < need_conf:
                await db.addr_credits.update_one(
                    {"address": address, "iso": iso, "chain": chain},
                    {"$set": {"pending_balance": onchain, "conf_current": confs,
                              "conf_required": need_conf, "user_id": a["user_id"],
                              "network": NETWORKS.get(nid, {}).get("name", chain),
                              "updated_ts": now_ts()}}, upsert=True)
                logger.info(f"deposit awaiting confirmations {confs}/{need_conf} {iso} {chain} @ {address}")
                return
        delta = round(onchain - last, 8)
        plat = await get_platform_settings()
        plat_fee = deposit_fee_for(plat, iso)
        net_amount = max(0.0, round(delta - plat_fee, 8))
        fee_applied = round(delta - net_amount, 8)
        await credit_balance(a["user_id"], iso, net_amount)
        if fee_applied > 0:
            await add_to_pool(iso, fee_applied, network_id=nid)
        net_name = NETWORKS.get(nid, {}).get("name", chain)
        real_hash = await asyncio.to_thread(rec_mod.last_incoming_tx, address, chain, iso)
        txrec = await add_transaction(
            a["user_id"], "deposit", iso, nid, net_amount, status="Done",
            address=address, txid=real_hash or "onchain",
            description=f"Deposit {iso} · {net_name} (gross {delta} {iso}, fee {fee_applied} {iso})",
            fee=fee_applied, fee_iso=iso, gross_amount=delta, source="cabinet")
        await db.addr_credits.update_one(
            {"address": address, "iso": iso, "chain": chain},
            {"$set": {"balance": onchain, "updated_ts": now_ts()}}, upsert=True)
        logger.info(f"direct deposit credited: {net_amount} {iso} on {chain} @ {address}")
        asyncio.create_task(sweep_to_hot_wallet(chain, iso, address))
        # Notify merchant callback (result_url) for direct/API deposits too.
        merchant = await db.merchants.find_one({"user_id": a["user_id"]}, {"_id": 0})
        if merchant and merchant.get("result_url"):
            synth = {
                "id": txrec.get("tx_id"), "order_id": a.get("order_id", "") or "",
                "status": "Paid", "payment_currency_iso": iso, "price": net_amount,
                "pay_info": {"address": address, "network": net_name},
                "time_create": now_ts(), "time_expired": None, "include_commission": 0,
            }
            asyncio.create_task(send_webhook(merchant, synth, iso, delta))
    elif onchain < last:
        await db.addr_credits.update_one(
            {"address": address, "iso": iso, "chain": chain},
            {"$set": {"balance": onchain, "updated_ts": now_ts()}}, upsert=True)


async def direct_deposit_worker():
    """LIVE detection for CABINET deposits made straight to a wallet address (no invoice).
    Credits balance + writes history, then sweeps funds to the hot wallet.
    EVM addresses are identical across ETH/BSC/Polygon/Arbitrum, so we detect the deposit
    on ALL EVM chains (a user who chose ERC-20 but paid on BEP-20 is still credited)."""
    await asyncio.sleep(12)
    while True:
        try:
            addrs = await db.addresses.find(
                {"invoice_id": None}, {"_id": 0}).sort("time_create", -1).to_list(300)
            for a in addrs:
                chain = a.get("chain")
                iso = a.get("iso")
                address = a.get("address")
                if not (chain and iso and address):
                    continue
                if chain in rec_mod.EVM:
                    # Scan the SAME 0x address across EVERY EVM network for ALL
                    # supported assets (native + tokens). A deposit is detected and
                    # swept no matter which EVM chain / currency the sender used.
                    try:
                        findings = await asyncio.to_thread(rec_mod.scan_evm_address, address)
                    except Exception:
                        findings = []
                    for f in findings:
                        sym = f.get("symbol")
                        if sym not in CURRENCIES:
                            continue
                        await _credit_direct_deposit(
                            a, sym, f["chain"], f["network_id"], float(f.get("amount") or 0))
                elif chain == "tron":
                    onchain = await asyncio.to_thread(rec_mod.check_tron_deposit, address, iso)
                    await _credit_direct_deposit(a, iso, "tron", 2, float(onchain or 0))
                elif chain == "bitcoin":
                    onchain = await asyncio.to_thread(rec_mod.check_btc_deposit, address)
                    await _credit_direct_deposit(a, iso, "bitcoin", 0, float(onchain or 0))
        except Exception as e:
            logger.info(f"direct_deposit_worker error: {e}")
        await asyncio.sleep(25)





async def withdrawal_worker():
    """Execute REAL on-chain payouts for Pending withdrawals from the hot wallet (EVM).
    Non-EVM withdrawals stay Pending for the operator."""
    await asyncio.sleep(15)
    while True:
        try:
            pend = await db.transactions.find(
                {"type": "withdraw", "status": "Pending"}, {"_id": 0}).to_list(100)
            for tx in pend:
                nid = tx.get("network_id")
                chain = NETWORKS.get(nid, {}).get("chain")
                if chain not in rec_mod.EVM:
                    continue
                if int(tx.get("wd_attempts", 0)) >= 5:
                    continue
                await ensure_seed()
                tpk = rec_mod.treasury_privkey(_seed["bytes"])
                if not tpk:
                    continue
                # Auto-convert leg: swap SOURCE→iso on the hot wallet first (real 1inch).
                # For opBNB the swap runs on BSC (1inch has no opBNB support).
                if tx.get("convert_from") and not tx.get("converted"):
                    swap_chain = tx.get("convert_chain") or _swap_chain_for(chain)
                    conv = await asyncio.to_thread(
                        _swap_exact, swap_chain, tx["convert_from"], tx["iso"],
                        float(tx.get("convert_amount") or 0), tpk)
                    if not conv.get("ok"):
                        await db.transactions.update_one(
                            {"tx_id": tx["tx_id"]},
                            {"$inc": {"wd_attempts": 1},
                             "$set": {"wd_error": "convert: " + conv.get("error", "")}})
                        continue
                    await db.transactions.update_one(
                        {"tx_id": tx["tx_id"]},
                        {"$set": {"converted": True, "convert_txid": conv.get("tx")}})
                res = await asyncio.to_thread(
                    rec_mod.send_evm_amount, tpk, chain, tx["iso"], tx["address"], tx["amount"], tpk)
                if res.get("ok"):
                    await db.transactions.update_one(
                        {"tx_id": tx["tx_id"]},
                        {"$set": {"status": "Done", "txid": res["tx_hash"],
                                  "explorer_url": catalog.explorer_tx_url(nid, res["tx_hash"])}})
                    logger.info(f"withdrawal paid {tx['tx_id']}: {res['tx_hash']}")
                else:
                    await db.transactions.update_one(
                        {"tx_id": tx["tx_id"]},
                        {"$inc": {"wd_attempts": 1},
                         "$set": {"wd_error": res.get("error", "")}})
                    logger.info(f"withdrawal {tx['tx_id']} not sent: {res.get('error')}")
        except Exception as e:
            logger.info(f"withdrawal_worker error: {e}")
        await asyncio.sleep(30)


async def payout_retry_worker():
    """Retry merchant payout requests (заявки) that are `awaiting_funds`. Once the
    merchant balance is topped up (or auto-convert becomes possible), debit + queue
    the on-chain payout so the request completes without depending on the merchant's
    own retry window."""
    await asyncio.sleep(20)
    while True:
        try:
            reqs = await db.payout_requests.find(
                {"status": "awaiting_funds"}, {"_id": 0}).to_list(100)
            for pr in reqs:
                merchant = await db.merchants.find_one({"user_id": pr["user_id"]}, {"_id": 0})
                if not merchant:
                    continue
                key = _payout_key(pr["user_id"], pr.get("order_id", ""), pr.get("request_id"))
                try:
                    res = await _prepare_withdraw(
                        pr["user_id"], pr["currency"], pr["network_id"],
                        float(pr["amount"]), pr["address"], "api", merchant)
                except HTTPException:
                    continue  # still not fundable
                except Exception as e:
                    logger.info(f"payout_retry {pr.get('pr_id')} error: {e}")
                    continue
                tx = res["tx"]
                await db.payout_requests.update_one(key, {"$set": {
                    "status": "processing", "tx_id": tx["tx_id"], "error": "",
                    "total_fee": res["total_fee"], "platform_fee": res["platform_fee"],
                    "merchant_fee": res["merchant_fee"],
                    "convert_from": res["convert_from"] or "",
                    "convert_amount": res["convert_amount"] if res["convert_from"] else 0,
                    "total_debited": res["total"], "updated_ts": now_ts()}})
                logger.info(f"payout_retry funded {pr.get('pr_id')} -> tx {tx['tx_id']}")
        except Exception as e:
            logger.info(f"payout_retry_worker error: {e}")
        await asyncio.sleep(30)


async def deposit_worker():
    """LIVE detection: poll pending invoices and credit merchant when funds arrive on-chain."""
    await asyncio.sleep(8)
    while True:
        try:
            ts = now_ts()
            cur = db.invoices.find({"status": {"$in": ["In Process", "Partially", "Confirming"]},
                                    "pay_info": {"$ne": None},
                                    "time_expired": {"$gt": ts}}, {"_id": 0})
            async for inv in cur:
                pi = inv["pay_info"]
                chain = NETWORKS.get(pi["network_id"], {}).get("chain")
                sym = pi["currency"]
                addr = pi["address"]
                expected = float(pi.get("amount_to_pay", pi["amount"]))
                if chain in rec_mod.EVM:
                    got = await asyncio.to_thread(rec_mod.check_evm_deposit, addr, chain, sym)
                elif chain == "tron":
                    got = await asyncio.to_thread(rec_mod.check_tron_deposit, addr, sym)
                elif chain == "bitcoin":
                    got = await asyncio.to_thread(rec_mod.check_btc_deposit, addr)
                else:
                    continue
                if got <= 0:
                    continue
                if got >= expected * 0.995:
                    need_conf = await confirmations_required(pi["network_id"])
                    confs, _ch = await asyncio.to_thread(rec_mod.incoming_confirmations, addr, chain, sym)
                    await db.invoices.update_one({"id": inv["id"]},
                        {"$set": {"conf_required": need_conf, "conf_current": confs}})
                    if confs < need_conf:
                        await db.invoices.update_one({"id": inv["id"]},
                            {"$set": {"status": "Confirming", "status_id": 1, "amount_paid": got}})
                        continue
                    status = "Overpayment" if got > expected * 1.02 else "Paid"
                    sid = 10 if status == "Overpayment" else 8
                    await _confirm_payment(inv, sym, pi["network_id"], got, addr, status, sid)
                elif got > 0:
                    await db.invoices.update_one({"id": inv["id"]},
                        {"$set": {"status": "Partially", "status_id": 1, "amount_paid": got}})
        except Exception as e:
            logger.info(f"deposit_worker error: {e}")
        await asyncio.sleep(20)


async def _confirm_payment(inv, iso, nid, amount, address, status, sid, from_address=None):
    already = await db.invoices.find_one({"id": inv["id"]}, {"status": 1})
    if already and already.get("status") in ("Paid", "Completed", "Overpayment"):
        return
    # AML screening on the sender (if we can detect it, best-effort)
    aml_result = await aml_mod.check_deposit_aml(from_address or "", amount, iso, nid)
    if aml_result.get("action") == "BLOCK":
        logger.warning(f"AML BLOCK deposit inv={inv['id']} from={from_address}: {aml_result}")
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {
            "status": "Blocked", "status_id": 8, "aml": aml_result,
            "amount_paid": amount}})
        # Record a blocked transaction so admin sees it
        await add_transaction(inv["user_id"], "deposit_blocked", iso, nid, 0,
                              status="Blocked", address=address, txid="onchain",
                              description=f"BLOCKED by AML ({', '.join(aml_result.get('flags', []))})",
                              invoice_id=inv["id"], order_id=inv["order_id"],
                              fee=0, fee_iso=iso, gross_amount=float(amount),
                              source="cabinet")
        return
    review_hold = aml_result.get("action") == "REVIEW"
    # Deduct platform deposit fee (e.g. 0.5 USDT flat) from the incoming amount.
    plat = await get_platform_settings()
    plat_fee = deposit_fee_for(plat, iso)
    net_amount = max(0.0, round(float(amount) - plat_fee, 8))
    fee_applied = round(float(amount) - net_amount, 8)
    if not review_hold:
        await credit_balance(inv["user_id"], iso, net_amount)
    if fee_applied > 0:
        await add_to_pool(iso, fee_applied, network_id=nid)
    if not review_hold:
        asyncio.create_task(sweep_to_hot_wallet(nid and NETWORKS.get(nid, {}).get("chain"), iso, address))
    tx_status = "Review" if review_hold else "Done"
    real_hash = await asyncio.to_thread(
        rec_mod.last_incoming_tx, address, NETWORKS.get(nid, {}).get("chain"), iso)
    await add_transaction(inv["user_id"], "deposit", iso, nid, net_amount, status=tx_status,
                          address=address, txid=real_hash or "onchain",
                          description=f"Deposit Invoice #{inv['id']} (gross {amount} {iso}, fee {fee_applied} {iso})"
                                      + (" — ON HOLD by AML" if review_hold else ""),
                          invoice_id=inv["id"], order_id=inv["order_id"],
                          fee=fee_applied, fee_iso=iso, gross_amount=float(amount),
                          source="cabinet")
    await db.invoices.update_one({"id": inv["id"]}, {"$set": {
        "status": ("Hold" if review_hold else status),
        "status_id": (9 if review_hold else sid),
        "amount_paid": amount, "aml": aml_result,
        "pay_hash": real_hash or "", "pay_explorer": catalog.explorer_tx_url(nid, real_hash) or "",
        "usd_value": round(amount * PRICES_USD.get(iso, 0.0), 2)}})
    inv["status"] = "Hold" if review_hold else status
    merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
    if merchant and not review_hold:
        await send_webhook(merchant, inv, iso, amount)
        if merchant.get("auto_swap"):
            asyncio.create_task(_auto_swap(inv, merchant, iso, address))


async def _auto_swap(inv, merchant, iso, address):
    """Best-effort 1inch swap of a received EVM deposit into the target currency."""
    try:
        pi = inv["pay_info"]
        chain = NETWORKS.get(pi["network_id"], {}).get("chain")
        if chain not in rec_mod.EVM:
            return
        target = (merchant.get("auto_swap_to") or "USDT").upper()
        if iso == target:
            return
        doc = await db.addresses.find_one({"address": address}, {"_id": 0})
        if not doc:
            return
        await ensure_seed()
        pk = derive_evm_privkey(_seed["bytes"], doc["index"])
        tpk = rec_mod.treasury_privkey(_seed["bytes"])
        res = await asyncio.to_thread(_do_swap, pk, chain, iso, target, tpk)
        logger.info(f"auto_swap invoice {inv['id']}: {res}")
    except Exception as e:
        logger.info(f"auto_swap failed: {e}")


def _do_swap(privkey, chain, src_iso, dst_iso, treasury_pk):
    """Resolve tokens, ensure gas, execute 1inch swap on the deposit address."""
    import oneinch as oi
    from web3 import Web3
    native = rec_mod.EVM[chain][2]
    chainid = rec_mod.EVM[chain][3]
    w3 = rec_mod._w3(chain)
    acct = w3.eth.account.from_key(privkey)
    frm = acct.address
    # resolve src amount + address
    if src_iso == native:
        src = oi.NATIVE
        amount = w3.eth.get_balance(frm)
        gas_reserve = 250000 * w3.eth.gas_price
        amount = amount - gas_reserve
    else:
        tok = rec_mod.TOKENS.get(chain, {}).get(src_iso)
        if not tok:
            return {"ok": False, "error": "src token not on chain"}
        src = Web3.to_checksum_address(tok[0])
        c = w3.eth.contract(address=src, abi=rec_mod.ERC20_ABI)
        amount = c.functions.balanceOf(frm).call()
        # ensure gas for approve+swap
        need = 350000 * w3.eth.gas_price
        if w3.eth.get_balance(frm) < need and treasury_pk:
            gf = rec_mod._fund_gas(w3, treasury_pk, frm, int(need * 1.3), w3.eth.gas_price, chainid, native)
            if gf.get("ok"):
                w3.eth.wait_for_transaction_receipt(gf["tx_hash"], timeout=180)
    if amount <= 0:
        return {"ok": False, "error": "nothing to swap"}
    dtok = rec_mod.TOKENS.get(chain, {}).get(dst_iso)
    dst = oi.NATIVE if dst_iso == native else (Web3.to_checksum_address(dtok[0]) if dtok else None)
    if not dst:
        return {"ok": False, "error": "dst token not on chain"}
    return oi.execute_swap(w3, privkey, chain, src, dst, amount)


def _iso_evm_repr(chain, iso):
    """Return ('native'|'token', contract_or_None, decimals) for iso on an EVM chain, else None."""
    native = rec_mod.EVM[chain][2]
    if iso == native:
        return ("native", None, 18)
    tok = rec_mod.TOKENS.get(chain, {}).get(iso)
    if tok:
        return ("token", tok[0], tok[1])
    return None


def _common_evm_chain(fi, ti):
    """First EVM chain where BOTH currencies are swappable on-chain (native or token)."""
    for ch in rec_mod.EVM:
        if _iso_evm_repr(ch, fi) and _iso_evm_repr(ch, ti):
            return ch
    return None


def _best_swap_chain(fi, ti, amount_human, frm):
    """Among EVM chains where both fi & ti are swappable, pick the one where the hot
    wallet actually holds enough `fi` (deposits may sit on a specific chain, e.g.
    Polygon). Fallback: chain with the largest fi balance, else the first common one."""
    from web3 import Web3
    cands = [ch for ch in rec_mod.EVM if _iso_evm_repr(ch, fi) and _iso_evm_repr(ch, ti)]
    if not cands:
        return None
    best, best_bal = None, -1.0
    for ch in cands:
        try:
            w3 = rec_mod._w3(ch)
            bal = _hot_iso_balance(w3, Web3.to_checksum_address(frm), ch, fi)
        except Exception:
            bal = 0.0
        if bal + 1e-12 >= amount_human:
            return ch
        if bal > best_bal:
            best, best_bal = ch, bal
    return best or cands[0]


def _hot_iso_balance(w3, addr, chain, iso):
    """Human-unit balance of `iso` (native or ERC-20) held by `addr` on `chain`."""
    rep = _iso_evm_repr(chain, iso)
    if not rep:
        return 0.0
    kind, contract, dec = rep
    if kind == "native":
        return w3.eth.get_balance(addr) / 1e18
    from web3 import Web3
    c = w3.eth.contract(address=Web3.to_checksum_address(contract), abi=rec_mod.ERC20_ABI)
    return c.functions.balanceOf(addr).call() / (10 ** dec)


def _swap_exact(chain, src_iso, dst_iso, amount_human, hot_pk):
    """Execute a REAL 1inch swap of a SPECIFIC amount from the hot wallet and
    return the actual received amount of dst_iso (measured on-chain)."""
    import oneinch as oi
    from web3 import Web3
    native = rec_mod.EVM[chain][2]
    w3 = rec_mod._w3(chain)
    acct = w3.eth.account.from_key(hot_pk)
    frm = acct.address
    gas_price = w3.eth.gas_price
    src_rep = _iso_evm_repr(chain, src_iso)
    dst_rep = _iso_evm_repr(chain, dst_iso)
    if not src_rep or not dst_rep:
        return {"ok": False, "error": "Пара не підтримується для on-chain обміну"}
    # resolve src token address + base amount, verify hot-wallet holds it + gas
    if src_rep[0] == "native":
        src = oi.NATIVE
        gas_room = 300000 * gas_price
        base = int(round(amount_human * 1e18))
        bal_native = w3.eth.get_balance(frm)
        if bal_native < base + gas_room:
            if bal_native > gas_room:
                base = bal_native - gas_room  # clamp to available (full-balance/rounding)
            else:
                return {"ok": False, "error": f"Недостатньо {native} на гарячому гаманці для обміну"}
    else:
        src = Web3.to_checksum_address(src_rep[1])
        base = int(round(amount_human * (10 ** src_rep[2])))
        c = w3.eth.contract(address=src, abi=rec_mod.ERC20_ABI)
        have = c.functions.balanceOf(frm).call()
        if have < base:
            # tolerate ledger↔on-chain rounding: if within 1% use the actual balance
            if have > 0 and have >= int(base * 0.99):
                base = have
            else:
                return {"ok": False, "error": f"Недостатньо {src_iso} на гарячому гаманці для обміну"}
        if w3.eth.get_balance(frm) < 350000 * gas_price:
            return {"ok": False, "error": f"Недостатньо {native} для газу на гарячому гаманці"}
    if base <= 0:
        return {"ok": False, "error": "Некоректна сума обміну"}
    dst = oi.NATIVE if dst_rep[0] == "native" else Web3.to_checksum_address(dst_rep[1])
    before = _hot_iso_balance(w3, frm, chain, dst_iso)
    try:
        res = oi.execute_swap(w3, hot_pk, chain, src, dst, base)
        w3.eth.wait_for_transaction_receipt(res["swap"], timeout=150)
    except Exception as e:
        return {"ok": False, "error": f"Помилка on-chain обміну: {str(e)[:180]}"}
    after = _hot_iso_balance(w3, frm, chain, dst_iso)
    received = max(0.0, after - before)
    return {"ok": True, "received": received, "tx": res.get("swap"), "chain": chain}


async def expire_worker():
    while True:
        try:
            ts = now_ts()
            cur = db.invoices.find({"status": {"$in": ["Created", "In Process"]},
                                    "time_expired": {"$lt": ts}}, {"_id": 0})
            async for inv in cur:
                await db.invoices.update_one({"id": inv["id"]}, {"$set": {"status": "Expired", "status_id": 7}})
                merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
                if merchant:
                    inv["status"] = "Expired"
                    await send_webhook(merchant, inv)
        except Exception as e:
            logger.info(f"worker error: {e}")
        await asyncio.sleep(30)


async def seed_demo():
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_pw = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if existing:
        if existing.get("password_hash") and not verify_password(admin_pw, existing["password_hash"]):
            await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_pw)}})
        uid = existing["user_id"]
    else:
        uid = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({"user_id": uid, "email": admin_email, "name": "Merchant",
                                   "password_hash": hash_password(admin_pw), "auth_provider": "password",
                                   "picture": "", "role": "admin",
                                   "created_at": datetime.now(timezone.utc).isoformat()})
    await get_merchant(uid)
    return uid


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id")
    await db.merchants.create_index("token")
    await db.merchants.create_index("user_id")
    await db.addresses.create_index([("chain", 1), ("index", 1)], unique=True)
    await db.invoices.create_index("id", unique=True)
    await db.transactions.create_index([("user_id", 1), ("created_ts", -1)])
    await db.user_sessions.create_index("session_token")
    await ensure_seed()
    uid = await seed_demo()
    merchant = await db.merchants.find_one({"user_id": uid}, {"_id": 0})
    try:
        from pathlib import Path as _P
        _P("/app/memory/test_credentials.md").write_text(
            "# Test Credentials\n\n"
            f"## Admin cabinet (email/password)\n- Email: {os.environ['ADMIN_EMAIL']}\n"
            f"- Password: {os.environ['ADMIN_PASSWORD']}\n- Role: admin\n\n"
            "Note: Публічної реєстрації немає. Адмін створює користувачів у "
            "Налаштування → Користувачі та може змінювати їхні паролі.\n\n"
            "## Merchant API keys (for private /api/v1 endpoints)\n"
            f"- X-Auth-Token: {merchant['token']}\n- Secret: {merchant['secret']}\n\n"
            "## Auth endpoints\n- POST /api/auth/login\n"
            "- POST /api/auth/google/session\n- GET /api/auth/me\n- POST /api/auth/logout\n")
    except Exception as e:
        logger.info(f"cred write failed: {e}")
    asyncio.create_task(expire_worker())
    asyncio.create_task(deposit_worker())
    asyncio.create_task(direct_deposit_worker())
    asyncio.create_task(withdrawal_worker())
    asyncio.create_task(payout_retry_worker())
    asyncio.create_task(aml_mod.aml_refresh_worker())
    asyncio.create_task(binance_prices.price_worker())


@app.on_event("shutdown")
async def shutdown():
    from core import client as _c
    _c.close()


@app.get("/api/")
async def root():
    return {"message": "FozPay clone API", "status": True}


for r in (auth_router, cab, pub, priv, rec, admin_router, sec_router, hotw):
    app.include_router(r)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[os.environ.get("FRONTEND_URL", "*")] if os.environ.get("FRONTEND_URL") else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
