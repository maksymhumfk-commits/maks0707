# FozPay — PRD / Project Memory

## Original problem statement
Скопіювати і розгорнути проєкт https://github.com/psymaks249-debug/ddsfrwef, написати інструкцію
для публікації на Hostinger, і зробити так, щоб доступ до сервера/БД НЕ був критичним для
гарячого гаманця — зашифрувати сід-фразу. Ключі: ALCHEMY_KEY, TRONGRID_KEY, ONEINCH_KEY.

## Architecture
- Backend: FastAPI (Python), MongoDB (motor), HD-wallet (bip-utils), web3/1inch swaps, JWT + Google session auth.
- Frontend: React (CRACO), Tailwind, admin + merchant cabinet.
- Hot wallet = HD EVM address at index 0; per-user deposit addresses derived per index; deposits swept to hot wallet.

## Seed-phrase security (this session)
- Seed is stored ENCRYPTED in MongoDB (`system/_id=wallet`, field `mnemonic_enc`, Fernet/AES).
- Decryption key `MNEMONIC_ENC_KEY` lives ONLY in `/app/backend/.env` → a DB dump alone cannot reveal the seed.
- `WALLET_MNEMONIC` intentionally NOT set in .env (DB is source of truth).
- New backend endpoints (admin only):
  - `GET /api/admin/hot-wallet/seed-status` — shows configured/auto_generated/env_override/encrypted_at_rest + addresses; never returns the seed.
  - `POST /api/admin/hot-wallet/set-mnemonic` — validates BIP-39, encrypts, stores in DB, reloads seed, returns new addresses (optional 2FA).
- New frontend: Settings → Гарячий гаманець → "Безпека сід-фрази" card to enter/replace the seed securely.
- `hd_wallet.is_valid_mnemonic()` added for BIP-39 validation.

## Config (preview env)
- backend/.env: MONGO_URL, DB_NAME, JWT_SECRET, MNEMONIC_ENC_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, FRONTEND_URL, ALCHEMY_KEY, TRONGRID_KEY, ONEINCH_KEY.
- Admin: psymaks249@gmail.com / FozPay2025Admin!

## Deployment
- `/app/README-HOSTINGER.md` — full Ukrainian VPS guide for domain **fozpay.online** (Nginx + HTTPS + systemd + MongoDB), with the encrypted-seed workflow (seed entered in admin UI after deploy, not in .env).

## Status (2026-10-03)
- Project cloned into /app, deps installed, backend + frontend running.
- Seed encryption feature implemented & tested: 100% backend (8/8), 100% frontend.
- Hot-wallet seed currently auto-generated (encrypted) — user to replace with own seed via admin UI.

## Backlog / Next
- Audit log for set-mnemonic (admin id + timestamp).
- Optional: split server.py routers into modules (maintainability).
- Secondary badge "Користувацька сід-фраза" after user sets seed (cosmetic).
