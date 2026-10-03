import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Zap, ShieldCheck, ArrowRight, RefreshCw, Terminal, Layers,
  CheckCircle2, Lock, Cpu, Globe, ExternalLink, Copy, ChevronDown, Flame, Webhook,
} from "lucide-react";
import { useLang } from "@/lib/i18n";
import { CoinIcon } from "@/components/common";
import { toast } from "sonner";

const COINS = ["USDT", "USDC", "BTC", "ETH", "BNB", "TRX", "SOL", "LTC"];
const NETWORKS = ["ERC-20", "BEP-20", "TRC-20", "Polygon", "Arbitrum", "Solana", "Bitcoin", "Litecoin"];

const L = {
  uk: {
    nav_features: "Функціонал", nav_currencies: "Валюти", nav_api: "API", nav_how: "Як працює", nav_security: "Безпека",
    login: "Увійти", start: "Почати",
    hero_badge: "Крипто-еквайринг нового покоління • Без KYC для транзиту",
    hero_h1a: "Приймайте платежі у крипті", hero_h1b: "миттєво та без блокувань",
    hero_sub: "FozPay — платіжний шлюз для прийому, обміну та виведення криптовалют. Автоконвертація у стейбли, миттєві вебхуки та REST API для мерчантів.",
    hero_cta1: "Створити акаунт", hero_cta2: "Документація API",
    live: "Усі мережі працюють у штатному режимі",
    cur_title: "Валюти та мережі", cur_sub: "8 валют у 8 мережах — приймайте так, як зручно вашим клієнтам.",
    feat_title: "Все для прийому криптоплатежів", feat_sub: "Один шлюз замінює цілий фінансовий відділ.",
    f1t: "Миттєві інвойси", f1d: "Створення рахунку одним кліком: QR-чекаут, авто-закриття та вебхук після оплати.",
    f2t: "Автоконвертація при виведенні", f2d: "Немає потрібної валюти? Платформа зробить реальний on-chain своп через 1inch у стейбл.",
    f3t: "Гарячий гаманець", f3d: "HD-гаманець із авто-збором депозитів і безпечним зберіганням зашифрованого мнемоніка.",
    f4t: "Без KYC для транзиту", f4d: "Швидкі транзитні платежі без перевірок — кошти проходять без затримок.",
    f5t: "REST API для мерчантів", f5d: "Підпис запитів, IP-allowlist, статуси заявок та вебхуки з повторними спробами.",
    f6t: "Низька комісія", f6d: "Гнучкі тарифи від 0% — ви самі керуєте комісіями у кабінеті.",
    how_title: "Як це працює", how_sub: "Від інвойсу до виплати — чотири кроки.",
    s1t: "Створення інвойсу", s1d: "Через кабінет або REST API — вкажіть суму й валюту.",
    s2t: "Оплата клієнтом", s2d: "Клієнт обирає валюту та платить за QR-кодом.",
    s3t: "Зарахування", s3d: "Миттєве зарахування on-chain та авто-конвертація.",
    s4t: "Виведення", s4d: "Автоматична виплата через API або з кабінету.",
    api_title: "Інтеграція за хвилини", api_sub: "Створюйте заявки на виплату одним запитом. Повний контроль над статусами.",
    api_copy: "Скопіювати",
    stats_uptime: "Аптайм SLA", stats_latency: "Доставка вебхука", stats_chains: "Блокчейнів", stats_rate: "Стартова ставка", stats_kyc: "KYC-утримання транзиту",
    faq_title: "Часті запитання",
    faq: [
      ["Чи потрібен паспорт для початку?", "Ні. Для транзитних платежів KYC не вимагається — підключення займає кілька хвилин."],
      ["Як працює автоконвертація?", "Якщо на балансі немає потрібної валюти для виплати, платформа виконує реальний on-chain своп через 1inch із вашого стейбла."],
      ["Які комісії мереж?", "Комісію встановлює адміністратор у кабінеті окремо по кожній валюті та мережі — від 0%."],
      ["Чи можна інтегрувати в Telegram-бота або магазин?", "Так. REST API з підписом запитів підходить для будь-якого бекенду, бота чи CMS."],
    ],
    cta_title: "Готові приймати криптоплатежі вже сьогодні?",
    cta_sub: "Підключення за 5 хвилин — без очікування перевірок.",
    cta_btn: "Почати безкоштовно",
    foot_desc: "Крипто-платіжний шлюз для прийому, обміну та виведення криптовалют.",
    foot_product: "Продукт", foot_docs: "API Документація", foot_login: "Вхід", foot_contacts: "Контакти",
    foot_rights: "Усі права захищено.",
  },
  en: {
    nav_features: "Features", nav_currencies: "Currencies", nav_api: "API", nav_how: "How it works", nav_security: "Security",
    login: "Log in", start: "Get started",
    hero_badge: "Next-gen crypto acquiring • No KYC for transit",
    hero_h1a: "Accept crypto payments", hero_h1b: "instantly, without freezes",
    hero_sub: "FozPay is a payment gateway to accept, swap and pay out crypto. Auto-conversion to stablecoins, instant webhooks and a merchant REST API.",
    hero_cta1: "Create account", hero_cta2: "API docs",
    live: "All networks operational",
    cur_title: "Currencies & networks", cur_sub: "8 assets across 8 networks — accept however your clients prefer.",
    feat_title: "Everything to accept crypto", feat_sub: "One gateway replaces a whole finance stack.",
    f1t: "Instant invoices", f1d: "One-click invoice: QR checkout, auto-expiry and a webhook after payment.",
    f2t: "Auto-conversion on payout", f2d: "No target currency? The platform runs a real on-chain 1inch swap from a stablecoin.",
    f3t: "Hot wallet", f3d: "HD wallet with automatic deposit sweeps and an encrypted mnemonic.",
    f4t: "No KYC for transit", f4d: "Fast transit payments with no checks — funds pass without delays.",
    f5t: "Merchant REST API", f5d: "Signed requests, IP allow-list, payout statuses and retrying webhooks.",
    f6t: "Low fees", f6d: "Flexible rates from 0% — you control fees in the cabinet.",
    how_title: "How it works", how_sub: "From invoice to payout — four steps.",
    s1t: "Create invoice", s1d: "Via cabinet or REST API — set amount and currency.",
    s2t: "Client pays", s2d: "The client picks a currency and pays by QR.",
    s3t: "Credit", s3d: "Instant on-chain credit and auto-conversion.",
    s4t: "Payout", s4d: "Automatic payout via API or from the cabinet.",
    api_title: "Integrate in minutes", api_sub: "Create payouts with a single request. Full control over statuses.",
    api_copy: "Copy",
    stats_uptime: "Uptime SLA", stats_latency: "Webhook delivery", stats_chains: "Blockchains", stats_rate: "Starting rate", stats_kyc: "KYC hold for transit",
    faq_title: "FAQ",
    faq: [
      ["Do I need a passport to start?", "No. KYC is not required for transit payments — onboarding takes minutes."],
      ["How does auto-conversion work?", "If the balance lacks the target currency, the platform runs a real on-chain 1inch swap from your stablecoin."],
      ["What about network fees?", "Fees are set by the admin per currency and network — from 0%."],
      ["Can I integrate a Telegram bot or store?", "Yes. The signed REST API fits any backend, bot or CMS."],
    ],
    cta_title: "Ready to accept crypto today?",
    cta_sub: "Onboarding in 5 minutes — no waiting for checks.",
    cta_btn: "Start for free",
    foot_desc: "Crypto payment gateway to accept, swap and pay out crypto.",
    foot_product: "Product", foot_docs: "API Docs", foot_login: "Log in", foot_contacts: "Contacts",
    foot_rights: "All rights reserved.",
  },
};

