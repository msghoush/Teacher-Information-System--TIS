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
  Database,
  Eye,
  FileSpreadsheet,
  FileSearch,
  GraduationCap,
  LineChart,
  LoaderCircle,
  LockKeyhole,
  Menu,
  MessageSquareText,
  Network,
  Route,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  UserCheck,
  UserCog,
  Users,
  X
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
  {
    title: "Too Many Spreadsheets",
    description:
      "Academic work is scattered across different files, formats, and personal tracking systems.",
    icon: FileSpreadsheet
  },
  {
    title: "Inconsistent Data",
    description:
      "Each person or branch may structure information differently, making comparison and reporting difficult.",
    icon: Database
  },
  {
    title: "Heavy Staff Workload",
    description:
      "Teachers, supervisors, and coordinators carry the burden of repeatedly entering and updating data.",
    icon: Users
  },
  {
    title: "Delayed Visibility",
    description:
      "Leaders often discover staffing gaps, missing coverage, or academic issues after the problem has grown.",
    icon: Eye
  },
  {
    title: "Disconnected Decisions",
    description:
      "Calendars, observations, staffing, reports, and academic planning are managed separately.",
    icon: Network
  }
];

const trustPoints = [
  "Multi-tenant SaaS architecture",
  "Branch and academic year isolation",
  "Secure school data",
  "Role-based access"
];

const heroStory = [
  {
    label: "Scattered Files",
    description: "Separate sheets, calendars, forms, and follow-up lists.",
    icon: FileSpreadsheet
  },
  {
    label: "Connected Operations",
    description: "One structured academic workflow inside TIS.",
    icon: Network
  },
  {
    label: "Clear Decisions",
    description: "Visible gaps, priorities, progress, and required action.",
    icon: BarChart3
  }
];

const solutionPoints = [
  {
    title: "One Source of Academic Truth",
    description:
      "Bring teacher data, workloads, observations, calendars, and staffing information into one connected system.",
    icon: Database
  },
  {
    title: "Clearer Leadership Visibility",
    description:
      "Help principals, academic leaders, and supervisors see what is happening, what is missing, and what requires action.",
    icon: Eye
  },
  {
    title: "Standardized Academic Processes",
    description:
      "Replace personal spreadsheet formats with a consistent way to manage academic operations across branches.",
    icon: ClipboardCheck
  },
  {
    title: "Smarter Staffing Decisions",
    description:
      "Identify teaching load issues, uncovered hours, subject gaps, and staffing needs before they become larger problems.",
    icon: TrendingUp
  },
  {
    title: "Connected School Communication",
    description:
      "Support coordination between leadership, supervisors, teachers, and branches through shared workflows.",
    icon: MessageSquareText
  },
  {
    title: "Ready for Future Intelligence",
    description:
      "Build the structured data foundation needed for advanced AI-powered features as TIS continues to grow.",
    icon: Sparkles
  }
];

const features = [
  {
    title: "Academic Workforce Planning",
    description:
      "Plan teacher assignments, analyze weekly loads, identify uncovered hours, and understand staffing needs.",
    icon: Users
  },
  {
    title: "Academic Calendars & Shared Coordination",
    description:
      "Coordinate events, timelines, school priorities, and branch-level planning through shared calendars.",
    icon: CalendarDays
  },
  {
    title: "Observation & Supervision Workflows",
    description:
      "Manage structured observations, supervisor feedback, shared records, and signing workflows.",
    icon: ClipboardCheck
  },
  {
    title: "Multi-Branch Organization Management",
    description:
      "Support school groups, campuses, branches, users, roles, and tenant-isolated structures.",
    icon: Building2
  },
  {
    title: "Dashboards & Decision Visibility",
    description:
      "Give leaders a clearer view of coverage, staffing gaps, utilization, and follow-up needs.",
    icon: BarChart3
  },
  {
    title: "Future AI-Powered Intelligence",
    description:
      "Prepare for planned subscription-based AI capabilities grounded in verified academic data.",
    icon: BrainCircuit
  }
];

const workforceCapabilities = [
  { title: "Teacher Load Visibility", icon: BarChart3 },
  { title: "Subject Coverage Analysis", icon: Target },
  { title: "Staffing Gap Detection", icon: TrendingUp },
  { title: "Qualification-Based Planning", icon: GraduationCap },
  { title: "New Teacher Requirement Insights", icon: Users },
  { title: "Multi-Branch Workforce Clarity", icon: Building2 }
];

