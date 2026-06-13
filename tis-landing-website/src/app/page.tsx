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
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

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
    description: "Keep teacher information, subject assignments, workload, and planning status in one secure workspace.",
    icon: Users
  },
  {
    title: "Plan workload before the year starts",
    description: "Review coverage, available capacity, uncovered hours, and staffing needs before operations become reactive.",
    icon: ClipboardCheck
  },
  {
    title: "Give leaders a reliable operating view",
    description: "Support owners, principals, coordinators, and HR teams with shared planning visibility.",
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
    description: "For growing schools that need workload, staffing, and operations visibility.",
    highlights: ["Workload planning", "Staffing insights", "Academic operations"]
  },
  {
    name: "Enterprise",
    description: "For multi-branch school groups with advanced governance and support needs.",
    highlights: ["Multi-branch oversight", "Advanced access control", "Onboarding support"]
  }
];

export default function Home() {
  return (
    <main className="overflow-hidden bg-white">
      <Header />
      <Hero />
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

function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-200/80 bg-white/[0.94] backdrop-blur">
      <div className="section-shell flex min-h-20 flex-col gap-4 py-4 md:flex-row md:items-center md:justify-between">
        <div className="flex w-full items-center justify-between gap-3 md:w-auto">
          <a href="#" className="focus-ring flex items-center gap-3 rounded-md">
            <Image
              src="/logo/TIS_Logo_Adjusted.png"
              alt="TIS Platform"
              width={176}
              height={71}
              className="h-11 w-auto object-contain"
              priority
            />
            <span className="hidden text-lg font-bold text-ink sm:inline">TIS Platform</span>
          </a>

          <a
            href={appPortalUrl}
            className="focus-ring inline-flex h-10 items-center justify-center rounded-md border border-ocean px-4 text-sm font-bold text-ocean transition hover:bg-ocean hover:text-white md:hidden"
          >
            Login
          </a>
        </div>

        <nav
          className="flex w-full flex-wrap items-center gap-x-5 gap-y-2 text-sm font-semibold text-slate-600 md:w-auto md:justify-center"
          aria-label="Primary navigation"
        >
          <a className="focus-ring rounded-md transition hover:text-ocean" href="#features">
            Features
          </a>
          <a className="focus-ring rounded-md transition hover:text-ocean" href="#how-it-works">
            How It Works
          </a>
          <a className="focus-ring rounded-md transition hover:text-ocean" href="#pricing">
            Pricing
          </a>
          <a className="focus-ring rounded-md transition hover:text-ocean" href="#request-demo">
            Request Demo
          </a>
        </nav>

        <a
          href={appPortalUrl}
          className="focus-ring hidden h-10 items-center justify-center rounded-md border border-ocean px-4 text-sm font-bold text-ocean transition hover:bg-ocean hover:text-white md:inline-flex"
        >
          Login
        </a>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="border-b border-slate-200 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_68%,#f7faf9_100%)]">
      <div className="section-shell py-20 lg:py-24">
        <div className="mx-auto max-w-4xl text-center">
          <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-ocean shadow-sm">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            Secure SaaS for academic leadership teams
          </div>

          <h1 className="text-4xl font-bold leading-tight tracking-normal text-ink sm:text-5xl lg:text-6xl">
            Smarter Teacher Planning for Modern Schools
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg leading-8 text-slate-600">
            TIS Platform helps schools organize teacher data, assign subjects, plan workloads,
            and identify staffing needs from one secure SaaS platform.
          </p>

          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <a
              href="#request-demo"
              className="focus-ring inline-flex h-12 items-center justify-center rounded-md bg-ocean px-6 text-base font-bold text-white shadow-card transition hover:bg-teal"
            >
              Request a Demo
              <ArrowRight className="ml-2 h-5 w-5" aria-hidden="true" />
            </a>
            <a
              href={appPortalUrl}
              className="focus-ring inline-flex h-12 items-center justify-center rounded-md border border-slate-300 bg-white px-6 text-base font-bold text-ink shadow-sm transition hover:border-ocean hover:text-ocean"
            >
              Go to App Portal
            </a>
          </div>
        </div>

        <div className="mx-auto mt-14 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {trustPoints.map((point) => (
            <div
              key={point}
              className="flex min-h-20 items-center gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
            >
              <CheckCircle2 className="h-5 w-5 shrink-0 text-teal" aria-hidden="true" />
              <p className="text-sm font-bold leading-6 text-ink">{point}</p>
            </div>
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
        <div>
          <SectionLabel icon={Target}>Problem</SectionLabel>
          <h2 className="mt-4 text-3xl font-bold leading-tight text-ink sm:text-4xl">
            Planning gets harder when teacher data lives in too many places.
          </h2>
          <p className="mt-4 text-base leading-7 text-slate-600">
            Academic teams are expected to make staffing decisions quickly, but the information
            they need is often split between spreadsheets, messages, timetables, and last-minute
            reports.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
          <div className="grid gap-2">
            {problems.map((problem) => (
              <div key={problem} className="rounded-md border border-slate-200 bg-white p-5">
                <p className="text-base font-bold leading-7 text-ink">{problem}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function SolutionSection() {
  return (
    <section id="how-it-works" className="border-y border-slate-200 bg-slate-50 py-20">
      <div className="section-shell">
        <div className="max-w-3xl">
          <SectionLabel icon={Sparkles}>Solution</SectionLabel>
          <h2 className="mt-4 text-3xl font-bold leading-tight text-ink sm:text-4xl">
            Move from scattered planning to one operating layer for academic decisions.
          </h2>
          <p className="mt-4 text-base leading-7 text-slate-600">
            TIS Platform gives school leaders a structured workflow for setting up the academic
            year, planning teacher allocation, and monitoring staffing readiness.
          </p>
        </div>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {solutionPoints.map((point) => {
            const Icon = point.icon;

            return (
              <article key={point.title} className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
                <div className="grid h-11 w-11 place-items-center rounded-md bg-skysoft text-ocean">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </div>
                <h3 className="mt-5 text-xl font-bold leading-7 text-ink">{point.title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{point.description}</p>
              </article>
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
          <div>
            <SectionLabel icon={BarChart3}>Product</SectionLabel>
            <h2 className="mt-4 text-3xl font-bold leading-tight text-ink sm:text-4xl">
              A calm command center for teacher workload, staffing, and academic visibility.
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-600">
              The product view supports the story without overwhelming it: leadership teams can
              inspect coverage, staffing pressure, subject demand, and reports from a single
              privacy-safe dashboard.
            </p>

            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              {features.map((feature) => {
                const Icon = feature.icon;

                return (
                  <div key={feature.title} className="flex items-center gap-3 rounded-md border border-slate-200 bg-white p-3">
                    <Icon className="h-4 w-4 shrink-0 text-ocean" aria-hidden="true" />
                    <p className="text-sm font-bold leading-5 text-ink">{feature.title}</p>
                  </div>
                );
              })}
            </div>
          </div>

          <ProductFrame
            image="/screenshots/sanitized/dashboard.png"
            width={1505}
            height={629}
            alt="Privacy-safe TIS dashboard showing executive coverage and staffing planning"
          />
        </div>
      </div>
    </section>
  );
}

function AiAssistantSection() {
  return (
    <section className="bg-ink py-20 text-white">
      <div className="section-shell grid gap-10 lg:grid-cols-[0.86fr_1.14fr] lg:items-center">
        <div>
          <div className="inline-flex items-center gap-2 rounded-md border border-white/15 bg-white/10 px-3 py-2 text-sm font-bold text-white">
            <Bot className="h-4 w-4" aria-hidden="true" />
            Coming Soon
          </div>
          <h2 className="mt-4 text-3xl font-bold leading-tight sm:text-4xl">
            TIS AI Academic Assistant
          </h2>
          <p className="mt-4 text-base leading-7 text-slate-300">
            Future AI capabilities are planned to help academic teams analyze learning quality,
            identify risks, and turn school data into practical improvement actions.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {aiCapabilities.map((capability) => {
            const Icon = capability.icon;

            return (
              <div
                key={capability.title}
                className="rounded-lg border border-white/15 bg-white/[0.06] p-5 shadow-sm"
              >
                <Icon className="h-5 w-5 text-mint" aria-hidden="true" />
                <p className="mt-4 text-base font-bold leading-7 text-white">{capability.title}</p>
              </div>
            );
          })}
          <div className="rounded-lg border border-teal/40 bg-teal/20 p-5">
            <BrainCircuit className="h-5 w-5 text-mint" aria-hidden="true" />
            <p className="mt-4 text-base font-bold leading-7 text-white">
              Built for academic leaders, not generic chat workflows.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function PricingSection() {
  return (
    <section id="pricing" className="bg-white py-20">
      <div className="section-shell">
        <div className="mx-auto max-w-3xl text-center">
          <SectionLabel icon={BarChart3}>Pricing</SectionLabel>
          <h2 className="mt-4 text-3xl font-bold leading-tight text-ink sm:text-4xl">
            Simple plans for schools at different stages.
          </h2>
          <p className="mt-4 text-base leading-7 text-slate-600">
            Subscription and onboarding options are coming soon.
          </p>
        </div>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {plans.map((plan) => (
            <article key={plan.name} className="rounded-lg border border-slate-200 bg-white p-6 shadow-card">
              <h3 className="text-2xl font-bold text-ink">{plan.name}</h3>
              <p className="mt-4 min-h-20 text-sm leading-6 text-slate-600">{plan.description}</p>
              <div className="mt-6 space-y-3">
                {plan.highlights.map((highlight) => (
                  <div key={highlight} className="flex items-start gap-3">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-teal" aria-hidden="true" />
                    <p className="text-sm font-bold leading-6 text-ink">{highlight}</p>
                  </div>
                ))}
              </div>
              <a
                href="#request-demo"
                className="focus-ring mt-8 inline-flex h-11 w-full items-center justify-center rounded-md border border-ocean text-sm font-bold text-ocean transition hover:bg-ocean hover:text-white"
              >
                Request a Demo
              </a>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function DemoSection() {
  return (
    <section id="request-demo" className="bg-[linear-gradient(180deg,#f7fbff_0%,#ffffff_100%)] py-20">
      <div className="section-shell grid gap-10 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
        <div>
          <SectionLabel icon={UserCog}>Demo</SectionLabel>
          <h2 className="mt-4 text-3xl font-bold leading-tight text-ink sm:text-4xl">
            See how TIS Platform can support your school planning workflow.
          </h2>
          <p className="mt-4 text-base leading-7 text-slate-600">
            Share your school details and the TIS team can follow up with demo availability,
            onboarding options, and recommended next steps.
          </p>
        </div>

        <form className="rounded-lg border border-slate-200 bg-white p-6 shadow-soft">
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="School Name" name="school-name" placeholder="Example International School" />
            <Field label="Full Name" name="full-name" placeholder="Your name" />
            <Field label="Email" name="email" type="email" placeholder="name@school.edu" />
            <Field label="Phone" name="phone" type="tel" placeholder="+966 5X XXX XXXX" />
            <Field label="Number of Teachers" name="teachers" type="number" placeholder="150" />
            <div className="sm:col-span-2">
              <label htmlFor="message" className="text-sm font-bold text-ink">
                Message
              </label>
              <textarea
                id="message"
                name="message"
                rows={5}
                placeholder="Tell us about your branches, planning process, or staffing needs."
                className="mt-2 w-full rounded-md border-slate-300 text-sm shadow-sm focus:border-teal focus:ring-teal"
              />
            </div>
          </div>

          <button
            type="button"
            className="focus-ring mt-6 inline-flex h-12 w-full items-center justify-center rounded-md bg-ocean px-6 text-base font-bold text-white shadow-card transition hover:bg-teal sm:w-auto"
          >
            Submit Demo Request
            <ArrowRight className="ml-2 h-5 w-5" aria-hidden="true" />
          </button>
        </form>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-slate-800 bg-ink py-10 text-white">
      <div className="section-shell flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div>
          <Image
            src="/logo/TIS_Logo_Adjusted.png"
            alt="TIS Platform"
            width={190}
            height={77}
            className="h-12 w-auto rounded-md bg-white p-1 object-contain"
          />
          <a className="mt-3 block text-sm text-slate-300 transition hover:text-white" href="mailto:info@tisplatform.com">
            info@tisplatform.com
          </a>
        </div>

        <div className="flex flex-col gap-2 text-sm text-slate-300 md:items-end">
          <a className="transition hover:text-white" href={appPortalUrl}>
            Login: https://app.tisplatform.com
          </a>
          <p>Copyright {new Date().getFullYear()} TIS Platform. All rights reserved.</p>
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
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-soft">
      <div className="flex h-9 items-center gap-2 border-b border-slate-200 px-3">
        <span className="h-2.5 w-2.5 rounded-sm bg-red-300" />
        <span className="h-2.5 w-2.5 rounded-sm bg-amber-300" />
        <span className="h-2.5 w-2.5 rounded-sm bg-teal-400" />
        <span className="ml-3 h-2 w-40 rounded-sm bg-slate-100" />
      </div>
      <div className="pt-3">
        <Image
          src={image}
          alt={alt}
          width={width}
          height={height}
          sizes="(min-width: 1024px) 54vw, 100vw"
          className="h-auto w-full rounded-md border border-slate-100 object-contain"
        />
      </div>
    </div>
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
    <div className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-ocean shadow-sm">
      <Icon className="h-4 w-4" aria-hidden="true" />
      {children}
    </div>
  );
}

function Field({
  label,
  name,
  type = "text",
  placeholder
}: {
  label: string;
  name: string;
  type?: string;
  placeholder: string;
}) {
  return (
    <div>
      <label htmlFor={name} className="text-sm font-bold text-ink">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        placeholder={placeholder}
        className="mt-2 h-11 w-full rounded-md border-slate-300 text-sm shadow-sm focus:border-teal focus:ring-teal"
      />
    </div>
  );
}
