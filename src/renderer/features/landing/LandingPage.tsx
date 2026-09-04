/**
 * Flow Marketing Landing Page
 * Premium SaaS landing experience — dark-first, EN + AR, responsive.
 * Uses design-system.css tokens. No fake data, no stock images.
 */
import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { motion, useReducedMotion } from "framer-motion";
import AxonLogo from "../../AxonLogo";
import { useLangContext } from "../../contexts/lang";
import "./landing.css";

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  onSignIn: () => void;
  onSignUp: () => void;
}

// ── Scroll-triggered animation hook ──────────────────────────────────────────

function useInView(threshold = 0.1) {
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Use lp-scroll-root as IntersectionObserver root so animations fire
    // correctly when content scrolls inside our custom scrollable container.
    const scrollRoot = document.getElementById("lp-scroll-root");
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) { setInView(true); obs.disconnect(); }
      },
      { threshold, root: scrollRoot ?? null },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return { ref, inView };
}

// ── Inline SVG Icons ──────────────────────────────────────────────────────────

function AgentIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4"/>
      <path d="M6 20v-2a6 6 0 0 1 12 0v2"/>
      <circle cx="18.5" cy="8.5" r="1.5" fill="currentColor" opacity="0.4"/>
      <circle cx="5.5" cy="8.5" r="1.5" fill="currentColor" opacity="0.4"/>
    </svg>
  );
}

function WorkflowIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h4v4H3zM10 6h4v4h-4zM17 6h4v4h-4z"/>
      <path d="M3 14h4v4H3zM10 14h4v4h-4z"/>
      <path d="M7 8h3M14 8h3M5 10v4M12 10v4"/>
    </svg>
  );
}

function AgentOSIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2"/>
      <path d="M8 21h8M12 17v4"/>
      <path d="M6 7h.01M6 11h12M6 9h7"/>
    </svg>
  );
}

function GatewayIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2 2 7l10 5 10-5-10-5z"/>
      <path d="M2 17l10 5 10-5"/>
      <path d="M2 12l10 5 10-5"/>
    </svg>
  );
}

function MemoryIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="6" width="20" height="12" rx="3"/>
      <path d="M6 10v4M10 10v4M14 10v4M18 10v4"/>
    </svg>
  );
}

function IntegrationIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="6" r="3"/>
      <circle cx="18" cy="6" r="3"/>
      <circle cx="6" cy="18" r="3"/>
      <circle cx="18" cy="18" r="3"/>
      <path d="M9 6h6M6 9v6M18 9v6M9 18h6"/>
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14M12 5l7 7-7 7"/>
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6"/>
    </svg>
  );
}

function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="12" x2="21" y2="12"/>
      <line x1="3" y1="6" x2="21" y2="6"/>
      <line x1="3" y1="18" x2="21" y2="18"/>
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/>
      <line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  );
}

// ── Animated Pipeline Visualization ──────────────────────────────────────────

interface PipelineStep { icon: string; name: string; detail: string; }