const observationCapabilities = [
  { title: "Structured Observation Records", icon: ClipboardCheck },
  { title: "Shared Teacher-Supervisor Visibility", icon: UserCheck },
  { title: "Signing and Approval Workflow", icon: ShieldCheck },
  { title: "Supervision Follow-Up", icon: MessageSquareText },
  { title: "Planned AI-Suggested Improvement Plans", icon: Sparkles },
  { title: "Leadership Oversight", icon: Eye }
];

const calendarCapabilities = [
  { title: "Academic-Year-Based Calendar", icon: CalendarDays },
  { title: "Shared School Coordination", icon: Users },
  { title: "International Event Awareness", icon: Route },
  { title: "Planned AI-Suggested Activities", icon: Sparkles },
  { title: "Curriculum-Integrated Events", icon: GraduationCap },
  { title: "SDG Awareness Planning", icon: Target }
];

const branchCapabilities = [
  { title: "Organization and Branch Structure", icon: Building2 },
  { title: "Role-Based User Management", icon: UserCog },
  { title: "Tenant-Isolated Environment", icon: LockKeyhole },
  { title: "Branch Progress Intelligence", icon: LineChart },
  { title: "Branch Comparison Indicators", icon: BarChart3 },
  { title: "Scalable SaaS Structure", icon: Network }
];

const dashboardCapabilities = [
  { title: "Planning Completion Indicators", icon: ClipboardCheck },
  { title: "Assessment Progress Visibility", icon: FileSearch },
  { title: "Observation & Supervision Insights", icon: Eye },
  { title: "Academic Calendar Integration", icon: CalendarDays },
  { title: "Branch and Organization Dashboards", icon: Building2 },
  { title: "Risk and Delay Alerts", icon: Target }
];

const aiCapabilities = [
  { title: "Curriculum-to-Classroom AI Support", icon: Route },
  { title: "AI-Assisted Assessment Generation", icon: FileSearch },
  { title: "AI-Supported Observation Follow-Up", icon: UserCheck },
  { title: "AI-Powered Calendar Planning", icon: CalendarDays },
  { title: "Academic Analytics and Recommendations", icon: LineChart },
  { title: "Subscription-Based AI Growth", icon: BrainCircuit }
];

const curriculumJourney = [
  {
    title: "Approved Curriculum Data",
    description: "Uploaded standards, learning outcomes, objectives, and school requirements.",
    icon: GraduationCap
  },
  {
    title: "Guided Planning",
    description: "Future support for annual, weekly, and lesson planning through approved templates.",
    icon: ClipboardCheck
  },
  {
    title: "Teacher Review & Approval",
    description: "Teachers adjust and submit; academic leaders review and approve official planning data.",
    icon: UserCheck
  },
  {
    title: "Assessment & Insight",
    description: "Planned assessment generation, answer keys, coverage analytics, and recommendations.",
    icon: BarChart3
  }
];

const plans = [
  {
    name: "Core",
    description:
      "For schools that need structured teacher data, academic operations, basic planning visibility, and essential workflows.",
    highlights: ["Teacher and subject operations", "Essential planning visibility", "Core academic workflows"]
  },
  {
    name: "Professional",
    description:
      "For schools that need stronger dashboards, shared calendars, observation workflows, and staffing visibility.",
    highlights: ["Advanced dashboards", "Shared calendars and observations", "Staffing and team coordination"]
  },
  {
    name: "Enterprise AI",
    description:
      "For school groups that need multi-branch visibility, customization, and progressively introduced AI intelligence.",
    highlights: ["Multi-branch intelligence", "Advanced customization", "Planned AI-assisted capabilities"]
  }
];

