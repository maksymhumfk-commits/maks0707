import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight, RefreshCw, Terminal, Layers, CheckCircle2, Percent,
  ChevronDown, Flame, Webhook, Wallet, Send, Download, Gift, QrCode,
  ShieldCheck, Zap, ExternalLink, Copy,
} from "lucide-react";
import { useLang } from "@/lib/i18n";
import { CoinIcon } from "@/components/common";
import { toast } from "sonner";

const COINS = ["USDT", "USDC", "BTC", "ETH", "BNB", "TRX", "SOL", "LTC"];
const NETWORKS = ["ERC-20", "BEP-20", "TRC-20", "Polygon", "Arbitrum", "Solana", "Bitcoin", "Litecoin"];

const L = {
  uk: {
    nav_features: "Переваги", nav_currencies: "Валюти", nav_how: "Як почати", nav_api: "API",
    login: "Увійти", start: "Почати",
    hero_chip: "Власний гарячий гаманець · прямі розрахунки",
    hero_h1: "Прийом платежів у криптовалюті для вашого бізнесу",
    hero_sub: "Приймайте Bitcoin, Ethereum, USDT та інші криптовалюти на сайті або в Telegram-боті. Швидка інтеграція, автоконвертація у стейбли та виплати напряму на ваші гаманці.",
    hero_cta1: "Почати", hero_cta2: "Документація API",
    chips: [
      ["Комісії від 0%", "Без прихованих платежів і плати за підключення", Percent],
      ["Оплата за QR-кодом", "Клієнт платить у два кліки, без реєстрації", QrCode],
      ["Зарахування до 99.9%", "Автоматичне розпізнавання транзакцій on-chain", CheckCircle2],
      ["Швидка інтеграція", "REST API з підписом запитів і вебхуками", Zap],
    ],
    adv_title: "Наші переваги", adv_sub: "Усе для роботи з криптоплатежами в одному кабінеті.",
    adv: [
      ["Прийом криптоплатежів", "Клієнти платять через QR-чекаут або зі свого гаманця за кілька кліків — без реєстрації.", Download],
      ["Гарячий гаманець", "HD-гаманець із авто-збором депозитів і зашифрованим зберіганням сід-фрази в базі.", Flame],
      ["Автоконвертація", "Вхідні платежі автоматично конвертуються у USDT/USDC — захист від коливань курсу.", RefreshCw],
      ["Миттєві вебхуки", "Сповіщення про статус інвойсу з підписом і повторними спробами доставки.", Webhook],
      ["Реферальна програма", "Запрошуйте проєкти та отримуйте регулярний дохід від їхніх платежів.", Gift],
      ["Низькі комісії", "Гнучкі тарифи від 0% — ви самі керуєте комісіями у кабінеті.", Percent],
    ],
    sol_title: "Рішення для криптоплатежів",
    sol_sub: "Депозити, обміни та виведення — усе в одній панелі керування.",
    sol: [
      ["Депозит", "Поповнюйте баланс будь-якою підтримуваною валютою. Система покаже адресу, мережу й суму.", Download],
      ["Обмін", "Обмінюйте одну валюту на іншу прямо в балансі за поточним курсом, без зовнішніх бірж.", RefreshCw],
      ["Виведення", "Надсилайте кошти на будь-який зовнішній гаманець — оберіть монету, мережу й адресу.", Send],
    ],
    stats_title: "FozPay у цифрах",
    stats: [["8", "блокчейн-мереж"], ["< 1.2с", "доставка вебхука"], ["99.9%", "зарахування платежів"], ["0%", "стартова комісія"]],
    cur_title: "Найзручніші способи оплати для ваших клієнтів",
    cur_sub: "Дозвольте клієнтам платити в Bitcoin або будь-якій іншій криптовалюті — від USDT та ETH до Solana. Оплата за кілька кліків без реєстрації.",
    how_title: "Запустіть прийом платежів за два кроки",
    how: [
      ["Створіть акаунт", "Реєстрація за пару хвилин. Доступ до кабінету, API-ключів і налаштувань комісій."],
      ["Підключіть прийом", "Інтегруйтесь через REST API або готовий чекаут. Зрозуміла документація й приклади коду."],
    ],
    api_title: "Інтеграція за хвилини", api_sub: "Створюйте інвойси та виплати одним запитом. Повний контроль над статусами.",
    api_copy: "Скопіювати",
    faq_title: "Часті запитання",
    faq: [
      ["Як підключити криптоплатежі на сайт?", "Зареєструйтесь, отримайте API-ключ у кабінеті та інтегруйтесь через REST API або готовий чекаут. Підключення займає кілька хвилин."],
      ["Які комісії стягує сервіс?", "Комісію встановлює адміністратор у кабінеті окремо по кожній валюті та мережі — від 0%. Жодних прихованих платежів."],
      ["Які криптовалюти підтримуються?", "Bitcoin, Ethereum, USDT, USDC, BNB, TRX, SOL, LTC у 8 мережах. Список доступний у кабінеті."],
      ["Як працює автоконвертація?", "Якщо на балансі немає потрібної валюти для виплати, платформа виконує реальний on-chain своп через 1inch із вашого стейбла."],
      ["Чи безпечно зберігати кошти?", "Сід-фраза гарячого гаманця зберігається зашифрованою в базі (AES/Fernet), ключ — лише на сервері. Доступна 2FA для адміністратора."],
    ],
    cta_title: "Готові приймати криптоплатежі вже сьогодні?",
    cta_sub: "Підключення за 5 хвилин.",
    cta_btn: "Почати безкоштовно",
    foot_desc: "Крипто-платіжний шлюз для прийому, обміну та виведення криптовалют.",
    foot_product: "Продукт", foot_docs: "API Документація", foot_login: "Вхід", foot_contacts: "Контакти",
    foot_rights: "Усі права захищено.",
  },
  en: {
    nav_features: "Advantages", nav_currencies: "Currencies", nav_how: "Get started", nav_api: "API",
    login: "Log in", start: "Get started",
    hero_chip: "Own hot wallet · direct settlement",
    hero_h1: "Crypto payment acceptance for your business",
    hero_sub: "Accept Bitcoin, Ethereum, USDT and other crypto on your website or Telegram bot. Fast integration, auto-conversion to stablecoins and payouts straight to your wallets.",
    hero_cta1: "Get started", hero_cta2: "API docs",
    chips: [
      ["Fees from 0%", "No hidden charges or setup fees", Percent],
      ["Pay by QR code", "Clients pay in two clicks, no signup", QrCode],
      ["Up to 99.9% credited", "Automatic on-chain transaction detection", CheckCircle2],
      ["Fast integration", "Signed REST API with webhooks", Zap],
    ],
    adv_title: "Our advantages", adv_sub: "Everything to work with crypto payments in one dashboard.",
    adv: [
      ["Accept crypto payments", "Clients pay via QR checkout or their own wallet in a few clicks — no signup.", Download],
      ["Hot wallet", "HD wallet with automatic deposit sweeps and an encrypted mnemonic stored in the DB.", Flame],
      ["Auto-conversion", "Incoming payments auto-convert to USDT/USDC — protection from rate swings.", RefreshCw],
      ["Instant webhooks", "Signed invoice status notifications with retrying delivery.", Webhook],
      ["Referral program", "Invite projects and earn recurring income from their payments.", Gift],
      ["Low fees", "Flexible rates from 0% — you control fees in the cabinet.", Percent],
    ],
    sol_title: "Crypto payment solution",
    sol_sub: "Deposits, swaps and payouts — all in one dashboard.",
    sol: [
      ["Deposit", "Top up with any supported currency. The system shows the address, network and amount.", Download],
      ["Exchange", "Swap one currency for another right in your balance at the current rate.", RefreshCw],
      ["Send", "Send funds to any external wallet — pick coin, network and address.", Send],
    ],
    stats_title: "FozPay in numbers",
    stats: [["8", "blockchain networks"], ["< 1.2s", "webhook delivery"], ["99.9%", "payments credited"], ["0%", "starting fee"]],
    cur_title: "The most convenient payment methods for your clients",
    cur_sub: "Let clients pay in Bitcoin or any other crypto — from USDT and ETH to Solana. Checkout in a few clicks, no signup.",
    how_title: "Launch crypto payments in two steps",
    how: [
      ["Create an account", "Sign up in minutes. Access the cabinet, API keys and fee settings."],
      ["Connect acceptance", "Integrate via REST API or ready-made checkout. Clear docs and code samples."],
    ],
    api_title: "Integrate in minutes", api_sub: "Create invoices and payouts with a single request. Full control over statuses.",
    api_copy: "Copy",
    faq_title: "FAQ",
    faq: [
      ["How to connect crypto payments?", "Sign up, get an API key in the cabinet and integrate via REST API or ready-made checkout. It takes minutes."],
      ["What fees do you charge?", "The admin sets fees per currency and network in the cabinet — from 0%. No hidden charges."],
      ["Which cryptocurrencies are supported?", "Bitcoin, Ethereum, USDT, USDC, BNB, TRX, SOL, LTC across 8 networks."],
      ["How does auto-conversion work?", "If the balance lacks the target currency, the platform runs a real on-chain 1inch swap from your stablecoin."],
      ["Is it safe to store funds?", "The hot wallet mnemonic is stored encrypted in the DB (AES/Fernet); the key stays on the server. 2FA is available for the admin."],
    ],
    cta_title: "Ready to accept crypto today?",
    cta_sub: "Onboarding in 5 minutes.",
    cta_btn: "Start for free",
    foot_desc: "Crypto payment gateway to accept, swap and pay out crypto.",
    foot_product: "Product", foot_docs: "API Docs", foot_login: "Log in", foot_contacts: "Contacts",
    foot_rights: "All rights reserved.",
  },
};

