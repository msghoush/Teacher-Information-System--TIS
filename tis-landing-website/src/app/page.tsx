"use client";

import Image from "next/image";
import {
  ArrowRight,
  BarChart3,
  Bot,
  BrainCircuit,
  Building2,
  CalendarDays,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  GraduationCap,
  LineChart,
  LoaderCircle,
  LockKeyhole,
  MessageSquareText,
  Route,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  UserCheck,
  UserCog,
  Users
} from "lucide-react";
import { useEffect, useState } from "react";
import type {
  CSSProperties,
  ElementType,
  FormEvent,
  InputHTMLAttributes,
  PointerEvent as ReactPointerEvent,
  ReactNode
} from "react";
import type { LucideIcon } from "lucide-react";

const appPortalUrl = "https://app.tisplatform.com";

const problems = [
  "Teacher workload is hard to track across branches and academic years.",
  "Subject allocation often depends on manual files and scattered updates.",
  "Staffing gaps are discovered late, when timetables are already under pressure.",
  "Leadership reports are difficult to trust when the source data is fragmented."
];

const trustPoints = [
  "Multi-tenant SaaS architecture",
  "Branch and academic year isolation",
  "Secure school data",
  "Role-based access"
];

const solutionPoints = [
  {
    title: "Centralize teacher planning data",
    description:
      "Keep teacher information, subject assignments, workload, and planning status in one secure workspace.",
    icon: Users
  },
  {
    title: "Plan workload before the year starts",
    description:
      "Review coverage, available capacity, uncovered hours, and staffing needs before operations become reactive.",
    icon: ClipboardCheck
  },
  {
    title: "Give leaders a reliable operating view",
    description:
      "Support owners, principals, coordinators, and HR teams with shared planning visibility.",
    icon: BarChart3
  }
];

const features = [
  { title: "Teacher Information Management", icon: Users },
  { title: "Subject & Workload Planning", icon: ClipboardCheck },
  { title: "Staffing Need Forecasting", icon: TrendingUp },
  { title: "Academic Observations", icon: GraduationCap },
  { title: "Academic Calendar", icon: CalendarDays },
  { title: "Reports & Analytics", icon: BarChart3 },
  { title: "Multi-Branch Management", icon: Building2 },
  { title: "Role-Based Access", icon: LockKeyhole }
];

const aiCapabilities = [
  { title: "Exam analysis", icon: FileSearch },
  { title: "Curriculum alignment review", icon: Route },
  { title: "Academic supervision support", icon: UserCheck },
  { title: "Assessment quality analysis", icon: Target },
  { title: "Action plan generation", icon: ClipboardCheck },
  { title: "Academic coaching recommendations", icon: MessageSquareText },
  { title: "School performance insights", icon: LineChart }
];

const plans = [
  {
    name: "Starter",
    description: "For single schools organizing teacher records and core planning workflows.",
    highlights: ["Teacher profiles", "Subject planning", "Core reports"]
  },
  {
    name: "Professional",
    description:
      "For growing schools that need workload, staffing, and operations visibility.",
    highlights: ["Workload planning", "Staffing insights", "Academic operations"]
  },
  {
    name: "Enterprise",
    description:
      "For multi-branch school groups with advanced governance and support needs.",
    highlights: ["Multi-branch oversight", "Advanced access control", "Onboarding support"]
  }
];

const showcaseImage = {
  image: "/screenshots/2.png",
  width: 1510,
  height: 559,
  alt: "Privacy-safe TIS view showing staffing demand, teacher coverage, and uncovered hours"
};

const aiParticles = [
  { left: 8, top: 12, size: 6, delay: "0s", duration: "15s" },
  { left: 17, top: 68, size: 4, delay: "-2s", duration: "13s" },
  { left: 24, top: 38, size: 5, delay: "-4s", duration: "18s" },
  { left: 31, top: 80, size: 3, delay: "-7s", duration: "12s" },
  { left: 42, top: 15, size: 4, delay: "-5s", duration: "16s" },
  { left: 48, top: 52, size: 6, delay: "-1s", duration: "14s" },
  { left: 57, top: 30, size: 4, delay: "-8s", duration: "17s" },
  { left: 63, top: 74, size: 5, delay: "-3s", duration: "15s" },
  { left: 71, top: 20, size: 3, delay: "-6s", duration: "12s" },
  { left: 77, top: 58, size: 5, delay: "-9s", duration: "19s" },
  { left: 84, top: 36, size: 4, delay: "-2.5s", duration: "14s" },
  { left: 91, top: 70, size: 6, delay: "-4.5s", duration: "18s" }
];