function PipelineViz({ steps }: { steps: PipelineStep[] }) {
  const [activeIdx, setActiveIdx] = useState(0);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce) return;
    const interval = setInterval(() => {
      setActiveIdx(prev => (prev + 1) % steps.length);
    }, 1800);
    return () => clearInterval(interval);
  }, [steps.length, reduce]);

  return (
    <div className="lp-pipeline" role="presentation" aria-hidden="true">
      <div className="lp-pipeline__header">Flow · Live Run</div>
      <div className="lp-pipeline__steps">
        {steps.map((step, i) => {
          const isDone = reduce ? true : i < activeIdx;
          const isActive = reduce ? false : i === activeIdx;
          const state = isDone ? "done" : isActive ? "active" : "pending";
          return (
            <div
              key={i}
              className={`lp-pipeline__step ${state}`}
              style={{ transitionDelay: `${i * 40}ms` }}
            >
              <div className="lp-pipeline__step-icon">
                {isDone ? "✓" : step.icon}
              </div>
              <div className="lp-pipeline__step-info">
                <div className="lp-pipeline__step-name">{step.name}</div>
                <div className="lp-pipeline__step-detail">{step.detail}</div>
              </div>
              <div className="lp-pipeline__step-status">
                {isActive && (
                  <div className="lp-running">
                    <span /><span /><span />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Navigation ────────────────────────────────────────────────────────────────

function Nav({ onSignIn, onSignUp }: Props) {
  const { t } = useTranslation("landing");
  const { lang, toggleLang } = useLangContext();
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // Find the scrollable landing root
    const root = document.getElementById("lp-scroll-root");
    rootRef.current = root;
    if (!root) return;
    const onScroll = () => setScrolled(root.scrollTop > 20);
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, []);

  // Lock body scroll when mobile menu is open
  useEffect(() => {
    document.body.style.overflow = menuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [menuOpen]);

  function scrollTo(id: string) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth" });
    setMenuOpen(false);
  }

  return (
    <>
      <nav
        className={`lp-nav ${scrolled ? "lp-nav--scrolled" : ""}`}
        role="navigation"
        aria-label="Main navigation"
      >
        {/* Brand */}
        <button
          className="lp-nav__brand"
          style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
          onClick={() => scrollTo("lp-hero")}
          aria-label="Flow — home"
        >
          <AxonLogo size={32} />
          <span className="lp-nav__wordmark">Flow</span>
        </button>

        {/* Desktop links */}
        <ul className="lp-nav__links">
          <li>
            <button className="lp-nav__link" onClick={() => scrollTo("lp-features")}>
              {t("nav.product")}
            </button>
          </li>
          <li>
            <button className="lp-nav__link" onClick={() => scrollTo("lp-how")}>
              {t("nav.howItWorks")}
            </button>
          </li>
          <li>
            <button className="lp-nav__link" onClick={() => scrollTo("lp-pricing")}>
              {t("nav.pricing")}
            </button>
          </li>
        </ul>

        {/* Desktop actions */}
        <div className="lp-nav__actions">
          <button
            className="lp-nav__lang"
            onClick={toggleLang}
            aria-label={lang === "en" ? "التبديل إلى العربية" : "Switch to English"}
          >
            {lang === "en" ? "العربية" : "English"}
          </button>
          <button className="lp-nav__signin" onClick={onSignIn}>
            {t("nav.signIn")}
          </button>
          <button className="lp-nav__cta" onClick={onSignUp}>
            {t("nav.startFree")}
          </button>
        </div>

        {/* Hamburger */}
        <button
          className="lp-nav__hamburger"
          onClick={() => setMenuOpen(true)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
        >
          <MenuIcon />
        </button>
      </nav>

      {/* Mobile menu */}
      <div
        className={`lp-nav__mobile-menu ${menuOpen ? "open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
      >
        <div className="lp-nav__mobile-header">
          <button
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 10 }}
            onClick={() => { scrollTo("lp-hero"); setMenuOpen(false); }}
          >
            <AxonLogo size={28} />
            <span className="lp-nav__wordmark">Flow</span>
          </button>
          <button
            className="lp-nav__hamburger"
            onClick={() => setMenuOpen(false)}
            aria-label="Close menu"
          >
            <CloseIcon />
          </button>
        </div>
        <ul className="lp-nav__mobile-links">
          <li>
            <button className="lp-nav__mobile-link" onClick={() => scrollTo("lp-features")}>
              {t("nav.product")}
            </button>
          </li>
          <li>
            <button className="lp-nav__mobile-link" onClick={() => scrollTo("lp-how")}>
              {t("nav.howItWorks")}
            </button>
          </li>
          <li>
            <button className="lp-nav__mobile-link" onClick={() => scrollTo("lp-pricing")}>
              {t("nav.pricing")}
            </button>
          </li>
        </ul>
        <div className="lp-nav__mobile-actions">
          <button className="lp-nav__mobile-signin" onClick={() => { onSignIn(); setMenuOpen(false); }}>
            {t("nav.signIn")}
          </button>
          <button className="lp-nav__mobile-cta" onClick={() => { onSignUp(); setMenuOpen(false); }}>
            {t("nav.startFree")}
          </button>
          <button
            style={{ background: "none", border: "none", color: "var(--t4)", fontSize: 13, cursor: "pointer", textAlign: "center", padding: 8, fontFamily: "var(--font-sans)" }}
            onClick={() => { toggleLang(); setMenuOpen(false); }}
          >
            {lang === "en" ? "التبديل إلى العربية" : "Switch to English"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Hero Section ──────────────────────────────────────────────────────────────

function HeroSection({ onSignUp }: Pick<Props, "onSignUp">) {
  const { t } = useTranslation("landing");
  const reduce = useReducedMotion();

  const pipelineSteps: PipelineStep[] = [
    { icon: "💡", name: t("hero.pipeline.step1"), detail: "Natural language input" },
    { icon: "🤖", name: t("hero.pipeline.step2"), detail: "Specialized AI worker" },
    { icon: "⚙️", name: t("hero.pipeline.step3"), detail: "Sequential + parallel" },
    { icon: "🔄", name: t("hero.pipeline.step4"), detail: "Scheduled & triggered" },
    { icon: "✅", name: t("hero.pipeline.step5"), detail: "Delivered & monitored" },
  ];

  const container = {
    hidden: {},
    show: { transition: { staggerChildren: reduce ? 0 : 0.12 } },
  } as const;
  const item = {
    hidden: { opacity: 0, y: reduce ? 0 : 22 },
    show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: "easeOut" as const } },
  } as const;

  return (
    <section id="lp-hero" className="lp-hero" aria-labelledby="hero-headline">
      {/* Background glows */}
      <div className="lp-hero__bg" aria-hidden="true">
        <div className="lp-hero__glow1" />
        <div className="lp-hero__glow2" />
      </div>

      <div className="lp-hero__grid lp-container">
        {/* Left: copy */}
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
        >
          <motion.div variants={item}>
            <div className="lp-hero__badge" aria-label={t("hero.eyebrow")}>
              <span className="lp-hero__badge-dot" aria-hidden="true" />
              {t("hero.eyebrow")}
            </div>
          </motion.div>

          <motion.h1
            id="hero-headline"
            className="lp-hero__headline"
            variants={item}
          >
            {t("hero.headline1")}{" "}
            <br />
            <span>{t("hero.headline2")}</span>
          </motion.h1>

          <motion.p className="lp-hero__sub" variants={item}>
            {t("hero.sub")}
          </motion.p>

          <motion.div className="lp-hero__actions" variants={item}>
            <button
              className="lp-btn-primary"
              onClick={onSignUp}
              aria-label={t("hero.ctaPrimary")}
            >
              {t("hero.ctaPrimary")}
              <ArrowIcon />
            </button>
            <button
              className="lp-btn-ghost"
              onClick={() => document.getElementById("lp-how")?.scrollIntoView({ behavior: "smooth" })}
            >
              {t("hero.ctaSecondary")}
              <ChevronDownIcon />
            </button>
          </motion.div>
        </motion.div>

        {/* Right: animated pipeline */}
        <motion.div
          initial={{ opacity: 0, x: reduce ? 0 : 32 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
        >
          <PipelineViz steps={pipelineSteps} />
        </motion.div>
      </div>
    </section>
  );
}

// ── Core Value Section ────────────────────────────────────────────────────────

function CoreValueSection() {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  const steps = t("coreValue.steps", { returnObjects: true }) as string[];

  return (
    <section className="lp-section lp-corevalue" aria-labelledby="corevalue-headline">
      <div
        ref={ref}
        className={`lp-animate ${inView ? "lp-in" : ""} lp-container`}
      >
        <div className="lp-corevalue__grid">
          {/* Left copy */}
          <div>
            <div className="lp-eyebrow">{t("coreValue.eyebrow")}</div>
            <h2 id="corevalue-headline" className="lp-h2">{t("coreValue.headline")}</h2>
            <p className="lp-body">{t("coreValue.body")}</p>
          </div>

          {/* Right: workflow demo card */}
          <div className="lp-workflow-demo" role="presentation" aria-hidden="true">
            {/* Request bubble */}
            <div className="lp-workflow-demo__request">
              <div className="lp-workflow-demo__request-label">{t("coreValue.exampleLabel")}</div>
              <span style={{ fontSize: 13, color: "var(--t2)", fontStyle: "italic" }}>
                "{t("coreValue.exampleRequest")}"
              </span>
            </div>

            {/* Arrow */}
            <div className="lp-workflow-demo__arrow">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12l7 7 7-7"/>
              </svg>
            </div>

            {/* Pipeline steps */}
            <div className="lp-workflow-demo__steps">
              {steps.map((step, i) => (
                <div key={i} className="lp-workflow-demo__step">
                  <div className="lp-workflow-demo__node">{step}</div>
                  {i < steps.length - 1 && (
                    <div className="lp-workflow-demo__connector" aria-hidden="true" />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Features Section ──────────────────────────────────────────────────────────

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  body: string;
  detail: string;
  delay: string;
  inView: boolean;
}

function FeatureCard({ icon, title, body, detail, delay, inView }: FeatureCardProps) {
  return (
    <div className={`lp-feature-card lp-animate ${inView ? `lp-in ${delay}` : ""}`}>
      <div className="lp-feature-card__icon" aria-hidden="true">{icon}</div>
      <div className="lp-feature-card__title">{title}</div>
      <div className="lp-feature-card__body">{body}</div>
      <div className="lp-feature-card__detail">{detail}</div>
    </div>
  );
}

function FeaturesSection() {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  const features = [
    { key: "agents",       icon: <AgentIcon />,      delay: "d1" },
    { key: "workflows",    icon: <WorkflowIcon />,    delay: "d2" },
    { key: "agentos",      icon: <AgentOSIcon />,     delay: "d3" },
    { key: "gateway",      icon: <GatewayIcon />,     delay: "d4" },
    { key: "memory",       icon: <MemoryIcon />,      delay: "d5" },
    { key: "integrations", icon: <IntegrationIcon />, delay: "d6" },
  ] as const;

  return (
    <section id="lp-features" className="lp-section lp-section--center" aria-labelledby="features-headline">
      <div className="lp-container">
        <div ref={ref} className={`lp-animate ${inView ? "lp-in" : ""}`}>
          <div className="lp-eyebrow">{t("features.eyebrow")}</div>
          <h2 id="features-headline" className="lp-h2">{t("features.headline")}</h2>
          <p className="lp-body">{t("features.sub")}</p>
        </div>

        <div className="lp-features__grid">
          {features.map(f => (
            <FeatureCard
              key={f.key}
              icon={f.icon}
              title={t(`features.${f.key}.title`)}
              body={t(`features.${f.key}.body`)}
              detail={t(`features.${f.key}.detail`)}
              delay={f.delay}
              inView={inView}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

// ── How It Works Section ──────────────────────────────────────────────────────

function HowItWorksSection() {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  interface HowStep { number: string; title: string; body: string; }
  const steps = t("howItWorks.steps", { returnObjects: true }) as HowStep[];

  return (
    <section id="lp-how" className="lp-section" style={{ background: "var(--bg-surface)" }} aria-labelledby="how-headline">
      <div className="lp-container">
        <div ref={ref} className={`lp-animate ${inView ? "lp-in" : ""}`}>
          <div className="lp-eyebrow">{t("howItWorks.eyebrow")}</div>
          <h2 id="how-headline" className="lp-h2">{t("howItWorks.headline")}</h2>
        </div>

        <ol className="lp-how__steps" aria-label="How Flow works">
          {steps.map((step, i) => (
            <li
              key={i}
              className={`lp-how__step lp-animate ${inView ? `lp-in d${i + 1}` : ""}`}
            >
              <div className="lp-how__step-num" aria-hidden="true">{step.number}</div>
              <div>
                <div className="lp-how__step-title">{step.title}</div>
                <div className="lp-how__step-body">{step.body}</div>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ── Use Cases Section ─────────────────────────────────────────────────────────

function UseCasesSection() {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  interface UseCase { title: string; emoji: string; steps: string[]; }
  const cases = t("useCases.cases", { returnObjects: true }) as UseCase[];

  return (
    <section className="lp-section" aria-labelledby="cases-headline">
      <div className="lp-container">
        <div ref={ref} className={`lp-animate ${inView ? "lp-in" : ""}`}>
          <div className="lp-eyebrow">{t("useCases.eyebrow")}</div>
          <h2 id="cases-headline" className="lp-h2">{t("useCases.headline")}</h2>
        </div>

        <div className="lp-cases__grid">
          {cases.map((c, i) => (
            <div
              key={i}
              className={`lp-case-card lp-animate ${inView ? `lp-in d${i + 1}` : ""}`}
            >
              <span className="lp-case-card__emoji" aria-hidden="true">{c.emoji}</span>
              <div className="lp-case-card__title">{c.title}</div>
              <div className="lp-case-card__flow" role="list" aria-label={`${c.title} workflow steps`}>
                {c.steps.map((step, j) => (
                  <div key={j} role="listitem">
                    <div className="lp-case-card__step">
                      <div className="lp-case-card__step-dot" aria-hidden="true" />
                      <span>{step}</span>
                    </div>
                    {j < c.steps.length - 1 && (
                      <div className="lp-case-card__step-line" aria-hidden="true"
                        style={{ marginInlineStart: 3 }} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Benefits Section ──────────────────────────────────────────────────────────

function BenefitsSection() {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  interface BenefitItem { emoji: string; title: string; body: string; }
  const items = t("benefits.items", { returnObjects: true }) as BenefitItem[];

  return (
    <section className="lp-section lp-benefits" aria-labelledby="benefits-headline">
      <div className="lp-container">
        <div ref={ref} className={`lp-animate ${inView ? "lp-in" : ""}`}>
          <div className="lp-eyebrow">{t("benefits.eyebrow")}</div>
          <h2 id="benefits-headline" className="lp-h2">{t("benefits.headline")}</h2>
        </div>

        <div className="lp-benefits__grid">
          {items.map((item, i) => (
            <div
              key={i}
              className={`lp-benefit-card lp-animate ${inView ? `lp-in d${i + 1}` : ""}`}
            >
              <div className="lp-benefit-card__emoji" aria-hidden="true">{item.emoji}</div>
              <div className="lp-benefit-card__title">{item.title}</div>
              <div className="lp-benefit-card__body">{item.body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Trust Section ─────────────────────────────────────────────────────────────

function TrustSection() {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  interface TrustItem { title: string; body: string; }
  const items = t("trust.items", { returnObjects: true }) as TrustItem[];

  return (
    <section className="lp-section lp-section--center" aria-labelledby="trust-headline">
      <div className="lp-container">
        <div ref={ref} className={`lp-animate ${inView ? "lp-in" : ""}`}>
          <div className="lp-eyebrow">{t("trust.eyebrow")}</div>
          <h2 id="trust-headline" className="lp-h2">{t("trust.headline")}</h2>
        </div>

        <div className="lp-trust__grid" style={{ marginTop: 40 }}>
          {items.map((item, i) => (
            <div
              key={i}
              className={`lp-trust-card lp-animate ${inView ? `lp-in d${i + 1}` : ""}`}
            >
              <div className="lp-trust-card__title">{item.title}</div>
              <div className="lp-trust-card__body">{item.body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Pricing Section ───────────────────────────────────────────────────────────

function PricingSection({ onSignUp }: Pick<Props, "onSignUp">) {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  const plans = ["free", "pro", "business"] as const;

  return (
    <section id="lp-pricing" className="lp-section lp-pricing lp-section--center" aria-labelledby="pricing-headline">
      <div className="lp-container">
        <div ref={ref} className={`lp-animate ${inView ? "lp-in" : ""}`}>
          <div className="lp-eyebrow">{t("pricing.eyebrow")}</div>
          <h2 id="pricing-headline" className="lp-h2">{t("pricing.headline")}</h2>
        </div>

        <div className="lp-pricing__grid">
          {plans.map((plan, i) => {
            const isFeatured = plan === "pro";
            const features = t(`pricing.plans.${plan}.features`, { returnObjects: true }) as string[];
            const price = t(`pricing.plans.${plan}.price`);
            const isCustom = price === "Custom" || price === "مخصص";

            return (
              <div
                key={plan}
                className={`lp-price-card ${isFeatured ? "lp-price-card--featured" : ""} lp-animate ${inView ? `lp-in d${i + 1}` : ""}`}
              >
                {isFeatured && (
                  <div className="lp-price-card__badge">
                    {t("pricing.mostPopular")}
                  </div>
                )}
                <div className="lp-price-card__name">{t(`pricing.plans.${plan}.name`)}</div>
                <div className="lp-price-card__price">
                  <span className="lp-price-card__amount">{price}</span>
                  {!isCustom && (
                    <span className="lp-price-card__period">{t("pricing.perMonth")}</span>
                  )}
                </div>
                <div className="lp-price-card__desc">{t(`pricing.plans.${plan}.description`)}</div>

                <button
                  className="lp-price-card__cta"
                  onClick={onSignUp}
                  aria-label={t(`pricing.plans.${plan}.cta`)}
                >
                  {t(`pricing.plans.${plan}.cta`)}
                </button>

                <hr className="lp-price-card__divider" />

                <ul className="lp-price-card__features" aria-label={`${t(`pricing.plans.${plan}.name`)} features`}>
                  {features.map((f, j) => (
                    <li key={j} className="lp-price-card__feature">
                      <span className="lp-price-card__check" aria-hidden="true">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ── Final CTA Section ─────────────────────────────────────────────────────────

function FinalCtaSection({ onSignIn, onSignUp }: Props) {
  const { t } = useTranslation("landing");
  const { ref, inView } = useInView();

  return (
    <section
      id="lp-final"
      className="lp-section lp-final-cta"
      aria-labelledby="final-headline"
      style={{ background: "var(--bg-surface)" }}
    >
      <div className="lp-final-cta__glow" aria-hidden="true" />
      <div className="lp-container" style={{ position: "relative", zIndex: 1 }}>
        <div
          ref={ref}
          className={`lp-animate ${inView ? "lp-in" : ""}`}
        >
          <h2 id="final-headline" className="lp-final-cta__headline">
            {t("finalCta.headline1")}
            <br />
            <span style={{
              background: "linear-gradient(135deg, var(--accent), var(--teal))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}>
              {t("finalCta.headline2")}
            </span>
          </h2>
          <p className="lp-final-cta__sub">{t("finalCta.sub")}</p>
          <div className="lp-final-cta__actions">
            <button
              className="lp-btn-primary"
              onClick={onSignUp}
              aria-label={t("finalCta.ctaPrimary")}
            >
              {t("finalCta.ctaPrimary")}
              <ArrowIcon />
            </button>
            <button
              className="lp-btn-ghost"
              onClick={onSignIn}
            >
              {t("finalCta.ctaSecondary")}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Footer ────────────────────────────────────────────────────────────────────

function Footer() {
  const { t } = useTranslation("landing");

  return (
    <footer className="lp-footer" role="contentinfo">
      <div className="lp-footer__inner">
        <div className="lp-footer__brand">
          <AxonLogo size={28} />
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, color: "var(--t2)", letterSpacing: "-0.02em" }}>
              Flow
            </div>
            <div className="lp-footer__tagline">{t("footer.tagline")}</div>
          </div>
        </div>
        <div className="lp-footer__copy">
          {t("footer.copyright", { year: new Date().getFullYear() })}
        </div>
      </div>
    </footer>
  );
}

// ── Main LandingPage ──────────────────────────────────────────────────────────

export function LandingPage({ onSignIn, onSignUp }: Props) {
  return (
    <div
      id="lp-scroll-root"
      className="lp-root"
      data-theme="dark"
    >
      <a
        href="#lp-hero"
        style={{
          position: "absolute",
          top: -40,
          insetInlineStart: 0,
          padding: "8px 14px",
          background: "var(--accent)",
          color: "#fff",
          fontSize: 13,
          fontWeight: 600,
          borderRadius: "0 0 var(--r-md) 0",
          zIndex: 9999,
          transition: "top 0.15s",
          textDecoration: "none",
        }}
        onFocus={e => { (e.target as HTMLAnchorElement).style.top = "0"; }}
        onBlur={e => { (e.target as HTMLAnchorElement).style.top = "-40px"; }}
      >
        Skip to main content
      </a>

      <Nav onSignIn={onSignIn} onSignUp={onSignUp} />

      <main id="main-content">
        <HeroSection onSignUp={onSignUp} />
        <CoreValueSection />
        <FeaturesSection />
        <HowItWorksSection />
        <UseCasesSection />
        <BenefitsSection />
        <TrustSection />
        <PricingSection onSignUp={onSignUp} />
        <FinalCtaSection onSignIn={onSignIn} onSignUp={onSignUp} />
      </main>

      <Footer />
    </div>
  );
}
