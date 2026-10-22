import {
  ArrowRight,
  Binary,
  Copy,
  Cpu,
  FileSearch,
  Fingerprint,
  Grid3x3,
  Layers,
  ScanLine,
  Waves,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { ThemeSwitch } from "../components/AppShell";
import { Logo, VerdictBadge } from "../components/ui";

const MODULES = [
  { icon: FileSearch, title: "Metadata analysis", text: "Editing software, capture vs. modification time, ISO, thumbnails; PDF revisions, whiteout boxes and mixed fonts." },
  { icon: Layers, title: "Error level analysis", text: "Re-compression error compared between regions of similar texture, so text-heavy pages don't false-alarm." },
  { icon: Waves, title: "Noise consistency", text: "Pasted or digitally typed content lacks the scanner/sensor noise of the rest of the page." },
  { icon: Binary, title: "JPEG compression traces", text: "JPEG ghosts, misaligned 8x8 block grids and double-compression history." },
  { icon: Copy, title: "Copy-move detection", text: "Cloned stamps, signatures or digits, verified by noise correlation to ignore repeated print." },
  { icon: Grid3x3, title: "Template matching (SSIM)", text: "Aligns the document to a verified original and boxes added or missing content." },
  { icon: Cpu, title: "SRM-CNN classifier", text: "A CNN whose first layer starts from the 30 SRM high-pass filters decides real vs. fake." },
  { icon: Fingerprint, title: "Pixel manipulation analyzer", text: "Two-stream RGB + DCT network that draws a heatmap of the edited pixels." },
];

function HeroMock() {
  return (
    <div className="relative mx-auto w-full max-w-md">
      <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-br from-brand-500/30 via-brand-300/20 to-transparent blur-2xl" />
      <div className="card overflow-hidden p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-slate-900 dark:text-white">income_certificate.jpg</div>
            <div className="text-xs muted">8 forensic modules - 4.2 s</div>
          </div>
          <VerdictBadge verdict="tampered" size="sm" />
        </div>
        <div className="relative mb-4 aspect-[4/3] overflow-hidden rounded-xl border border-slate-200 bg-[#f6f3ea] p-4 dark:border-slate-700">
          <div className="mx-auto mb-3 h-3 w-1/2 rounded bg-slate-400/60" />
          <div className="mx-auto mb-5 h-2 w-1/3 rounded bg-slate-300" />
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="mb-2.5 flex gap-3">
              <div className="h-2 w-1/4 rounded bg-slate-300" />
              <div className="h-2 rounded bg-slate-400/70" style={{ width: `${30 + ((i * 17) % 25)}%` }} />
            </div>
          ))}
          <div className="absolute top-[58%] left-[38%] h-7 w-[34%] rounded-sm bg-rose-500/25 ring-2 ring-rose-500" />
          <div className="absolute top-[52%] left-[72%] rounded bg-rose-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            edited pixels
          </div>
          <div className="absolute right-5 bottom-4 size-12 rounded-full border-2 border-indigo-800/40" />
        </div>
        <div className="space-y-2">
          {[
            ["Pixel manipulation", 1.2, "bg-rose-500"],
            ["JPEG traces", 3.1, "bg-rose-500"],
            ["Template (SSIM)", 6.4, "bg-amber-500"],
            ["Metadata", 9.0, "bg-emerald-500"],
          ].map(([label, v, c]) => (
            <div key={label as string} className="flex items-center gap-3 text-xs">
              <span className="w-32 shrink-0 muted">{label}</span>
              <div className="h-1.5 flex-1 rounded-full bg-slate-100 dark:bg-slate-800">
                <div className={`h-full rounded-full ${c}`} style={{ width: `${(v as number) * 10}%` }} />
              </div>
              <span className="w-8 text-right font-mono tabular-nums">{(v as number).toFixed(1)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const { user } = useAuth();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  const t = health.data?.thresholds ?? { authentic: 70, tampered: 40 };
  const hi = Math.round(t.authentic);
  const lo = Math.round(t.tampered);
  const cta = user ? { to: "/app", label: "Open dashboard" } : { to: "/register", label: "Create free account" };
  return (
    <div className="min-h-dvh overflow-x-clip">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Logo className="text-lg text-slate-900 dark:text-white" />
        <nav className="flex items-center gap-2 sm:gap-4">
          <a href="#modules" className="hidden text-sm muted hover:text-slate-900 sm:inline dark:hover:text-white">
            Modules
          </a>
          <a href="#how" className="hidden text-sm muted hover:text-slate-900 sm:inline dark:hover:text-white">
            How it works
          </a>
          <ThemeSwitch />
          {user ? null : (
            <Link to="/login" className="rounded-lg px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800">
              Sign in
            </Link>
          )}
        </nav>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-10 pb-20 sm:px-6 lg:grid-cols-2 lg:pt-16">
        <div>
          <span className="mb-4 inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 ring-1 ring-brand-600/15 dark:bg-brand-500/10 dark:text-brand-300">
            <ScanLine className="size-3.5" /> Multi-feature forgery detection
          </span>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl dark:text-white">
            Catch forged documents <span className="text-brand-600 dark:text-brand-400">before you trust them.</span>
          </h1>
          <p className="mt-5 max-w-xl text-lg muted">
            DocAuth runs eight independent forensic tests on certificates, IDs and scans, from camera
            metadata to a deep network that pinpoints edited pixels, and explains every verdict with
            evidence you can show.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to={cta.to} className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700">
              {cta.label} <ArrowRight className="size-4" />
            </Link>
            <a href="#how" className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800">
              See how it works
            </a>
          </div>
          <p className="mt-4 text-xs muted">Accepts JPEG, PNG, TIFF, BMP, WebP and multi-page PDF.</p>
        </div>
        <HeroMock />
      </section>

      <section id="modules" className="border-y border-slate-200 bg-white py-20 dark:border-slate-800 dark:bg-slate-900/50">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">Eight lenses on every document</h2>
          <p className="mt-2 max-w-2xl muted">
            Each module looks for a different trace of editing. Their evidence is weighted by how reliable the
            test is on that file and fused into one authenticity score.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {MODULES.map(({ icon: Icon, title, text }) => (
              <div key={title} className="rounded-2xl border border-slate-200 p-5 dark:border-slate-800">
                <Icon className="mb-3 size-6 text-brand-600 dark:text-brand-400" />
                <h3 className="font-semibold text-slate-900 dark:text-white">{title}</h3>
                <p className="mt-1.5 text-sm muted">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="how" className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <h2 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">How it works</h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {[
            ["Upload", "Drop an image or PDF. Optionally pick the verified template for that document type, or let DocAuth recognise it."],
            ["Analyse", "All modules run in the background, at the file's native resolution so compression traces survive."],
            ["Decide", "Get a green/amber/red verdict, heatmaps and boxes over the suspicious areas, and a PDF report to file."],
          ].map(([t, d], i) => (
            <div key={t} className="card p-6">
              <div className="mb-4 flex size-9 items-center justify-center rounded-full bg-brand-600 text-sm font-bold text-white">{i + 1}</div>
              <h3 className="font-semibold text-slate-900 dark:text-white">{t}</h3>
              <p className="mt-1.5 text-sm muted">{d}</p>
            </div>
          ))}
        </div>
        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          {(
            [
              ["authentic", `Score ${hi}-100`, "No significant manipulation found."],
              ["suspicious", `Score ${lo}-${hi}`, "Some indicators; review the highlighted areas."],
              ["tampered", `Score 0-${lo}`, "Strong evidence of manipulation."],
            ] as const
          ).map(([v, range, text]) => (
            <div key={v} className="rounded-2xl border border-slate-200 p-5 dark:border-slate-800">
              <VerdictBadge verdict={v} />
              <div className="mt-3 font-mono text-sm text-slate-900 dark:text-white">{range}</div>
              <p className="mt-1 text-sm muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-slate-200 py-8 text-center text-xs muted dark:border-slate-800">
        DocAuth v2 - originally built for Smart India Hackathon 2023. Automated forensic indicators, not a legal determination.
      </footer>
    </div>
  );
}
