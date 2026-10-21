import clsx from "clsx";
import { AlertTriangle, ChevronDown, CircleAlert, Info, ScanSearch } from "lucide-react";
import { useState } from "react";
import type { ModuleResult, Severity } from "../api";
import { bandFor10, VERDICT_META } from "../format";
import { MODULE_COLORS } from "./DocumentViewer";

const SEV_STYLE: Record<Severity, string> = {
  high: "text-rose-600 dark:text-rose-400",
  medium: "text-amber-600 dark:text-amber-400",
  low: "text-sky-600 dark:text-sky-400",
  info: "text-slate-400",
};

const HIDDEN_METRICS = new Set(["fields", "pages", "ghost_curve"]);

function MetricValue({ v }: { v: unknown }) {
  if (typeof v === "number") return <>{Number.isInteger(v) ? v : v.toFixed(3)}</>;
  if (typeof v === "boolean") return <>{v ? "yes" : "no"}</>;
  if (Array.isArray(v)) return <>{v.map((x) => (typeof x === "number" ? x.toFixed(2) : String(x))).join(", ")}</>;
  return <>{String(v)}</>;
}

export default function ModuleCard({
  m,
  contribution,
  focused,
  onFocus,
}: {
  m: ModuleResult;
  contribution?: number;
  focused: boolean;
  onFocus: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ok = m.status === "ok";
  const band = bandFor10(m.score10);
  const fields = (m.metrics.fields ?? null) as Record<string, string> | null;
  const metrics = Object.entries(m.metrics).filter(([k, v]) => !HIDDEN_METRICS.has(k) && (typeof v !== "object" || Array.isArray(v)));
  const hasVisual = m.boxes.length > 0 || m.artifacts.some((a) => a.kind !== "image");

  return (
    <div
      className={clsx(
        "rounded-xl border bg-white transition-shadow dark:bg-slate-900",
        focused ? "border-brand-400 shadow-md ring-2 ring-brand-500/20" : "border-slate-200 dark:border-slate-800",
      )}
    >
      <button className="flex w-full items-start gap-3 p-4 text-left" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="mt-1 size-2.5 shrink-0 rounded-full" style={{ background: MODULE_COLORS[m.key] ?? "#94a3b8" }} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium text-slate-900 dark:text-white">{m.title}</span>
            {!ok && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800">
                {m.status === "skipped" ? "not applicable" : "error"}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm muted">{m.summary}</p>
          {ok && (
            <div className="mt-2.5 flex items-center gap-3">
              <div className="h-1.5 flex-1 rounded-full bg-slate-100 dark:bg-slate-800">
                <div className="h-full rounded-full transition-all" style={{ width: `${m.score10 * 10}%`, background: VERDICT_META[band].hex }} />
              </div>
              <span className="w-14 text-right font-mono text-xs tabular-nums">{m.score10.toFixed(1)}/10</span>
            </div>
          )}
        </div>
        <ChevronDown className={clsx("mt-1 size-4 shrink-0 text-slate-400 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-100 px-4 pt-3 pb-4 text-sm dark:border-slate-800">
          {ok && (
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs muted">
              <span>
                Confidence <b className="text-slate-700 dark:text-slate-300">{Math.round(m.confidence * 100)}%</b>
              </span>
              {contribution !== undefined && (
                <span>
                  Weight in verdict <b className="text-slate-700 dark:text-slate-300">{Math.round(contribution * 100)}%</b>
                </span>
              )}
              <span>{m.duration_ms} ms</span>
            </div>
          )}
          {m.findings.length > 0 && (
            <ul className="space-y-1.5">
              {m.findings.map((f, i) => {
                const Icon = f.severity === "high" ? AlertTriangle : f.severity === "info" ? Info : CircleAlert;
                return (
                  <li key={i} className="flex gap-2">
                    <Icon className={clsx("mt-0.5 size-4 shrink-0", SEV_STYLE[f.severity])} />
                    <span className="text-slate-700 dark:text-slate-300">{f.message}</span>
                  </li>
                );
              })}
            </ul>
          )}
          {fields && Object.keys(fields).length > 0 && (
            <div className="max-h-56 overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {Object.entries(fields).map(([k, v]) => (
                    <tr key={k}>
                      <td className="px-3 py-1.5 align-top font-medium whitespace-nowrap text-slate-600 dark:text-slate-400">{k}</td>
                      <td className="px-3 py-1.5 font-mono break-all text-slate-800 dark:text-slate-200">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {metrics.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
              {metrics.map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="truncate muted">{k.replaceAll("_", " ")}</dt>
                  <dd className="truncate font-mono text-slate-800 dark:text-slate-200">
                    <MetricValue v={v} />
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {hasVisual && (
            <button onClick={onFocus} className="inline-flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">
              <ScanSearch className="size-4" /> {focused ? "Showing on document" : "Show on document"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