const productImages = {
  workforce: {
    image: "/screenshots/10.png",
    width: 1586,
    height: 562,
    alt: "Privacy-safe TIS planning table showing sections, subjects, assignments, and allocated hours"
  },
  observations: {
    image: "/screenshots/13.png",
    width: 1601,
    height: 370,
    alt: "Privacy-safe TIS observation workflow showing records, scores, signatures, and status"
  },
  calendar: {
    image: "/screenshots/12.png",
    width: 1587,
    height: 626,
    alt: "TIS academic calendar showing shared school events and monthly coordination"
  },
  dashboard: {
    image: "/screenshots/7.png",
    width: 1550,
    height: 660,
    alt: "TIS reports dashboard showing coverage, staffing plans, uncovered hours, and leadership indicators"
  }
};

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
      <MainPositioningSection />
      <Hero pageReady={pageReady} />
      <ProblemSection />
      <SolutionSection />
      <CoreCapabilitiesSection />
      <WorkforcePlanningSection />
      <ObservationSection />
      <CalendarSection />
      <MultiBranchSection />
      <DashboardSection />
      <FutureAiSection />
      <CurriculumToClassroomSection />
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
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header
      className={cn(
        "site-header sticky top-0 z-50 border-b border-slate-200/80 bg-white/80 backdrop-blur-xl",
        pageReady && "is-ready",
        scrolled && "is-scrolled"
      )}
    >
      <div className="section-shell flex min-h-20 flex-col py-4 md:flex-row md:items-center md:justify-between">
        <div className="flex w-full items-center justify-between gap-3 md:w-auto">
          <a href="#" className="focus-ring relative block h-12 w-44 overflow-hidden rounded-xl sm:w-48">
            <Image
              src="/branding/tis/logos/tis-full-color-horizontal.png"
              alt="TIS Teacher Information System"
              width={1563}
              height={1563}
              priority
              className="absolute left-1/2 top-1/2 h-44 w-44 max-w-none -translate-x-1/2 -translate-y-1/2 object-contain sm:h-48 sm:w-48"
            />
          </a>

          <div className="flex items-center gap-2 md:hidden">
            <a
              href={appPortalUrl}
              className="focus-ring button-secondary inline-flex h-10 items-center justify-center rounded-xl px-4 text-sm font-bold text-ocean"
            >
              Login
            </a>
            <button
              type="button"
              className="focus-ring inline-flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-ink shadow-sm"
              aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
              aria-expanded={menuOpen}
              aria-controls="mobile-navigation"
              onClick={() => setMenuOpen((isOpen) => !isOpen)}
            >
              {menuOpen ? <X className="h-5 w-5" aria-hidden="true" /> : <Menu className="h-5 w-5" aria-hidden="true" />}
            </button>
          </div>
        </div>

        <nav
          id="mobile-navigation"
          className={cn(
            "mt-4 w-full border-t border-slate-200 pt-3 text-sm font-semibold text-slate-600 md:mt-0 md:flex md:w-auto md:items-center md:justify-center md:gap-x-5 md:border-0 md:pt-0",
            menuOpen ? "grid grid-cols-2 gap-2" : "hidden"
          )}
          aria-label="Primary navigation"
        >
          <a className="nav-link focus-ring rounded-md px-2 py-2 md:px-0 md:py-0" href="#capabilities" onClick={() => setMenuOpen(false)}>
            Features
          </a>
          <a className="nav-link focus-ring rounded-md px-2 py-2 md:px-0 md:py-0" href="#solution" onClick={() => setMenuOpen(false)}>
            How It Works
          </a>
          <a className="nav-link focus-ring rounded-md px-2 py-2 md:px-0 md:py-0" href="#future-ai" onClick={() => setMenuOpen(false)}>
            Future AI
          </a>
          <a className="nav-link focus-ring rounded-md px-2 py-2 md:px-0 md:py-0" href="#pricing" onClick={() => setMenuOpen(false)}>
            Pricing
          </a>
          <a className="nav-link focus-ring rounded-md px-2 py-2 md:px-0 md:py-0" href="#request-demo" onClick={() => setMenuOpen(false)}>
            Book a Demo
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

function MainPositioningSection() {
  return (
    <section className="positioning-strip border-b border-white/10 bg-[#102532] text-white">
      <div className="section-shell flex items-center justify-center gap-3 py-2.5 text-center">
        <span className="h-2 w-2 shrink-0 rounded-full bg-teal-300 shadow-[0_0_16px_rgba(94,234,212,0.65)]" aria-hidden="true" />
        <p className="text-xs leading-5 text-slate-200 sm:text-sm">
          <strong className="font-bold text-white">Developing SaaS academic operations platform.</strong>{" "}
          <span className="hidden md:inline">
            Connecting leadership, teachers, branches, calendars, observations, staffing, and decisions.
          </span>
        </p>
      </div>
    </section>
  );
}

