import clsx from "clsx";
import { CircleAlert, CircleCheck, CircleX, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Status, Verdict } from "../api";
import { VERDICT_META } from "../format";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "primary",
  size = "md",
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-4 py-2 text-sm",
        variant === "primary" && "bg-brand-600 text-white shadow-sm hover:bg-brand-700",
        variant === "secondary" &&
          "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
        variant === "danger" && "bg-rose-600 text-white hover:bg-rose-700",
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

const VERDICT_ICON = { authentic: CircleCheck, suspicious: CircleAlert, tampered: CircleX };

export function VerdictBadge({ verdict, size = "md" }: { verdict: Verdict; size?: "sm" | "md" | "lg" }) {
  const m = VERDICT_META[verdict];
  const Icon = VERDICT_ICON[verdict];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full font-semibold ring-1 ring-inset",
        m.tone,
        size === "sm" && "px-2 py-0.5 text-xs",
        size === "md" && "px-2.5 py-1 text-sm",
        size === "lg" && "px-3.5 py-1.5 text-base",
      )}
    >
      <Icon className={size === "lg" ? "size-5" : "size-4"} />
      {m.label}
    </span>
  );
}

export function StatusBadge({ status, verdict }: { status: Status; verdict: Verdict | null }) {
  if (status === "done" && verdict) return <VerdictBadge verdict={verdict} size="sm" />;
  if (status === "failed")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-500/20 ring-inset dark:bg-slate-800 dark:text-slate-300">
        Failed
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 ring-1 ring-brand-600/20 ring-inset dark:bg-brand-500/10 dark:text-brand-300">
      <Loader2 className="size-3 animate-spin" /> {status === "queued" ? "Queued" : "Analysing"}
    </span>
  );
}

/** Semicircular authenticity gauge, 0-100 with the verdict thresholds marked. */
export function ScoreGauge({
  score,
  verdict,
  thresholds = { authentic: 70, tampered: 40 },
}: {
  score: number;
  verdict: Verdict;
  thresholds?: { authentic: number; tampered: number };
}) {
  const r = 70;
  const c = Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const tick = (v: number) => {
    const a = Math.PI * (1 - v / 100);
    return { x1: 90 + (r - 12) * Math.cos(a), y1: 90 - (r - 12) * Math.sin(a), x2: 90 + (r + 12) * Math.cos(a), y2: 90 - (r + 12) * Math.sin(a) };
  };
  return (
    <svg viewBox="0 0 180 104" className="w-48" role="img" aria-label={`Authenticity score ${Math.round(score)} of 100`}>
      <path d="M20 90 A70 70 0 0 1 160 90" fill="none" className="stroke-slate-200 dark:stroke-slate-800" strokeWidth="14" strokeLinecap="round" />
      <path
        d="M20 90 A70 70 0 0 1 160 90"
        fill="none"
        stroke={VERDICT_META[verdict].hex}
        strokeWidth="14"
        strokeLinecap="round"
        strokeDasharray={`${c * pct} ${c}`}
        style={{ transition: "stroke-dasharray 700ms ease" }}
      />
      {[thresholds.tampered, thresholds.authentic].map((t) => (
        <line key={t} {...tick(t)} className="stroke-slate-400 dark:stroke-slate-500" strokeWidth="1.5" />
      ))}
      <text x="90" y="80" textAnchor="middle" className="fill-slate-900 text-[34px] font-bold dark:fill-white">
        {Math.round(score)}
      </text>
      <text x="90" y="99" textAnchor="middle" className="fill-slate-500 text-[10px] font-medium tracking-wider uppercase">
        Authenticity / 100
      </text>
    </svg>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm muted">
      <Loader2 className="size-5 animate-spin" /> {label ?? "Loading..."}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-2xl bg-brand-50 p-3 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300">{icon}</div>
      <h3 className="font-semibold text-slate-900 dark:text-white">{title}</h3>
      {children && <div className="mt-1 max-w-md text-sm muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
      {msg}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#5f50de" />
        <path d="M10 7h8l5 5v13a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z" fill="#fff" opacity=".95" />
        <path d="M18 7v5h5" fill="#d2cafb" />
        <path d="m12.5 18.5 2.6 2.6 5-5.2" fill="none" stroke="#5f50de" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>
        Doc<span className="text-brand-600 dark:text-brand-400">Auth</span>
      </span>
    </span>
  );
}