const initialDemoForm = {
  schoolName: "",
  fullName: "",
  email: "",
  phone: "",
  teachers: "",
  message: ""
};

type DemoFormState = typeof initialDemoForm;
type DemoFieldName = keyof DemoFormState;
type RevealDirection = "up" | "left" | "right" | "fade";
type SurfaceTone = "ocean" | "teal" | "ai";
type SubmitState = "idle" | "submitting" | "success" | "error";

const demoFieldIds: Record<DemoFieldName, string> = {
  schoolName: "school-name",
  fullName: "full-name",
  email: "email",
  phone: "phone",
  teachers: "teachers",
  message: "message"
};

export default function Home() {
  const [pageReady, setPageReady] = useState(false);
  const [headerScrolled, setHeaderScrolled] = useState(false);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setPageReady(true);
    });

    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const elements = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    if (!elements.length) {
      return undefined;
    }

    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (media.matches) {
      elements.forEach((element) => element.classList.add("is-visible"));
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }

          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      {
        threshold: 0.16,
        rootMargin: "0px 0px -10% 0px"
      }
    );

    elements.forEach((element) => observer.observe(element));

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let scrollFrame = 0;
    let pointerFrame = 0;

    const updateScroll = () => {
      scrollFrame = 0;
      const scrollY = window.scrollY;
      setHeaderScrolled(scrollY > 14);
      root.style.setProperty(
        "--page-scroll",
        String(Math.min(scrollY / Math.max(window.innerHeight, 1), 1))
      );
      root.style.setProperty("--hero-scroll", `${Math.min(scrollY, 260)}px`);
    };

    const onScroll = () => {
      if (scrollFrame) {
        return;
      }

      scrollFrame = window.requestAnimationFrame(updateScroll);
    };

    const onPointerMove = (event: PointerEvent) => {
      if (reducedMotion) {
        return;
      }

      if (pointerFrame) {
        window.cancelAnimationFrame(pointerFrame);
      }

      pointerFrame = window.requestAnimationFrame(() => {
        const shiftX = (event.clientX / window.innerWidth - 0.5) * 32;
        const shiftY = (event.clientY / window.innerHeight - 0.5) * 24;
        root.style.setProperty("--pointer-shift-x", `${shiftX.toFixed(2)}px`);
        root.style.setProperty("--pointer-shift-y", `${shiftY.toFixed(2)}px`);
      });
    };

    updateScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onPointerMove, { passive: true });

    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onPointerMove);
      if (scrollFrame) {
        window.cancelAnimationFrame(scrollFrame);
      }
      if (pointerFrame) {
        window.cancelAnimationFrame(pointerFrame);
      }
    };
  }, []);

  return (
    <main className={cn("landing-page overflow-hidden bg-white", pageReady && "is-ready")}>
      <Header pageReady={pageReady} scrolled={headerScrolled} />
      <Hero pageReady={pageReady} />
      <ProblemSection />
      <SolutionSection />
      <ProductSection />
      <AiAssistantSection />
      <PricingSection />
      <DemoSection />
      <Footer />
    </main>
  );
}

function Header({
  pageReady,
  scrolled
}: {
  pageReady: boolean;
  scrolled: boolean;
}) {
  return (
    <header
      className={cn(
        "site-header sticky top-0 z-50 border-b border-slate-200/80 bg-white/80 backdrop-blur-xl",
        pageReady && "is-ready",
        scrolled && "is-scrolled"
      )}
    >
      <div className="section-shell flex min-h-20 flex-col gap-4 py-4 md:flex-row md:items-center md:justify-between">
        <div className="flex w-full items-center justify-between gap-3 md:w-auto">
          <a href="#" className="focus-ring inline-flex items-center gap-3 rounded-xl px-1 py-1">
            <Image
              src="/logo/TIS_Logo_Adjusted.png"
              alt="TIS Platform"
              width={176}
              height={71}
              className="h-11 w-auto object-contain transition duration-500 group-hover:scale-[1.02]"
              priority
            />
            <span className="hidden text-lg font-bold tracking-[-0.02em] text-ink sm:inline">
              TIS Platform
            </span>
          </a>

          <a
            href={appPortalUrl}
            className="focus-ring button-secondary inline-flex h-10 items-center justify-center rounded-xl px-4 text-sm font-bold text-ocean md:hidden"
          >
            Login
          </a>
        </div>

        <nav
          className="flex w-full flex-wrap items-center gap-x-5 gap-y-2 text-sm font-semibold text-slate-600 md:w-auto md:justify-center"
          aria-label="Primary navigation"
        >
          <a className="nav-link focus-ring rounded-md" href="#features">
            Features
          </a>
          <a className="nav-link focus-ring rounded-md" href="#how-it-works">
            How It Works
          </a>
          <a className="nav-link focus-ring rounded-md" href="#pricing">
            Pricing
          </a>
          <a className="nav-link focus-ring rounded-md" href="#request-demo">
            Request Demo
          </a>
        </nav>

        <a
          href={appPortalUrl}
          className="focus-ring button-secondary hidden h-10 items-center justify-center rounded-xl px-4 text-sm font-bold text-ocean md:inline-flex"
        >
          Login
        </a>
      </div>
    </header>
  );
}