const CODE = `curl -X POST https://fozpay.online/api/v1/private/create-output \\
  -H "X-Auth-Token: <token>" \\
  -H "X-Auth-Sign: <sign>" \\
  -d '{ "order_id": "1042", "currency": "USDC",
        "network": "Polygon", "amount": 150,
        "address": "0x7C59...4D03" }'

{ "status": true,
  "data": { "status": "Pending", "order_id": "1042",
            "currency": "USDC", "amount": 150 } }`;

function Brand({ dark }) {
  return (
    <div className="flex items-center gap-2.5" data-testid="landing-logo">
      <img src="/fozpay-mark.png" alt="FozPay" className="h-9 w-9 object-contain" />
      <span className="font-display text-xl font-extrabold tracking-tight">
        <span className={dark ? "text-white" : "text-slate-900"}>Foz</span>
        <span className="text-[#0D5C46]">Pay</span>
      </span>
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const { lang, setLang } = useLang();
  const tr = L[lang] || L.uk;
  const [openFaq, setOpenFaq] = useState(0);

  const go = () => navigate("/login");
  const copyCode = () => { navigator.clipboard.writeText(CODE); toast.success(lang === "uk" ? "Скопійовано" : "Copied"); };

  const navItems = [
    ["#features", tr.nav_features], ["#currencies", tr.nav_currencies],
    ["#how", tr.nav_how], ["#api", tr.nav_api],
  ];

  return (
    <div data-testid="landing-root" className="min-h-screen bg-[#F6F9F8] text-slate-800">
      {/* NAV */}
      <header data-testid="navbar-main" className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <Brand />
          <nav className="hidden items-center gap-8 lg:flex">
            {navItems.map(([href, label]) => (
              <a key={href} href={href} data-testid={`nav-${href.slice(1)}`}
                className="text-sm font-semibold text-slate-600 transition-colors hover:text-[#0D5C46]">{label}</a>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <button data-testid="landing-lang" onClick={() => setLang(lang === "uk" ? "en" : "uk")}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-mono font-semibold text-slate-600 hover:border-slate-300">
              {lang.toUpperCase()}
            </button>
            <button data-testid="nav-login" onClick={go}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300">
              {tr.login}
            </button>
            <button data-testid="nav-start" onClick={go} className="btn-foz hidden px-4 py-2 text-sm sm:block">
              {tr.start}
            </button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section data-testid="hero-section" className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 foz-grid-bg"
          style={{ maskImage: "radial-gradient(70% 60% at 50% 0%, black, transparent)", WebkitMaskImage: "radial-gradient(70% 60% at 50% 0%, black, transparent)" }} />
        <div className="relative mx-auto max-w-7xl px-5 pt-16 pb-14 sm:px-8 sm:pt-24">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-[#0D5C46]">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> {tr.hero_chip}
              </div>
              <h1 className="mt-6 font-display text-4xl font-extrabold leading-[1.08] tracking-tight text-slate-900 sm:text-5xl lg:text-[3.4rem]">
                {tr.hero_h1}
              </h1>
              <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-600">{tr.hero_sub}</p>
              <div className="mt-8 flex flex-wrap gap-3">
                <button data-testid="hero-cta-start" onClick={go} className="btn-foz inline-flex items-center gap-2 px-6 py-3 text-sm">
                  {tr.hero_cta1} <ArrowRight className="h-4 w-4" />
                </button>
                <button data-testid="hero-cta-docs" onClick={go}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-300">
                  <Terminal className="h-4 w-4" /> {tr.hero_cta2}
                </button>
              </div>
            </div>

            {/* light checkout preview card */}
            <div className="relative">
              <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_24px_60px_-20px_rgba(13,92,70,0.25)]">
                <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                  <div className="flex items-center gap-2.5">
                    <img src="/fozpay-mark.png" alt="F" className="h-9 w-9 object-contain" />
                    <div><div className="text-sm font-semibold text-slate-900">FozPay Checkout</div><div className="text-[11px] text-slate-400">invoice #A1B2C3</div></div>
                  </div>
                  <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">Live</span>
                </div>
                <div className="py-5 text-center">
                  <div className="text-xs text-slate-400">{lang === "uk" ? "До сплати" : "Amount due"}</div>
                  <div className="mt-1 font-display text-3xl font-extrabold text-slate-900">150.00 <span className="text-[#0D5C46]">USDC</span></div>
                  <div className="mt-1 text-xs text-slate-400">Polygon • ≈ 1.2s confirm</div>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {COINS.map((c) => (
                    <div key={c} className="flex flex-col items-center gap-1 rounded-xl border border-slate-100 bg-slate-50/80 py-2.5 transition hover:border-emerald-300 hover:bg-emerald-50/50">
                      <CoinIcon iso={c} size={26} />
                      <span className="text-[10px] font-mono text-slate-500">{c}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50 p-3">
                  <code className="truncate text-[11px] text-[#0D5C46]">0x7C59…4D03</code>
                  <RefreshCw className="h-4 w-4 animate-spin text-slate-300" style={{ animationDuration: "3s" }} />
                </div>
              </div>
            </div>
          </div>

          {/* feature chips row */}
          <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {tr.chips.map(([t, d, Icon], i) => (
              <div key={i} data-testid={`chip-${i}`} className="rounded-2xl border border-slate-200 bg-white p-5 transition-colors hover:border-emerald-300">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-[#0D5C46]"><Icon className="h-5 w-5" /></div>
                <div className="mt-3 text-sm font-bold text-slate-900">{t}</div>
                <div className="mt-1 text-xs leading-relaxed text-slate-500">{d}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ADVANTAGES */}
      <section id="features" data-testid="features-grid-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
        <SectionHead title={tr.adv_title} sub={tr.adv_sub} />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tr.adv.map(([t, d, Icon], i) => (
            <div key={i} data-testid={`feature-${t}`} className="group rounded-2xl border border-slate-200 bg-white p-6 transition-all duration-200 hover:border-emerald-300 hover:shadow-[0_18px_40px_-24px_rgba(13,92,70,0.4)]">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-50 text-[#0D5C46] transition-colors group-hover:bg-[#0D5C46] group-hover:text-white"><Icon className="h-5 w-5" /></div>
              <div className="mt-4 font-display text-lg font-bold text-slate-900">{t}</div>
              <div className="mt-1.5 text-sm leading-relaxed text-slate-500">{d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* SOLUTION: deposit / exchange / send */}
      <section data-testid="solution-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
        <SectionHead title={tr.sol_title} sub={tr.sol_sub} />
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {tr.sol.map(([t, d, Icon], i) => (
            <div key={i} data-testid={`solution-${i}`} className="rounded-2xl border border-slate-200 bg-gradient-to-b from-white to-emerald-50/40 p-6">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#0D5C46] text-white"><Icon className="h-5 w-5" /></div>
              <div className="mt-4 font-display text-xl font-bold text-slate-900">{t}</div>
              <div className="mt-1.5 text-sm leading-relaxed text-slate-500">{d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* STATS */}
      <section data-testid="stats-trust-section" className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <div className="grid gap-px overflow-hidden rounded-3xl border border-slate-200 bg-slate-200 sm:grid-cols-2 lg:grid-cols-4">
          {tr.stats.map(([v, l], i) => (
            <div key={i} className="bg-white p-8 text-center">
              <div className="font-display text-3xl font-extrabold text-[#0D5C46] sm:text-4xl">{v}</div>
              <div className="mt-1 text-sm text-slate-500">{l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* CURRENCIES */}
      <section id="currencies" data-testid="currencies-networks-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
        <SectionHead title={tr.cur_title} sub={tr.cur_sub} />
        <div className="mt-10 grid grid-cols-4 gap-3 sm:grid-cols-8">
          {COINS.map((c) => (
            <div key={c} data-testid={`coin-badge-${c}`} className="flex flex-col items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-4 transition hover:border-emerald-300 hover:shadow-sm">
              <CoinIcon iso={c} size={36} />
              <span className="text-xs font-mono font-semibold text-slate-600">{c}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {NETWORKS.map((n) => (
            <span key={n} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-mono text-slate-500">{n}</span>
          ))}
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" data-testid="how-it-works-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
        <SectionHead title={tr.how_title} />
        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {tr.how.map(([t, d], i) => (
            <div key={i} data-testid={`step-${i + 1}`} className="relative rounded-2xl border border-slate-200 bg-white p-7">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-50 font-display text-base font-extrabold text-[#0D5C46]">0{i + 1}</div>
              <div className="mt-4 font-display text-lg font-bold text-slate-900">{t}</div>
              <div className="mt-1.5 text-sm leading-relaxed text-slate-500">{d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* API TEASER */}
      <section id="api" data-testid="api-teaser-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <div>
            <SectionHead title={tr.api_title} sub={tr.api_sub} left />
            <ul className="mt-6 space-y-3">
              {["X-Auth-Sign", "IP allow-list", "Webhook retries", "Auto-convert"].map((x) => (
                <li key={x} className="flex items-center gap-2 text-sm font-medium text-slate-700"><CheckCircle2 className="h-4 w-4 text-emerald-500" /> {x}</li>
              ))}
            </ul>
          </div>
          <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-xl">
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
              <div className="flex gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-amber-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-emerald-400/70" />
              </div>
              <button data-testid="api-copy" onClick={copyCode} className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400 hover:text-emerald-400"><Copy className="h-3 w-3" /> {tr.api_copy}</button>
            </div>
            <pre className="overflow-x-auto p-4 text-[12px] leading-relaxed text-emerald-300">{CODE}</pre>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section data-testid="faq-section" className="mx-auto max-w-3xl px-5 py-16 sm:px-8">
        <SectionHead title={tr.faq_title} />
        <div className="mt-8 space-y-3">
          {tr.faq.map(([q, a], i) => (
            <div key={i} data-testid={`faq-${i}`} className="rounded-2xl border border-slate-200 bg-white">
              <button onClick={() => setOpenFaq(openFaq === i ? -1 : i)} className="flex w-full items-center justify-between gap-4 p-5 text-left">
                <span className="text-sm font-semibold text-slate-900">{q}</span>
                <ChevronDown className={`h-4 w-4 shrink-0 text-[#0D5C46] transition-transform ${openFaq === i ? "rotate-180" : ""}`} />
              </button>
              {openFaq === i && <div className="px-5 pb-5 text-sm leading-relaxed text-slate-500">{a}</div>}
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section data-testid="cta-banner-section" className="mx-auto max-w-7xl px-5 py-10 sm:px-8">
        <div className="relative overflow-hidden rounded-3xl bg-[#0D5C46] p-10 text-center sm:p-14">
          <div className="pointer-events-none absolute inset-0 foz-grid-bg opacity-40" />
          <h2 className="relative font-display text-2xl font-extrabold text-white sm:text-4xl">{tr.cta_title}</h2>
          <p className="relative mx-auto mt-3 max-w-xl text-emerald-100">{tr.cta_sub}</p>
          <button data-testid="cta-start" onClick={go} className="relative mt-7 inline-flex items-center gap-2 rounded-xl bg-white px-8 py-3.5 text-sm font-bold text-[#0D5C46] shadow-lg transition active:scale-95 hover:bg-emerald-50">
            {tr.cta_btn} <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </section>

      {/* FOOTER */}
      <footer data-testid="footer-main" className="border-t border-slate-200 bg-white">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-12 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <Brand />
            <p className="mt-3 max-w-sm text-sm text-slate-500">{tr.foot_desc}</p>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">{tr.foot_product}</div>
            <div className="mt-3 flex flex-col gap-2 text-sm text-slate-500">
              <button onClick={go} className="text-left hover:text-[#0D5C46]" data-testid="footer-docs">{tr.foot_docs}</button>
              <button onClick={go} className="text-left hover:text-[#0D5C46]" data-testid="footer-login">{tr.foot_login}</button>
              <button onClick={go} className="text-left hover:text-[#0D5C46]" data-testid="footer-contacts">{tr.foot_contacts}</button>
            </div>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">FozPay</div>
            <div className="mt-3 flex items-center gap-1 text-sm text-slate-500"><ShieldCheck className="h-4 w-4 text-[#0D5C46]" /> HD Hot Wallet</div>
            <a href="https://t.me" target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-[#0D5C46]">Telegram <ExternalLink className="h-3 w-3" /></a>
          </div>
        </div>
        <div className="border-t border-slate-100 px-5 py-5 text-center text-xs text-slate-400 sm:px-8">
          © {new Date().getFullYear()} FozPay. {tr.foot_rights}
        </div>
      </footer>
    </div>
  );
}

function SectionHead({ title, sub, left }) {
  return (
    <div className={left ? "" : "text-center"}>
      <h2 className="font-display text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl lg:text-4xl">{title}</h2>
      {sub && <p className={`mt-3 text-slate-500 ${left ? "" : "mx-auto max-w-2xl"}`}>{sub}</p>}
    </div>
  );
}