function Hero({ pageReady }: { pageReady: boolean }) {
  return (
    <section className="hero-section relative isolate overflow-hidden border-b border-slate-200/80">
      <div className="hero-grid" aria-hidden="true" />
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
            Built for Schools Moving Beyond Spreadsheets
          </div>

          <h1
            className={cn(
              "motion-enter text-4xl font-bold leading-tight tracking-[-0.04em] text-ink sm:text-5xl lg:text-6xl",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "160ms" } as CSSProperties}
          >
            When Academic Decisions Are Scattered, Schools Lose Time, Clarity, and Control.
          </h1>

          <p
            className={cn(
              "motion-enter mx-auto mt-6 max-w-2xl text-lg leading-8 text-slate-600",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "240ms" } as CSSProperties}
          >
            TIS brings teacher data, workloads, staffing gaps, academic calendars,
            observations, and leadership decisions into one connected SaaS platform,
            helping schools see what is happening, what is missing, and what needs action.
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
              Request Early Access
              <ArrowRight className="ml-2 h-5 w-5" aria-hidden="true" />
            </a>
            <a
              href="#solution"
              className="focus-ring button-tertiary inline-flex h-12 items-center justify-center rounded-xl px-6 text-base font-bold text-ink"
            >
              See How TIS Works
            </a>
          </div>

          <p
            className={cn(
              "motion-enter mx-auto mt-5 max-w-2xl text-sm leading-6 text-slate-500",
              pageReady && "is-visible"
            )}
            style={{ "--enter-delay": "380ms" } as CSSProperties}
          >
            A developing academic operations platform with advanced AI capabilities
            planned through subscription-based growth.
          </p>
        </div>

        <div
          className={cn(
            "motion-enter hero-story-flow mx-auto mt-10 max-w-5xl",
            pageReady && "is-visible"
          )}
          style={{ "--enter-delay": "440ms" } as CSSProperties}
        >
          <div className="grid gap-3 md:grid-cols-3">
            {heroStory.map((step, index) => {
              const Icon = step.icon;

              return (
                <div key={step.label} className="hero-story-step relative flex items-start gap-4 p-4">
                  <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white text-ocean shadow-sm">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-bold text-ink">{step.label}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{step.description}</p>
                  </div>
                  {index < heroStory.length - 1 ? (
                    <ArrowRight className="hero-story-arrow absolute -right-3 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 text-teal md:block" aria-hidden="true" />
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mx-auto mt-5 flex max-w-5xl flex-wrap justify-center gap-x-5 gap-y-2">
          {trustPoints.map((point, index) => (
            <Reveal key={point} delay={380 + index * 90}>
              <div className="flex items-center gap-2 px-2 py-1 text-xs font-bold text-slate-600 sm:text-sm">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-teal" aria-hidden="true" />
                <span>{point}</span>
              </div>
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
            <SectionLabel icon={Target}>The Problem</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Schools Are Not Short of Data. They Are Drowning in Disconnected Files.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Teacher loads, subject coverage, observations, calendars, reports, staffing
              needs, and follow-up tasks are often managed in separate files, created by
              different people in different formats.
            </p>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Staff spend more time updating files than understanding the data. Leaders
              receive information late or inconsistently, and multi-branch organizations
              face an even larger burden when every branch works differently.
            </p>
          </div>
        </Reveal>

        <Reveal direction="right">
          <div className="rounded-[1.75rem] border border-slate-200/80 bg-[linear-gradient(180deg,rgba(247,250,252,0.86)_0%,rgba(255,255,255,0.96)_100%)] p-3 shadow-soft">
            <div className="grid gap-3">
              {problems.map((problem, index) => {
                const Icon = problem.icon;

                return (
                <InteractiveSurface
                  key={problem.title}
                  className="rounded-[1.2rem] border border-slate-200/80 bg-white/95 p-5"
                  tone="ocean"
                  style={{ "--reveal-delay": `${120 + index * 60}ms` } as CSSProperties}
                >
                  <div className="flex items-start gap-4">
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-skysoft text-ocean">
                      <Icon className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div>
                      <p className="text-base font-bold leading-7 text-ink">{problem.title}</p>
                      <p className="mt-1 text-sm leading-6 text-slate-600">{problem.description}</p>
                    </div>
                  </div>
                </InteractiveSurface>
                );
              })}
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
      id="solution"
      className="border-y border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#f7fafc_100%)] py-20"
    >
      <div className="section-shell">
        <Reveal>
          <div className="max-w-3xl">
            <SectionLabel icon={Sparkles}>Solution</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              One Connected Platform to Bring Academic Operations Back Under Control.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              TIS brings teacher data, workloads, subject coverage, academic calendars,
              observations, supervision follow-up, branch structures, and leadership
              decisions into one structured academic ecosystem.
            </p>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Schools can reduce manual confusion, standardize academic processes, improve
              visibility, and make decisions with greater confidence while every branch
              operates inside a secure, tenant-isolated environment.
            </p>
          </div>
        </Reveal>

        <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {solutionPoints.map((point, index) => {
            const Icon = point.icon;
            const directions: RevealDirection[] = ["left", "up", "right"];

            return (
              <Reveal
                key={point.title}
                direction={directions[index % directions.length] ?? "up"}
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

function CoreCapabilitiesSection() {
  return (
    <section id="capabilities" className="bg-white py-20">
      <div className="section-shell">
        <Reveal>
          <div className="mx-auto max-w-3xl text-center">
            <SectionLabel icon={Network}>Core Platform Capabilities</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Everything Your Academic Operation Needs, Connected in One Platform.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              TIS brings teacher planning, branch management, observations, calendars,
              dashboards, and a foundation for future AI-powered intelligence into one
              structured SaaS environment.
            </p>
          </div>
        </Reveal>

        <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {features.map((feature, index) => {
            const Icon = feature.icon;
            const directions: RevealDirection[] = ["left", "up", "right"];

            return (
              <Reveal
                key={feature.title}
                direction={directions[index % directions.length]}
                delay={60 + index * 55}
              >
                <InteractiveSurface
                  as="article"
                  className="feature-card h-full rounded-[1.35rem] border border-slate-200/80 bg-white p-5 shadow-soft"
                  tone={index === features.length - 1 ? "ai" : "ocean"}
                >
                  <div className="icon-badge grid h-12 w-12 place-items-center rounded-2xl bg-skysoft text-ocean">
                    <Icon className="feature-icon h-5 w-5" aria-hidden="true" />
                  </div>
                  <h3 className="mt-4 text-lg font-bold leading-7 text-ink">{feature.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-slate-600">{feature.description}</p>
                </InteractiveSurface>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function WorkforcePlanningSection() {
  return (
    <ModuleBand
      id="workforce-planning"
      label="Teacher Workforce Planning Engine"
      icon={Users}
      title="Know Exactly Who Is Teaching What, and Where Support Is Needed."
      paragraphs={[
        "One of the strongest current capabilities of TIS is its ability to help schools understand their teaching workforce with clarity. Instead of calculating teacher loads, subject coverage, and staffing needs across separate files, TIS brings the information into one structured planning engine.",
        "School leaders can track qualifications, majors, subject specialties, weekly teaching loads, assigned subjects, uncovered hours, and additional staffing requirements so gaps are identified earlier and decisions are based on clear data rather than assumptions."
      ]}
      capabilities={workforceCapabilities}
      image={productImages.workforce}
      className="border-y border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#f7fafc_100%)]"
    />
  );
}

function ObservationSection() {
  return (
    <ModuleBand
      id="observations"
      label="Observation & Supervision Workflows"
      icon={ClipboardCheck}
      title="Turn Teacher Observation into a Clear, Shared, and Accountable Process."
      paragraphs={[
        "TIS is designed to move teacher observation away from scattered forms, disconnected files, and informal follow-up. Observation records, supervisor feedback, teacher responses, signatures, and approval steps can become part of one structured workflow.",
        "As the platform grows, planned AI-assisted supervision may help supervisors suggest improvement plans based on observation notes, evaluation results, performance evidence, and school-approved criteria."
      ]}
      capabilities={observationCapabilities}
      image={productImages.observations}
      imageFirst
      className="bg-white"
      futureNote="AI-assisted improvement plans are planned capabilities and are not presented as currently released."
    />
  );
}

function CalendarSection() {
  return (
    <ModuleBand
      id="academic-calendar"
      label="Academic Calendars & Shared Coordination"
      icon={CalendarDays}
      title="Turn the Academic Calendar into a Shared Planning Engine."
      paragraphs={[
        "Academic leaders, supervisors, teachers, and branches can work from a shared calendar connected to the selected academic year, coordinating priorities, events, observations, deadlines, and academic follow-up.",
        "Future calendar capabilities are planned to support international events, curriculum-integrated activities, SDG awareness, and AI-assisted activity suggestions based on grade levels and school needs."
      ]}
      capabilities={calendarCapabilities}
      image={productImages.calendar}
      className="border-y border-slate-200/80 bg-[linear-gradient(180deg,#f7fafc_0%,#ffffff_100%)]"
      futureNote="Future activity suggestions will be progressively introduced as the platform develops."
    />
  );
}

function MultiBranchSection() {
  return (
    <section id="multi-branch" className="bg-white py-20">
      <div className="section-shell grid gap-12 lg:grid-cols-[0.88fr_1.12fr] lg:items-center">
        <Reveal direction="left">
          <div>
            <SectionLabel icon={Building2}>Multi-Branch Organization Management</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Built for Schools That Operate Across Branches, Campuses, and Teams.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              TIS provides a scalable environment where organizations, branches, users,
              roles, branding, academic structures, and workflows can be organized with
              greater clarity inside a tenant-isolated SaaS platform.
            </p>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Management-level users can compare progress, identify delayed tasks, and see
              where follow-up is needed across planning, exams, observations, calendars,
              reporting, and academic operations.
            </p>

            <CapabilityGrid capabilities={branchCapabilities} />
          </div>
        </Reveal>

        <Reveal direction="right" delay={120}>
          <OrganizationMap />
        </Reveal>
      </div>
    </section>
  );
}

function DashboardSection() {
  return (
    <ModuleBand
      id="dashboards"
      label="Dashboards & Decision Visibility"
      icon={BarChart3}
      title="See Academic Progress, Risks, and Priorities Before They Become Problems."
      paragraphs={[
        "TIS dashboards are designed to give leaders more than static reports. They connect academic operations so leadership can understand what is complete, what is delayed, what needs follow-up, and where intervention may be required.",
        "Branch-level dashboards can show the academic health of one campus, while organization-level views can compare branches, highlight delays, identify performance gaps, and support faster evidence-based decisions."
      ]}
      capabilities={dashboardCapabilities}
      image={productImages.dashboard}
      imageFirst
      className="border-y border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#f7fafc_100%)]"
      supportingLine="From reports to real-time academic visibility."
    />
  );
}

function FutureAiSection() {
  return (
    <section
      id="future-ai"
      className="ai-section relative isolate overflow-hidden py-24 text-white"
    >
      <div className="ai-grid-overlay" aria-hidden="true" />
      <div className="ai-beam ai-beam-a" aria-hidden="true" />
      <div className="ai-beam ai-beam-b" aria-hidden="true" />

      <div className="section-shell relative grid gap-10 lg:grid-cols-[0.86fr_1.14fr] lg:items-center">
        <Reveal direction="left">
          <div>
            <div className="ai-chip inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-bold text-white">
              <Bot className="h-4 w-4" aria-hidden="true" />
              Future AI-Powered Intelligence
            </div>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.04em] sm:text-4xl lg:text-[2.85rem]">
              AI That Works Inside the Academic Workflow, Not Outside It.
            </h2>
            <p className="mt-4 max-w-xl text-base leading-7 text-slate-200">
              TIS is being developed with a future intelligence layer that can work inside
              calendars, observations, curriculum planning, assessments, dashboards, branch
              progress, and leadership decision-making using reviewed and approved data.
            </p>
            <div className="ai-highlight mt-8 max-w-lg rounded-[1.6rem] border border-white/12 bg-white/[0.06] p-5 backdrop-blur-xl">
              <p className="text-sm font-semibold uppercase tracking-[0.22em] text-cyan-200/80">
                Planned subscription-based growth
              </p>
              <p className="mt-3 text-base leading-7 text-slate-100">
                Future AI capabilities will be introduced progressively through subscription
                plans, allowing schools to grow into more advanced intelligence as the
                platform and their needs develop.
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
                  Planned to work from verified academic data, approved school criteria, and
                  connected TIS workflows.
                </p>
              </InteractiveSurface>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function CurriculumToClassroomSection() {
  return (
    <section id="curriculum-to-classroom" className="bg-white py-20">
      <div className="section-shell">
        <Reveal>
          <div className="mx-auto max-w-3xl text-center">
            <SectionLabel icon={Route}>From Curriculum to Classroom</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Support Teachers Without Adding Another Burden.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Future AI-assisted planning tools are being designed to guide teachers through
              annual plans, weekly plans, lesson plans, and curriculum tracking using approved
              templates, curriculum data, learning outcomes, standards, and school requirements.
            </p>
            <p className="mt-4 text-base leading-7 text-slate-600">
              Teachers can review, adjust, complete, and submit their work while academic
              leaders review and approve it, turning planning documents into reliable official
              data inside TIS.
            </p>
          </div>
        </Reveal>

        <div className="curriculum-journey relative mt-12 grid gap-5 lg:grid-cols-4">
          {curriculumJourney.map((step, index) => {
            const Icon = step.icon;

            return (
              <Reveal key={step.title} delay={80 + index * 90}>
                <InteractiveSurface
                  className="journey-card h-full rounded-[1.5rem] border border-slate-200/80 bg-white p-6 shadow-soft"
                  tone="teal"
                >
                  <div className="flex items-center justify-between">
                    <div className="grid h-11 w-11 place-items-center rounded-2xl bg-mint text-teal">
                      <Icon className="feature-icon h-5 w-5" aria-hidden="true" />
                    </div>
                    <span className="text-sm font-bold text-slate-300">0{index + 1}</span>
                  </div>
                  <h3 className="mt-5 text-lg font-bold leading-7 text-ink">{step.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-slate-600">{step.description}</p>
                </InteractiveSurface>
              </Reveal>
            );
          })}
        </div>

        <Reveal delay={220}>
          <div className="mx-auto mt-8 max-w-3xl rounded-[1.3rem] border border-teal/20 bg-mint/55 px-5 py-4 text-center text-sm font-semibold leading-6 text-ocean">
            These capabilities are planned, are being developed progressively, and may be
            introduced through subscription-based plans.
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
            <SectionLabel icon={BarChart3}>Subscription Plans</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Choose the Level of Academic Intelligence Your School Needs.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              TIS is being developed as a subscription-based SaaS platform, allowing
              schools to start with essential academic operations and grow into advanced
              dashboards, multi-branch workflows, and future AI-powered intelligence.
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
                      {featured ? "Request Early Access" : "Request Pricing"}
                    </a>
                  </div>
                </InteractiveSurface>
              </Reveal>
            );
          })}
        </div>

        <Reveal delay={220}>
          <p className="mx-auto mt-8 max-w-3xl text-center text-sm leading-6 text-slate-500">
            AI-powered capabilities will be introduced progressively and may vary according
            to subscription level, school needs, and platform development stage.
          </p>
        </Reveal>
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
    setSubmitMessage(
      "Form validation complete. Online delivery is being connected; please email info@tisplatform.com to complete your request."
    );
  };

  return (
    <section
      id="request-demo"
      className="bg-[linear-gradient(180deg,#f7fbff_0%,#ffffff_100%)] py-20"
    >
      <div className="section-shell grid gap-10 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
        <Reveal direction="left">
          <div>
            <SectionLabel icon={UserCog}>Start Your TIS Journey</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              Ready to Bring Clarity, Control, and Intelligence to Your Academic Operations?
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              TIS is being built for schools that want to move beyond scattered files,
              disconnected workflows, and delayed decisions. Start exploring how one
              connected academic operations platform can support your leaders, supervisors,
              teachers, branches, and future AI-powered growth.
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row lg:flex-col xl:flex-row">
              <a
                href="#demo-form"
                className="focus-ring button-primary inline-flex h-11 items-center justify-center rounded-xl px-5 text-sm font-bold text-white"
              >
                Book a Demo
              </a>
              <a
                href="mailto:info@tisplatform.com?subject=TIS%20Early%20Access%20Request"
                className="focus-ring button-secondary inline-flex h-11 items-center justify-center rounded-xl px-5 text-sm font-bold text-ocean"
              >
                Request Early Access
              </a>
            </div>
            <p className="mt-6 text-sm leading-6 text-slate-500">
              TIS is currently in active development, with selected features and advanced
              AI capabilities planned for progressive release through subscription-based plans.
            </p>
          </div>
        </Reveal>

        <Reveal direction="right" delay={120}>
          <form
            id="demo-form"
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
              Book a Demo
              {!isSubmitting && !isSuccess ? (
                <ArrowRight className="ml-2 h-5 w-5" aria-hidden="true" />
              ) : null}
            </button>
            <p className="mt-4 max-w-xl text-xs leading-5 text-slate-500">
              This form does not send automatically yet. To complete a demo request now,
              email{" "}
              <a
                className="font-bold text-ocean underline decoration-ocean/30 underline-offset-2"
                href="mailto:info@tisplatform.com?subject=TIS%20Demo%20Request"
              >
                info@tisplatform.com
              </a>
              .
            </p>
          </form>
        </Reveal>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="footer-shell relative overflow-hidden border-t border-slate-800/80 bg-ink py-12 text-white">
      <div className="section-shell relative flex flex-col gap-8 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="relative h-12 w-48 overflow-hidden" aria-label="TIS Teacher Information System">
            <Image
              src="/branding/tis/logos/tis-white-light-orange-horizontal.png"
              alt=""
              width={1563}
              height={1563}
              className="absolute left-1/2 top-1/2 h-48 w-48 max-w-none -translate-x-1/2 -translate-y-1/2 object-contain"
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

function ModuleBand({
  id,
  label,
  icon: Icon,
  title,
  paragraphs,
  capabilities,
  image,
  imageFirst = false,
  className,
  futureNote,
  supportingLine
}: {
  id: string;
  label: string;
  icon: LucideIcon;
  title: string;
  paragraphs: string[];
  capabilities: Array<{ title: string; icon: LucideIcon }>;
  image: { image: string; width: number; height: number; alt: string };
  imageFirst?: boolean;
  className?: string;
  futureNote?: string;
  supportingLine?: string;
}) {
  return (
    <section id={id} className={cn("module-band py-20", className)}>
      <div className="section-shell grid gap-12 lg:grid-cols-[0.92fr_1.08fr] lg:items-center">
        <Reveal direction={imageFirst ? "right" : "left"} className={imageFirst ? "lg:order-2" : undefined}>
          <div>
            <SectionLabel icon={Icon}>{label}</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight tracking-[-0.03em] text-ink sm:text-4xl">
              {title}
            </h2>
            {paragraphs.map((paragraph, index) => (
              <p
                key={paragraph}
                className={cn(
                  "mt-4 leading-7",
                  index === 0 ? "text-base font-medium text-slate-700" : "text-sm text-slate-600"
                )}
              >
                {paragraph}
              </p>
            ))}
            {supportingLine ? (
              <p className="mt-5 text-sm font-bold uppercase tracking-[0.14em] text-teal">
                {supportingLine}
              </p>
            ) : null}
            <CapabilityGrid capabilities={capabilities} />
            {futureNote ? (
              <p className="mt-5 rounded-xl border border-teal/20 bg-mint/55 px-4 py-3 text-sm font-semibold leading-6 text-ocean">
                {futureNote}
              </p>
            ) : null}
          </div>
        </Reveal>

        <Reveal
          direction={imageFirst ? "left" : "right"}
          delay={120}
          className={imageFirst ? "lg:order-1" : undefined}
        >
          <ProductFrame
            image={image.image}
            width={image.width}
            height={image.height}
            alt={image.alt}
          />
        </Reveal>
      </div>
    </section>
  );
}

function CapabilityGrid({
  capabilities
}: {
  capabilities: Array<{ title: string; icon: LucideIcon }>;
}) {
  return (
    <div className="mt-8 grid gap-3 sm:grid-cols-2">
      {capabilities.map((capability, index) => {
        const Icon = capability.icon;

        return (
          <InteractiveSurface
            key={capability.title}
            className="feature-list-card flex min-h-14 items-center gap-3 rounded-[1rem] border border-slate-200/80 bg-white/90 p-3"
            tone={index % 2 === 0 ? "ocean" : "teal"}
          >
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-skysoft text-ocean">
              <Icon className="feature-icon h-4 w-4" aria-hidden="true" />
            </div>
            <p className="text-sm font-bold leading-5 text-ink">{capability.title}</p>
          </InteractiveSurface>
        );
      })}
    </div>
  );
}

function OrganizationMap() {
  const branches = [
    { name: "Branch A", progress: "92%", tone: "bg-teal" },
    { name: "Branch B", progress: "76%", tone: "bg-ocean" },
    { name: "Branch C", progress: "64%", tone: "bg-amber-400" }
  ];

  return (
    <div className="organization-map rounded-[2rem] border border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] p-5 shadow-soft sm:p-7">
      <div className="mx-auto max-w-sm rounded-[1.2rem] border border-ocean/20 bg-ocean px-5 py-4 text-center text-white shadow-card">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-cyan-100">Organization View</p>
        <p className="mt-1 text-lg font-bold">TIS School Group</p>
      </div>

      <div className="mx-auto h-8 w-px bg-slate-300" aria-hidden="true" />

      <div className="grid gap-4 sm:grid-cols-3">
        {branches.map((branch, index) => (
          <InteractiveSurface
            key={branch.name}
            className="rounded-[1.2rem] border border-slate-200/80 bg-white p-4"
            tone={index === 2 ? "teal" : "ocean"}
          >
            <div className="flex items-center justify-between gap-3">
              <Building2 className="h-5 w-5 text-ocean" aria-hidden="true" />
              <span className="text-xs font-bold text-slate-500">{branch.progress}</span>
            </div>
            <p className="mt-4 text-sm font-bold text-ink">{branch.name}</p>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
              <div
                className={cn("branch-progress-fill h-full rounded-full", branch.tone)}
                style={{ width: branch.progress }}
              />
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">Planning, calendar, observations, reports</p>
          </InteractiveSurface>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {["Tenant isolated", "Role based", "Comparable indicators"].map((item) => (
          <span key={item} className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600">
            {item}
          </span>
        ))}
      </div>
    </div>
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
      className="showcase-frame group relative overflow-hidden rounded-[1.5rem] border border-slate-200 bg-white p-2 shadow-[0_26px_75px_rgba(15,23,42,0.16)]"
      tone="ocean"
    >
      <div className="glass-bar relative flex h-10 items-center gap-2 rounded-xl border border-slate-200/80 px-4">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-teal-400" />
        <span className="ml-3 h-2 w-24 rounded-full bg-slate-100 sm:w-40" />
        <span className="ml-auto inline-flex items-center gap-2 text-[0.68rem] font-bold uppercase tracking-[0.1em] text-slate-500">
          <span className="h-2 w-2 rounded-full bg-teal" aria-hidden="true" />
          Product preview
        </span>
      </div>
      <div className="relative overflow-hidden rounded-xl bg-white pt-2">
        <div className="showcase-sheen" aria-hidden="true" />
        <Image
          src={image}
          alt={alt}
          width={width}
          height={height}
          sizes="(min-width: 1024px) 54vw, 100vw"
          className="showcase-image h-auto w-full rounded-lg border border-slate-200/80 bg-white object-contain"
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