const CODE = `curl -X POST https://api.fozpay.io/api/v1/private/create-output \\
  -H "X-Auth-Token: <token>" \\
  -H "X-Auth-Sign: <sign>" \\
  -d '{ "order_id": "1042", "currency": "USDC",
        "network": "Polygon", "amount": 150,
        "address": "0x7C59...4D03" }'

{ "status": true,
  "data": { "status": "Pending", "order_id": "1042",
            "currency": "USDC", "amount": 150 } }`;

function Brand() {
  return (
    <div className="flex items-center gap-2.5" data-testid="landing-logo">
      <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-violet-500 text-slate-950 shadow-[0_0_20px_rgba(139,92,246,0.45)]">
        <Zap className="h-5 w-5" strokeWidth={2.6} />
      </div>
      <span className="text-xl font-extrabold tracking-tight" style={{ fontFamily: "Sora, sans-serif" }}>
        <span className="text-white">Foz</span><span className="text-violet-500">Pay</span>
      </span>
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const { lang, setLang } = useLang();
  const tr = L[lang] || L.uk;
  const [openFaq, setOpenFaq] = useState(0);

  useEffect(() => {
    const id = "foz-landing-fonts";
    if (!document.getElementById(id)) {
      const link = document.createElement("link");
      link.id = id;
      link.rel = "stylesheet";
      link.href = "https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap";
      document.head.appendChild(link);
    }
  }, []);

  const go = () => navigate("/login");
  const copyCode = () => { navigator.clipboard.writeText(CODE); toast.success(lang === "uk" ? "Скопійовано" : "Copied"); };

  const navItems = [
    ["#features", tr.nav_features], ["#currencies", tr.nav_currencies],
    ["#api", tr.nav_api], ["#how", tr.nav_how], ["#security", tr.nav_security],
  ];

  return (
    <div data-testid="landing-root" className="foz-landing-root min-h-screen text-white"
      style={{ background: "#07090e", fontFamily: "Manrope, sans-serif" }}>
      {/* mesh + dot-matrix */}
      <div className="pointer-events-none fixed inset-0 z-0"
        style={{ background: "radial-gradient(circle at 50% -10%, rgba(139,92,246,0.14) 0%, rgba(217,70,239,0.05) 32%, transparent 68%)" }} />
      <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.25]"
        style={{ backgroundImage: "radial-gradient(rgba(255,255,255,0.09) 1px, transparent 1px)", backgroundSize: "26px 26px" }} />

      <div className="relative z-10">
        {/* NAV */}
        <header data-testid="navbar-main" className="sticky top-0 z-40 border-b border-white/10 backdrop-blur-xl" style={{ background: "rgba(7,9,14,0.75)" }}>
          <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
            <Brand />
            <nav className="hidden items-center gap-8 lg:flex">
              {navItems.map(([href, label]) => (
                <a key={href} href={href} data-testid={`nav-${href.slice(1)}`}
                  className="text-sm font-medium text-slate-400 transition-colors hover:text-violet-500">{label}</a>
              ))}
            </nav>
            <div className="flex items-center gap-2">
              <button data-testid="landing-lang" onClick={() => setLang(lang === "uk" ? "en" : "uk")}
                className="rounded-full border border-white/10 px-3 py-1.5 text-xs font-mono font-medium text-slate-300 hover:border-violet-500/50">
                {lang.toUpperCase()}
              </button>
              <button data-testid="nav-login" onClick={go}
                className="rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10">
                {tr.login}
              </button>
              <button data-testid="nav-start" onClick={go}
                className="hidden rounded-full bg-violet-500 px-4 py-2 text-sm font-semibold text-slate-950 shadow-[0_0_20px_rgba(139,92,246,0.35)] transition active:scale-95 hover:bg-violet-400 sm:block">
                {tr.start}
              </button>
            </div>
          </div>
        </header>

        {/* HERO */}
        <section data-testid="hero-section" className="mx-auto max-w-7xl px-5 pt-16 pb-20 sm:px-8 sm:pt-24">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1.5 text-xs font-medium text-violet-400 shadow-[0_0_15px_rgba(139,92,246,0.2)]">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-500" /> {tr.hero_badge}
              </div>
              <h1 className="mt-6 text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl" style={{ fontFamily: "Sora, sans-serif" }}>
                {tr.hero_h1a}<br /><span className="text-violet-500">{tr.hero_h1b}</span>
              </h1>
              <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-400">{tr.hero_sub}</p>
              <div className="mt-8 flex flex-wrap gap-3">
                <button data-testid="hero-cta-start" onClick={go}
                  className="inline-flex items-center gap-2 rounded-full bg-violet-500 px-6 py-3 text-sm font-semibold text-slate-950 shadow-[0_0_24px_rgba(139,92,246,0.4)] transition active:scale-95 hover:bg-violet-400">
                  {tr.hero_cta1} <ArrowRight className="h-4 w-4" />
                </button>
                <button data-testid="hero-cta-docs" onClick={go}
                  className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-6 py-3 text-sm font-semibold text-white transition hover:bg-white/10">
                  <Terminal className="h-4 w-4" /> {tr.hero_cta2}
                </button>
              </div>
              <div className="mt-6 inline-flex items-center gap-2 text-xs font-mono text-slate-500">
                <span className="h-2 w-2 rounded-full bg-violet-500 shadow-[0_0_8px_rgba(139,92,246,0.8)]" /> {tr.live}
              </div>
            </div>

            {/* live checkout preview card */}
            <div className="relative">
              <div className="absolute -inset-4 -z-10 rounded-[2rem] bg-violet-500/10 blur-3xl" />
              <div className="rounded-2xl border border-white/10 p-6 shadow-[0_20px_50px_rgba(0,0,0,0.6)]" style={{ background: "rgba(13,17,23,0.9)" }}>
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500 font-bold text-slate-950">F</div>
                    <div><div className="text-sm font-semibold text-white">FozPay Checkout</div><div className="text-[11px] text-slate-500">invoice #A1B2C3</div></div>
                  </div>
                  <span className="rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-1 text-[11px] font-medium text-violet-400">Live</span>
                </div>
                <div className="py-5 text-center">
                  <div className="text-xs text-slate-500">{lang === "uk" ? "До сплати" : "Amount due"}</div>
                  <div className="mt-1 text-3xl font-extrabold text-white" style={{ fontFamily: "Sora, sans-serif" }}>150.00 <span className="text-violet-500">USDC</span></div>
                  <div className="mt-1 text-xs text-slate-500">Polygon • ≈ 1.2s confirm</div>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {COINS.slice(0, 8).map((c) => (
                    <div key={c} className="flex flex-col items-center gap-1 rounded-xl border border-white/10 bg-white/5 py-2.5 transition hover:border-violet-500/50">
                      <CoinIcon iso={c} size={26} />
                      <span className="text-[10px] font-mono text-slate-400">{c}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex items-center justify-between rounded-xl border border-white/10 bg-black/40 p-3">
                  <code className="truncate text-[11px] text-violet-500" style={{ fontFamily: "JetBrains Mono, monospace" }}>0x7C59…4D03</code>
                  <RefreshCw className="h-4 w-4 animate-spin text-slate-500" style={{ animationDuration: "3s" }} />
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* CURRENCIES */}
        <section id="currencies" data-testid="currencies-networks-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionHead title={tr.cur_title} sub={tr.cur_sub} />
          <div className="mt-8 flex flex-wrap gap-3">
            {COINS.map((c) => (
              <div key={c} data-testid={`coin-badge-${c}`} className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3.5 py-2 text-sm font-mono font-medium text-slate-200 transition hover:border-violet-500/50 hover:bg-violet-500/10">
                <CoinIcon iso={c} size={22} /> {c}
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {NETWORKS.map((n) => (
              <span key={n} className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-mono text-slate-400">{n}</span>
            ))}
          </div>
        </section>

        {/* FEATURES BENTO */}
        <section id="features" data-testid="features-grid-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionHead title={tr.feat_title} sub={tr.feat_sub} />
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Feature icon={Zap} t={tr.f1t} d={tr.f1d} big />
            <Feature icon={RefreshCw} t={tr.f2t} d={tr.f2d} />
            <Feature icon={Flame} t={tr.f3t} d={tr.f3d} />
            <Feature icon={Lock} t={tr.f4t} d={tr.f4d} />
            <Feature icon={Webhook} t={tr.f5t} d={tr.f5d} />
            <Feature icon={Layers} t={tr.f6t} d={tr.f6d} />
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" data-testid="how-it-works-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <SectionHead title={tr.how_title} sub={tr.how_sub} />
          <div className="mt-10 grid gap-4 md:grid-cols-4">
            {[[tr.s1t, tr.s1d], [tr.s2t, tr.s2d], [tr.s3t, tr.s3d], [tr.s4t, tr.s4d]].map(([t, d], i) => (
              <div key={i} data-testid={`step-${i + 1}`} className="relative rounded-2xl border border-white/10 p-6" style={{ background: "rgba(15,20,29,0.9)" }}>
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 font-mono text-sm font-bold text-violet-500">0{i + 1}</div>
                <div className="mt-4 text-lg font-semibold text-white" style={{ fontFamily: "Sora, sans-serif" }}>{t}</div>
                <div className="mt-1.5 text-sm text-slate-400">{d}</div>
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
                  <li key={x} className="flex items-center gap-2 text-sm text-slate-300"><CheckCircle2 className="h-4 w-4 text-violet-500" /> {x}</li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-white/10 p-1" style={{ background: "#090c12" }}>
              <div className="flex items-center justify-between px-4 py-2.5">
                <div className="flex gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-rose-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-amber-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-violet-500/70" />
                </div>
                <button data-testid="api-copy" onClick={copyCode} className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400 hover:text-violet-500"><Copy className="h-3 w-3" /> {tr.api_copy}</button>
              </div>
              <pre className="overflow-x-auto rounded-lg p-4 text-[12px] leading-relaxed text-violet-500" style={{ fontFamily: "JetBrains Mono, monospace" }}>{CODE}</pre>
            </div>
          </div>
        </section>

        {/* STATS */}
        <section id="security" data-testid="stats-trust-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <div className="grid gap-4 rounded-3xl border border-white/10 p-8 sm:grid-cols-3 lg:grid-cols-5" style={{ background: "rgba(13,17,23,0.7)" }}>
            {[["99.98%", tr.stats_uptime, Globe], ["< 1.2s", tr.stats_latency, Zap], ["8+", tr.stats_chains, Layers], ["0%", tr.stats_rate, RefreshCw], ["$0", tr.stats_kyc, ShieldCheck]].map(([v, l, Icon], i) => (
              <div key={i} className="text-center">
                <Icon className="mx-auto h-5 w-5 text-violet-500" />
                <div className="mt-2 text-2xl font-extrabold text-white" style={{ fontFamily: "Sora, sans-serif" }}>{v}</div>
                <div className="mt-0.5 text-xs text-slate-400">{l}</div>
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section data-testid="faq-section" className="mx-auto max-w-3xl px-5 py-16 sm:px-8">
          <SectionHead title={tr.faq_title} />
          <div className="mt-8 space-y-3">
            {tr.faq.map(([q, a], i) => (
              <div key={i} data-testid={`faq-${i}`} className="rounded-2xl border border-white/10" style={{ background: "rgba(15,20,29,0.8)" }}>
                <button onClick={() => setOpenFaq(openFaq === i ? -1 : i)} className="flex w-full items-center justify-between gap-4 p-5 text-left">
                  <span className="text-sm font-semibold text-white">{q}</span>
                  <ChevronDown className={`h-4 w-4 shrink-0 text-violet-500 transition-transform ${openFaq === i ? "rotate-180" : ""}`} />
                </button>
                {openFaq === i && <div className="px-5 pb-5 text-sm text-slate-400">{a}</div>}
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section data-testid="cta-banner-section" className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
          <div className="relative overflow-hidden rounded-3xl border border-violet-500/30 p-10 text-center shadow-[0_0_40px_rgba(139,92,246,0.15)]" style={{ background: "linear-gradient(135deg, rgba(139,92,246,0.08), rgba(217,70,239,0.05))" }}>
            <h2 className="text-2xl font-bold text-white sm:text-4xl" style={{ fontFamily: "Sora, sans-serif" }}>{tr.cta_title}</h2>
            <p className="mx-auto mt-3 max-w-xl text-slate-300">{tr.cta_sub}</p>
            <button data-testid="cta-start" onClick={go} className="mt-7 inline-flex items-center gap-2 rounded-full bg-violet-500 px-8 py-3.5 text-sm font-semibold text-slate-950 shadow-[0_0_24px_rgba(139,92,246,0.45)] transition active:scale-95 hover:bg-violet-400">
              {tr.cta_btn} <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </section>

        {/* FOOTER */}
        <footer data-testid="footer-main" className="border-t border-white/10">
          <div className="mx-auto grid max-w-7xl gap-8 px-5 py-12 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
            <div className="lg:col-span-2">
              <Brand />
              <p className="mt-3 max-w-sm text-sm text-slate-500">{tr.foot_desc}</p>
              <div className="mt-4 inline-flex items-center gap-2 text-xs font-mono text-violet-500">
                <span className="h-2 w-2 rounded-full bg-violet-500 shadow-[0_0_8px_rgba(139,92,246,0.8)]" /> {tr.live}
              </div>
            </div>
            <div>
              <div className="text-sm font-semibold text-white">{tr.foot_product}</div>
              <div className="mt-3 flex flex-col gap-2 text-sm text-slate-400">
                <button onClick={go} className="text-left hover:text-violet-500" data-testid="footer-docs">{tr.foot_docs}</button>
                <button onClick={go} className="text-left hover:text-violet-500" data-testid="footer-login">{tr.foot_login}</button>
                <button onClick={go} className="text-left hover:text-violet-500" data-testid="footer-contacts">{tr.foot_contacts}</button>
              </div>
            </div>
            <div>
              <div className="text-sm font-semibold text-white">FozPay</div>
              <div className="mt-3 flex items-center gap-1 text-sm text-slate-400"><Cpu className="h-4 w-4 text-violet-500" /> HD Hot Wallet</div>
              <a href="https://t.me" target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-violet-500">Telegram <ExternalLink className="h-3 w-3" /></a>
            </div>
          </div>
          <div className="border-t border-white/10 px-5 py-5 text-center text-xs text-slate-600 sm:px-8">
            © {new Date().getFullYear()} FozPay. {tr.foot_rights}
          </div>
        </footer>
      </div>
    </div>
  );
}

function SectionHead({ title, sub, left }) {
  return (
    <div className={left ? "" : "text-center"}>
      <h2 className="text-2xl font-bold tracking-tight text-white sm:text-3xl lg:text-4xl" style={{ fontFamily: "Sora, sans-serif" }}>{title}</h2>
      {sub && <p className={`mt-3 text-slate-400 ${left ? "" : "mx-auto max-w-2xl"}`}>{sub}</p>}
    </div>
  );
}

function Feature({ icon: Icon, t, d, big }) {
  return (
    <div data-testid={`feature-${t}`} className={`rounded-2xl border border-white/10 p-6 transition-colors duration-200 hover:border-violet-500/40 ${big ? "sm:col-span-2 lg:col-span-1" : ""}`} style={{ background: "rgba(15,20,29,0.9)" }}>
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/15 text-violet-500"><Icon className="h-5 w-5" /></div>
      <div className="mt-4 text-lg font-semibold text-white" style={{ fontFamily: "Sora, sans-serif" }}>{t}</div>
      <div className="mt-1.5 text-sm leading-relaxed text-slate-400">{d}</div>
    </div>
  );
}
