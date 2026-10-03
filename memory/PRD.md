# FozPay — PRD

## Original problem statement (iteration: GitHub import dyguop/klklk)
Додати головну сторінку продукту; перемикач реєстрації клієнтів (email+Google) в адмінці;
виправити графік балансу 1Д/1Т/1М/1Р; додати час до останніх операцій; прибрати приклад комісії;
покращити рахунок на оплату (кнопка закриття + хеш транзакції, прибрати on-chain текст);
перевірити перекази/автоконвертацію (Polygon USDT→USDC); комісії платформи = 0;
строга валідація адреси по API; показувати повну адресу у заявках; повернення коштів із сумою;
прибрати merchant-вкладку «Комісії»; інструкція публікації на Hostinger.

## Architecture
- Backend: FastAPI (server.py, admin_router.py, recovery.py, oneinch.py, hd_wallet.py, catalog.py, core.py, aml.py)
- Frontend: React (CRACO) + Tailwind + shadcn/ui; pages under src/pages
- DB: MongoDB (motor). HD wallet from WALLET_MNEMONIC (encrypted). Live chain: Alchemy/TronGrid; swap via 1inch.

## Done (2026-06)
- NEW public LandingPage.js at '/' — purple/violet dark theme, real crypto icons, Ukrainian+EN.
- Real crypto icons everywhere (common.js CoinIcon → cryptocurrency-icons CDN, fallback circle).
- Admin registration toggle: platform_settings.registration_enabled; GET/PUT /api/admin/registration;
  public /api/auth/registration-status; register() + google_session() gated; Login.js register form; Settings Users tab switch.
- Balance chart ranges fixed: _balance_chart() + GET /api/me/chart?range=1Д/1Т/1М/1Р (24/7/30/12 buckets).
- Dashboard: modern purple-gradient balance card; recent tx show date/time (fmtDateTime).
- Checkout: removed on-chain explanation block; close button (X + bottom); tx hash + explorer link on paid.
- Platform commissions set to 0 everywhere (DEFAULT_PLATFORM + existing DB doc).
- Strict address validation: _validate_payout_address() in withdraw + create-output (rejects malformed/zero-padded; EVM checksummed).
- Requests: payout table shows FULL address + copy button.
- Recovery: optional amount input per finding (partial return via send_evm_amount).
- Removed merchant 'Комісії' (tab-fees) from Settings.
- README-HOSTINGER.md: full Ukrainian VPS deploy guide.

## Hot wallet / test addresses (preview)
- EVM hot wallet / treasury (Polygon/ERC20/BSC/ARB): 0x7C594Ce4C977bbE53bf63cB2d11d70Df1f004D03
- TRON hot wallet: TU1Ndfw4jsyELqHqkphj1qFWjSKwarPWi4

## Backlog / Not verifiable without real funds
- Live on-chain deposit credit, 1inch auto-convert swap, real payouts (need funded hot wallet + gas).
- P1: standardize API response envelope; split large server.py.

## Credentials
- Admin: psymaks249@gmail.com / FozPay2025Admin! (see /app/memory/test_credentials.md)