function Hero({ pageReady }: { pageReady: boolean }) {
  return (
    <section className="hero-section relative isolate overflow-hidden border-b border-slate-200/80">
      <div className="hero-grid" aria-hidden="true" />
      <div className="hero-orb hero-orb-a" aria-hidden="true" />
      <div className="hero-orb hero-orb-b" aria-hidden="true" />
      <div className="hero-orb hero-orb-c" aria-hidden="true" />
      <div className="hero-float hero-float-a" aria-hidden="true" />
      <div className="hero-float hero-float-b" aria-hidden="true" />

      <div className="section-shell relative py-20 lg:py-24">
        <div className="mx-auto max-w-4xl text-center">
          <div
            className={cn(
              "motion-enter glass-chip mx-auto mb-6 inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-bold text-ocean shadow-sm",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "80ms" } as CSSProperties}
          >
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            Secure SaaS for academic leadership teams
          </div>

          <h1
            className={cn(
              "motion-enter text-4xl font-bold leading-tight tracking-[-0.04em] text-ink sm:text-5xl lg:text-6xl",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "160ms" } as CSSProperties}
          >
            Smarter Teacher Planning for Modern Schools
          </h1>

          <p
            className={cn(
              "motion-enter mx-auto mt-6 max-w-2xl text-lg leading-8 text-slate-600",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "240ms" } as CSSProperties}
          >
            TIS Platform helps schools organize teacher data, assign subjects, plan
            workloads, and identify staffing needs from one secure SaaS platform.
          </p>

          <div
            className={cn(
              "motion-enter mt-8 flex flex-col justify-center gap-3 sm:flex-row",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "320ms" } as CSSProperties}
          >
            <a
              href="#request-demo"
              className="focus-ring button-primary inline-flex h-12 items-center justify-center rounded-xl px-6 text-base font-bold text-white shadow-card"
            >
              Request a Demo
              <ArrowRight className="ml-2 h-5 w-5" aria-hidden="true" />
            </a>
            <a
              href={appPortalUrl}
              className="focus-ring button-tertiary inline-flex h-12 items-center justify-center rounded-xl px-6 text-base font-bold text-ink"
            >
              Go to App Portal
            </a>
          </div>
        </div>

        <div className="mx-auto mt-14 grid max-w-5xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {trustPoints.map((point, index) => (
            <Reveal key={point} delay={380 + index * 90}>
              <InteractiveSurface
                className="glass-card flex min-h-24 items-center gap-3 rounded-[1.35rem] border border-white/70 p-4 shadow-[0_18px_46px_rgba(15,23,42,0.08)]"
                tone="teal"
              >
                <CheckCircle2 className="feature-icon h-5 w-5 shrink-0 text-teal" aria-hidden="true" />
                <p className="text-sm font-bold leading-6 text-ink">{point}</p>
              </InteractiveSurface>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function ProblemSection() {
  return (
    <section className="bg-white py-20">
      <div className="section-shell grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
        <Reveal direction="left">
          <div>
            <SectionLabel icon={Target}>Problem</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Planning gets harder when teacher data lives in too many places.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Academic teams are expected to make staffing decisions quickly, but the
              information they need is often split between spreadsheets, messages,
              timetables, and last-minute reports.
            </p>
          </div>
        </Reveal>

        <Reveal direction="right">
          <div className="rounded-[1.75rem] border border-slate-200/80 bg-[linear-gradient(180deg,rgba(247,250,252,0.86)_0%,rgba(255,255,255,0.96)_100%)] p-3 shadow-soft">
            <div className="grid gap-3">
              {problems.map((problem, index) => (
                <InteractiveSurface
                  key={problem}
                  className="rounded-[1.2rem] border border-slate-200/80 bg-white/95 p-5"
                  tone="ocean"
                  style={{ "--reveal-delay": `${120 + index * 60}ms` } as CSSProperties}
                >
                  <p className="text-base font-bold leading-7 text-ink">{problem}</p>
                </InteractiveSurface>
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function SolutionSection() {
  return (
    <section
      id="how-it-works"
      className="border-y border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#f7fafc_100%)] py-20"
    >
      <div className="section-shell">
        <Reveal>
          <div className="max-w-3xl">
            <SectionLabel icon={Sparkles}>Solution</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Move from scattered planning to one operating layer for academic decisions.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              TIS Platform gives school leaders a structured workflow for setting up the
              academic year, planning teacher allocation, and monitoring staffing readiness.
            </p>
          </div>
        </Reveal>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {solutionPoints.map((point, index) => {
            const Icon = point.icon;
            const directions: RevealDirection[] = ["left", "up", "right"];

            return (
              <Reveal
                key={point.title}
                direction={directions[index] ?? "up"}
                delay={80 + index * 80}
              >
                <InteractiveSurface
                  as="article"
                  className="feature-card rounded-[1.75rem] border border-slate-200/75 bg-white/95 p-6 shadow-[0_20px_52px_rgba(15,23,42,0.08)]"
                  tone="ocean"
                >
                  <div className="icon-badge grid h-12 w-12 place-items-center rounded-2xl bg-skysoft text-ocean">
                    <Icon className="feature-icon h-5 w-5" aria-hidden="true" />
                  </div>
                  <h3 className="mt-5 text-xl font-bold leading-7 tracking-[-0.02em] text-ink">
                    {point.title}
                  </h3>
                  <p className="mt-3 text-sm leading-6 text-slate-600">
                    {point.description}
                  </p>
                </InteractiveSurface>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function ProductSection() {
  return (
    <section id="features" className="bg-white py-20">
      <div className="section-shell">
        <div className="grid gap-12 lg:grid-cols-[0.82fr_1.18fr] lg:items-center">
          <Reveal direction="left">
            <div>
              <SectionLabel icon={BarChart3}>Product</SectionLabel>
              <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
                A calm command center for teacher workload, staffing, and academic visibility.
              </h2>
              <p className="mt-4 text-base leading-7 text-slate-600">
                The product view supports the story without overwhelming it: leadership
                teams can inspect coverage, staffing pressure, subject demand, and reports
                from a single privacy-safe dashboard.
              </p>

              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {features.map((feature, index) => {
                  const Icon = feature.icon;
                  const direction = index % 2 === 0 ? "left" : "right";

                  return (
                    <Reveal key={feature.title} direction={direction} delay={80 + index * 40}>
                      <InteractiveSurface
                        className="feature-list-card flex items-center gap-3 rounded-[1.1rem] border border-slate-200/80 bg-white/90 p-3"
                        tone="teal"
                      >
                        <div className="grid h-9 w-9 place-items-center rounded-xl bg-skysoft text-ocean">
                          <Icon className="feature-icon h-4 w-4 shrink-0" aria-hidden="true" />
                        </div>
                        <p className="text-sm font-bold leading-5 text-ink">{feature.title}</p>
                      </InteractiveSurface>
                    </Reveal>
                  );
                })}
              </div>
            </div>
          </Reveal>

          <Reveal direction="right" delay={120}>
            <ProductFrame
              image={showcaseImage.image}
              width={showcaseImage.width}
              height={showcaseImage.height}
              alt={showcaseImage.alt}
            />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function AiAssistantSection() {
  return (
    <section
      id="ai-assistant"
      className="ai-section relative isolate overflow-hidden py-24 text-white"
    >
      <div className="ai-grid-overlay" aria-hidden="true" />
      <div className="ai-glow ai-glow-a" aria-hidden="true" />
      <div className="ai-glow ai-glow-b" aria-hidden="true" />
      <div className="ai-beam ai-beam-a" aria-hidden="true" />
      <div className="ai-beam ai-beam-b" aria-hidden="true" />
      <div className="ai-particles" aria-hidden="true">
        {aiParticles.map((particle, index) => (
          <span
            key={`${particle.left}-${particle.top}-${index}`}
            className="ai-particle"
            style={
              {
                "--particle-left": `${particle.left}%`,
                "--particle-top": `${particle.top}%`,
                "--particle-size": `${particle.size}px`,
                "--particle-delay": particle.delay,
                "--particle-duration": particle.duration
              } as CSSProperties
            }
          />
        ))}
      </div>

      <div className="section-shell relative grid gap-10 lg:grid-cols-[0.86fr_1.14fr] lg:items-center">
        <Reveal direction="left">
          <div>
            <div className="ai-chip inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-bold text-white">
              <Bot className="h-4 w-4" aria-hidden="true" />
              Coming Soon
            </div>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.04em] sm:text-4xl lg:text-[2.85rem]">
              TIS AI Academic Assistant
            </h2>
            <p className="mt-4 max-w-xl text-base leading-7 text-slate-200">
              Future AI capabilities are planned to help academic teams analyze learning
              quality, identify risks, and turn school data into practical improvement
              actions.
            </p>
            <div className="ai-highlight mt-8 max-w-lg rounded-[1.6rem] border border-white/12 bg-white/[0.06] p-5 backdrop-blur-xl">
              <p className="text-sm font-semibold uppercase tracking-[0.22em] text-cyan-200/80">
                Premium roadmap emphasis
              </p>
              <p className="mt-3 text-base leading-7 text-slate-100">
                Designed to become the intelligence layer for academic leaders who need
                faster insight, clearer priorities, and stronger school follow-through.
              </p>
            </div>
          </div>
        </Reveal>

        <Reveal direction="right">
          <div className="ai-panel rounded-[2rem] border border-white/12 bg-white/[0.04] p-3 shadow-[0_32px_120px_rgba(2,6,23,0.45)] backdrop-blur-xl sm:p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {aiCapabilities.map((capability, index) => {
                const Icon = capability.icon;

                return (
                  <InteractiveSurface
                    key={capability.title}
                    className="ai-card rounded-[1.35rem] border border-white/12 bg-white/[0.06] p-5"
                    tone="ai"
                    style={{ "--reveal-delay": `${index * 55}ms` } as CSSProperties}
                  >
                    <div className="ai-icon-wrap grid h-12 w-12 place-items-center rounded-2xl bg-white/10 text-mint">
                      <Icon className="feature-icon h-5 w-5" aria-hidden="true" />
                    </div>
                    <p className="mt-4 text-base font-bold leading-7 text-white">
                      {capability.title}
                    </p>
                  </InteractiveSurface>
                );
              })}

              <InteractiveSurface
                className="ai-card ai-card-highlight rounded-[1.35rem] border border-teal/40 bg-[linear-gradient(135deg,rgba(22,138,136,0.24),rgba(11,28,45,0.74))] p-5 sm:col-span-2"
                tone="ai"
              >
                <div className="ai-icon-wrap grid h-12 w-12 place-items-center rounded-2xl bg-white/12 text-mint">
                  <BrainCircuit className="feature-icon h-5 w-5" aria-hidden="true" />
                </div>
                <p className="mt-4 text-base font-bold leading-7 text-white">
                  Built for academic leaders, not generic chat workflows.
                </p>
              </InteractiveSurface>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function PricingSection() {
  return (
    <section id="pricing" className="bg-white py-20">
      <div className="section-shell">
        <Reveal>
          <div className="mx-auto max-w-3xl text-center">
            <SectionLabel icon={BarChart3}>Pricing</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Simple plans for schools at different stages.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Subscription and onboarding options are coming soon.
            </p>
          </div>
        </Reveal>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {plans.map((plan, index) => {
            const featured = plan.name === "Professional";
            const direction: RevealDirection =
              index === 0 ? "left" : index === 1 ? "up" : "right";

            return (
              <Reveal key={plan.name} direction={direction} delay={80 + index * 80}>
                <InteractiveSurface
                  as="article"
                  className={cn(
                    "pricing-card rounded-[1.85rem] border border-slate-200/80 bg-white/95 p-6 shadow-soft",
                    featured && "is-featured lg:-translate-y-3"
                  )}
                  tone={featured ? "ai" : "ocean"}
                >
                  <div className="relative z-[1]">
                    <h3 className="text-2xl font-bold tracking-[-0.03em] text-ink">
                      {plan.name}
                    </h3>
                    <p className="mt-4 min-h-20 text-sm leading-6 text-slate-600">
                      {plan.description}
                    </p>
                    <div className="mt-6 space-y-3">
                      {plan.highlights.map((highlight) => (
                        <div key={highlight} className="flex items-start gap-3">
                          <CheckCircle2
                            className="mt-0.5 h-5 w-5 shrink-0 text-teal"
                            aria-hidden="true"
                          />
                          <p className="text-sm font-bold leading-6 text-ink">{highlight}</p>
                        </div>
                      ))}
                    </div>
                    <a
                      href="#request-demo"
                      className={cn(
                        "focus-ring pricing-button mt-8 inline-flex h-11 w-full items-center justify-center rounded-xl border text-sm font-bold transition",
                        featured
                          ? "border-transparent bg-ocean text-white shadow-card hover:bg-teal"
                          : "border-ocean text-ocean hover:bg-ocean hover:text-white"
                      )}
                    >
                      Request a Demo
                    </a>
                  </div>
                </InteractiveSurface>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function DemoSection() {
  const [formData, setFormData] = useState<DemoFormState>(initialDemoForm);
  const [touched, setTouched] = useState<Partial<Record<DemoFieldName, boolean>>>({});
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [submitMessage, setSubmitMessage] = useState("");
  const errors = getDemoErrors(formData);
  const isSubmitting = submitState === "submitting";
  const isSuccess = submitState === "success";

  const handleFieldChange = (field: DemoFieldName, value: string) => {
    setFormData((current) => ({
      ...current,
      [field]: value
    }));

    if (submitState !== "idle") {
      setSubmitState("idle");
      setSubmitMessage("");
    }
  };

  const handleFieldBlur = (field: DemoFieldName) => {
    setTouched((current) => ({
      ...current,
      [field]: true
    }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setTouched({
      schoolName: true,
      fullName: true,
      email: true,
      phone: true,
      teachers: true,
      message: true
    });

    if (Object.keys(errors).length > 0) {
      setSubmitState("error");
      setSubmitMessage("Please review the highlighted fields.");
      return;
    }

    setSubmitState("submitting");
    setSubmitMessage("");

    await new Promise((resolve) => window.setTimeout(resolve, 900));

    setSubmitState("success");
    setSubmitMessage("Looks good.");
  };

  return (
    <section
      id="request-demo"
      className="bg-[linear-gradient(180deg,#f7fbff_0%,#ffffff_100%)] py-20"
    >
      <div className="section-shell grid gap-10 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
        <Reveal direction="left">
          <div>
            <SectionLabel icon={UserCog}>Demo</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              See how TIS Platform can support your school planning workflow.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Share your school details and the TIS team can follow up with demo
              availability, onboarding options, and recommended next steps.
            </p>
          </div>
        </Reveal>

        <Reveal direction="right" delay={120}>
          <form
            className={cn(
              "demo-form-shell rounded-[1.9rem] border border-slate-200/80 bg-white/90 p-6 shadow-soft backdrop-blur-xl",
              isSuccess && "is-success",
              submitState === "error" && "is-error"
            )}
            noValidate
            onSubmit={handleSubmit}
          >
            <div className="grid gap-5 sm:grid-cols-2">
              <Field
                label="School Name"
                name="schoolName"
                placeholder="Example International School"
                value={formData.schoolName}
                onChange={handleFieldChange}
                onBlur={handleFieldBlur}
                error={touched.schoolName ? errors.schoolName : undefined}
                autoComplete="organization"
              />
              <Field
                label="Full Name"
                name="fullName"
                placeholder="Your name"
                value={formData.fullName}
                onChange={handleFieldChange}
                onBlur={handleFieldBlur}
                error={touched.fullName ? errors.fullName : undefined}
                autoComplete="name"
              />
              <Field
                label="Email"
                name="email"
                type="email"
                placeholder="name@school.edu"
                value={formData.email}
                onChange={handleFieldChange}
                onBlur={handleFieldBlur}
                error={touched.email ? errors.email : undefined}
                autoComplete="email"
              />
              <Field
                label="Phone"
                name="phone"
                type="tel"
                placeholder="+966 5X XXX XXXX"
                value={formData.phone}
                onChange={handleFieldChange}
                onBlur={handleFieldBlur}
                error={touched.phone ? errors.phone : undefined}
                autoComplete="tel"
              />
              <Field
                label="Number of Teachers"
                name="teachers"
                type="number"
                placeholder="150"
                value={formData.teachers}
                onChange={handleFieldChange}
                onBlur={handleFieldBlur}
                error={touched.teachers ? errors.teachers : undefined}
                inputMode="numeric"
              />
              <div className="sm:col-span-2">
                <label htmlFor={demoFieldIds.message} className="text-sm font-bold text-ink">
                  Message
                </label>
                <textarea
                  id={demoFieldIds.message}
                  name="message"
                  rows={5}
                  placeholder="Tell us about your branches, planning process, or staffing needs."
                  value={formData.message}
                  onChange={(event) => handleFieldChange("message", event.target.value)}
                  onBlur={() => handleFieldBlur("message")}
                  aria-invalid={Boolean(touched.message && errors.message)}
                  aria-describedby={errors.message ? "message-error" : undefined}
                  className={cn(
                    "demo-textarea mt-2 w-full rounded-2xl border border-slate-300 bg-white/90 text-sm shadow-sm transition duration-300",
                    touched.message && errors.message
                      ? "border-rose-300 focus:border-rose-400 focus:ring-rose-200"
                      : "focus:border-teal focus:ring-teal/25"
                  )}
                />
                <FieldError id="message-error" message={touched.message ? errors.message : undefined} />
              </div>
            </div>

            <div
              className={cn(
                "form-status mt-5 min-h-6 text-sm font-semibold transition",
                submitState === "error" && "text-rose-500",
                isSuccess && "text-teal"
              )}
              role="status"
              aria-live="polite"
            >
              {submitMessage}
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                "focus-ring demo-submit-button mt-4 inline-flex h-12 w-full items-center justify-center rounded-xl px-6 text-base font-bold text-white shadow-card transition sm:w-auto",
                isSuccess ? "is-success" : "bg-ocean hover:bg-teal",
                isSubmitting && "cursor-wait"
              )}
            >
              {isSubmitting ? (
                <LoaderCircle className="mr-2 h-5 w-5 animate-spin" aria-hidden="true" />
              ) : isSuccess ? (
                <CheckCircle2 className="mr-2 h-5 w-5" aria-hidden="true" />
              ) : null}
              Submit Demo Request
              {!isSubmitting && !isSuccess ? (
                <ArrowRight className="ml-2 h-5 w-5" aria-hidden="true" />
              ) : null}
            </button>
          </form>
        </Reveal>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="footer-shell relative overflow-hidden border-t border-slate-800/80 bg-ink py-12 text-white">
      <div className="footer-glow footer-glow-a" aria-hidden="true" />
      <div className="footer-glow footer-glow-b" aria-hidden="true" />

      <div className="section-shell relative flex flex-col gap-8 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="inline-flex rounded-[1.45rem] border border-white/12 bg-white/[0.06] p-2 shadow-[0_20px_50px_rgba(2,6,23,0.35)]">
            <Image
              src="/logo/TIS_Logo_Adjusted.png"
              alt="TIS Platform"
              width={190}
              height={77}
              className="h-12 w-auto rounded-xl bg-white p-1 object-contain"
            />
          </div>
          <a
            className="footer-link mt-4 inline-flex rounded-full border border-white/12 bg-white/[0.05] px-4 py-2 text-sm text-slate-200"
            href="mailto:info@tisplatform.com"
          >
            info@tisplatform.com
          </a>
        </div>

        <div className="flex flex-col gap-3 text-sm text-slate-300 md:items-end">
          <a className="footer-link" href={appPortalUrl}>
            Login: https://app.tisplatform.com
          </a>
          <p className="text-slate-400">
            Copyright {new Date().getFullYear()} TIS Platform. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}

function ProductFrame({
  image,
  width,
  height,
  alt
}: {
  image: string;
  width: number;
  height: number;
  alt: string;
}) {
  return (
    <InteractiveSurface
      className="showcase-frame group relative overflow-hidden rounded-[2rem] border border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.82),rgba(247,250,252,0.92))] p-3 shadow-[0_26px_75px_rgba(15,23,42,0.14)]"
      tone="ocean"
    >
      <div className="absolute inset-x-0 top-0 h-28 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.7),transparent_70%)]" />
      <div className="glass-bar relative flex h-10 items-center gap-2 rounded-2xl border border-white/70 px-4">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-teal-400" />
        <span className="ml-3 h-2 w-40 rounded-full bg-white/60" />
      </div>
      <div className="relative overflow-hidden rounded-[1.5rem] pt-3">
        <div className="showcase-sheen" aria-hidden="true" />
        <Image
          src={image}
          alt={alt}
          width={width}
          height={height}
          sizes="(min-width: 1024px) 54vw, 100vw"
          className="showcase-image h-auto w-full rounded-[1.3rem] border border-slate-100 object-contain"
        />
      </div>
    </InteractiveSurface>
  );
}

function SectionLabel({
  icon: Icon,
  children
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <div className="glass-chip inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-bold text-ocean shadow-sm">
      <Icon className="h-4 w-4" aria-hidden="true" />
      {children}
    </div>
  );
}

function Field({
  label,
  name,
  value,
  type = "text",
  placeholder,
  onChange,
  onBlur,
  error,
  autoComplete,
  inputMode
}: {
  label: string;
  name: DemoFieldName;
  value: string;
  type?: string;
  placeholder: string;
  onChange: (field: DemoFieldName, value: string) => void;
  onBlur: (field: DemoFieldName) => void;
  error?: string;
  autoComplete?: string;
  inputMode?: InputHTMLAttributes<HTMLInputElement>["inputMode"];
}) {
  const fieldId = demoFieldIds[name];
  const errorId = `${fieldId}-error`;

  return (
    <div>
      <label htmlFor={fieldId} className="text-sm font-bold text-ink">
        {label}
      </label>
      <input
        id={fieldId}
        name={name}
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(name, event.target.value)}
        onBlur={() => onBlur(name)}
        autoComplete={autoComplete}
        inputMode={inputMode}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        className={cn(
          "demo-input mt-2 h-11 w-full rounded-2xl border border-slate-300 bg-white/90 text-sm shadow-sm transition duration-300",
          error
            ? "border-rose-300 focus:border-rose-400 focus:ring-rose-200"
            : "focus:border-teal focus:ring-teal/25"
        )}
      />
      <FieldError id={errorId} message={error} />
    </div>
  );
}

function FieldError({ id, message }: { id: string; message?: string }) {
  return (
    <div id={id} className="mt-2 min-h-5 text-xs font-medium text-rose-500">
      {message}
    </div>
  );
}

function Reveal({
  as,
  children,
  className,
  delay = 0,
  direction = "up"
}: {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  delay?: number;
  direction?: RevealDirection;
}) {
  const Tag = as ?? "div";

  return (
    <Tag
      data-reveal={direction}
      className={className}
      style={{ "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}

function InteractiveSurface({
  as,
  children,
  className,
  style,
  tone = "ocean"
}: {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  tone?: SurfaceTone;
}) {
  const Tag = as ?? "div";

  const handlePointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) {
      return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const rotateY = ((x / rect.width) - 0.5) * 6;
    const rotateX = (0.5 - y / rect.height) * 6;

    event.currentTarget.style.setProperty("--pointer-x", `${x}px`);
    event.currentTarget.style.setProperty("--pointer-y", `${y}px`);
    event.currentTarget.style.setProperty("--rotate-x", `${rotateX.toFixed(2)}deg`);
    event.currentTarget.style.setProperty("--rotate-y", `${rotateY.toFixed(2)}deg`);
  };

  const handlePointerLeave = (event: ReactPointerEvent<HTMLElement>) => {
    event.currentTarget.style.setProperty("--rotate-x", "0deg");
    event.currentTarget.style.setProperty("--rotate-y", "0deg");
    event.currentTarget.style.setProperty("--pointer-x", "50%");
    event.currentTarget.style.setProperty("--pointer-y", "50%");
  };

  return (
    <Tag
      className={cn("interactive-surface", `surface-${tone}`, className)}
      style={style}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
    >
      {children}
    </Tag>
  );
}

function getDemoErrors(formData: DemoFormState) {
  const errors: Partial<Record<DemoFieldName, string>> = {};

  if (!formData.schoolName.trim()) {
    errors.schoolName = "School name is required.";
  }

  if (!formData.fullName.trim()) {
    errors.fullName = "Full name is required.";
  }

  if (!formData.email.trim()) {
    errors.email = "Email is required.";
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email.trim())) {
    errors.email = "Enter a valid email address.";
  }

  if (formData.phone.trim() && formData.phone.trim().length < 8) {
    errors.phone = "Phone number looks too short.";
  }

  if (formData.teachers.trim()) {
    const teacherCount = Number(formData.teachers);
    if (!Number.isFinite(teacherCount) || teacherCount <= 0) {
      errors.teachers = "Enter a valid teacher count.";
    }
  }

  if (formData.message.trim().length > 1000) {
    errors.message = "Keep the message under 1000 characters.";
  }

  return errors;
}

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}
