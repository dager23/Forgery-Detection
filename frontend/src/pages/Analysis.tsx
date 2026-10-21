import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileDown, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, fileUrl, type Analysis } from "../api";
import DocumentViewer from "../components/DocumentViewer";
import ModuleCard from "../components/ModuleCard";
import { Button, ErrorNote, ScoreGauge, Spinner, VerdictBadge } from "../components/ui";
import { formatBytes, formatDate, VERDICT_META } from "../format";

const STEPS = ["Reading file", "Metadata & compression", "Noise & cloning", "Template matching", "Deep networks", "Fusing evidence"];

function Pending({ a }: { a: Analysis }) {
  const elapsed = (Date.now() - new Date(a.created_at).getTime()) / 1000;
  const step = Math.min(STEPS.length - 1, Math.floor(elapsed / 1.5));
  return (
    <div className="card mx-auto max-w-xl p-8 text-center">
      <Loader2 className="mx-auto mb-4 size-8 animate-spin text-brand-600" />
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{a.status === "queued" ? "Waiting in queue..." : "Analysing document..."}</h2>
      <p className="mt-1 text-sm muted">{a.filename}</p>
      <ol className="mx-auto mt-6 max-w-xs space-y-2 text-left text-sm">
        {STEPS.map((s, i) => (
          <li key={s} className={i < step ? "text-slate-400 line-through" : i === step ? "font-medium text-brand-700 dark:text-brand-300" : "muted"}>
            {s}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function AnalysisPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [focus, setFocus] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => api.analysis(id),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "queued" || s === "running" ? 1500 : false;
    },
  });

  const rerun = useMutation({
    mutationFn: () => api.rerun(id),
    onSuccess: (a) => {
      qc.setQueryData(["analysis", id], a);
      qc.invalidateQueries({ queryKey: ["analyses"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analyses"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      navigate("/app/history", { replace: true });
    },
  });

  if (q.isPending) return <Spinner />;
  if (q.error) return <ErrorNote error={q.error} />;
  const a = q.data!;

  const back = (
    <Link to="/app/history" className="mb-4 inline-flex items-center gap-1.5 text-sm muted hover:text-slate-900 dark:hover:text-white">
      <ArrowLeft className="size-4" /> History
    </Link>
  );

  if (a.status === "queued" || a.status === "running")
    return (
      <>
        {back}
        <Pending a={a} />
      </>
    );

  if (a.status === "failed" || !a.result)
    return (
      <>
        {back}
        <div className="card mx-auto max-w-xl p-8 text-center">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Analysis failed</h2>
          <p className="mt-2 text-sm muted">{a.error ?? "Unknown error"}</p>
          <div className="mt-6 flex justify-center gap-2">
            <Button variant="secondary" icon={<Trash2 className="size-4" />} loading={remove.isPending} onClick={() => remove.mutate()}>
              Delete
            </Button>
            <Button icon={<RotateCcw className="size-4" />} loading={rerun.isPending} onClick={() => rerun.mutate()}>
              Try again
            </Button>
          </div>
        </div>
      </>
    );

  const r = a.result;
  const contributions = r.fusion.contributions;
  const ordered = [...r.modules].sort((x, y) => {
    const rank = (m: typeof x) => (m.status === "ok" ? 0 : 1);
    return rank(x) - rank(y) || (contributions[y.key] ?? 0) - (contributions[x.key] ?? 0) || x.score10 - y.score10;
  });
  const totalContribution = Object.values(contributions).reduce((s, v) => s + v, 0) || 1;
  const standalone = r.modules.flatMap((m) => m.artifacts.filter((x) => x.kind === "image").map((x) => ({ ...x, module: m.title })));

  return (
    <>
      {back}
      <div className={`card mb-6 border-l-4 p-6 ${VERDICT_META[r.verdict].ring}`}>
        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          <div className="shrink-0 self-center">
            <ScoreGauge score={r.score} verdict={r.verdict} thresholds={r.thresholds} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <VerdictBadge verdict={r.verdict} size="lg" />
              <span className="text-sm muted">{VERDICT_META[r.verdict].flag}</span>
            </div>
            <h1 className="mt-3 truncate text-xl font-semibold text-slate-900 dark:text-white" title={a.filename}>
              {a.filename}
            </h1>
            <p className="mt-1.5 max-w-3xl text-sm break-words text-slate-600 dark:text-slate-300">{r.summary}</p>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs muted">
              <span>{formatDate(a.created_at)}</span>
              <span>{formatBytes(a.size_bytes)}</span>
              <span>
                {r.document.analysed_pages} of {r.document.page_count} page(s)
              </span>
              {r.template && (
                <span>
                  Template: {r.template.name}
                  {r.template.auto_selected ? " (auto)" : ""}
                </span>
              )}
              <span>{(r.duration_ms / 1000).toFixed(1)} s</span>
              <span className="font-mono" title={a.sha256}>
                sha256 {a.sha256.slice(0, 12)}...
              </span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2 md:flex-col">
            <a href={`/api/analyses/${a.id}/report.pdf`} className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
              <FileDown className="size-4" /> PDF report
            </a>
            <a
              href={`/api/analyses/${a.id}/original`}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <Download className="size-4" /> Original
            </a>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" icon={<RotateCcw className="size-4" />} loading={rerun.isPending} onClick={() => rerun.mutate()} title="Run the analysis again">
                Re-run
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 className="size-4" />}
                loading={remove.isPending}
                onClick={() => window.confirm("Delete this analysis and its files?") && remove.mutate()}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
        {r.document.notes.length > 0 && (
          <ul className="mt-4 space-y-1 rounded-lg bg-slate-50 px-3 py-2 text-xs muted dark:bg-slate-800/50">
            {r.document.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <ErrorNote error={rerun.error || remove.error} />
      </div>

      <div className="grid gap-6 xl:grid-cols-5">
        <div className="min-w-0 xl:col-span-3">
          <DocumentViewer analysisId={a.id} pages={r.pages} modules={r.modules} focus={focus} onFocus={setFocus} />
          {standalone.length > 0 && (
            <div className="mt-6">
              <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">Forensic views</h2>
              <div className="grid gap-4 sm:grid-cols-2">
                {standalone.map((s) => (
                  <a key={s.file} href={fileUrl(a.id, s.file)} target="_blank" rel="noreferrer" className="card group overflow-hidden">
                    <img src={fileUrl(a.id, s.file)} alt={s.label} loading="lazy" className="aspect-[4/3] w-full bg-slate-900 object-contain" />
                    <div className="px-3 py-2 text-sm">
                      <div className="font-medium text-slate-900 group-hover:text-brand-700 dark:text-white">{s.label}</div>
                      <div className="text-xs muted">
                        {s.module}
                        {r.pages.length > 1 ? ` - page ${s.page + 1}` : ""}
                      </div>
                    </div>
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="min-w-0 space-y-3 xl:col-span-2">
          <h2 className="font-semibold text-slate-900 dark:text-white">Module results</h2>
          {ordered.map((m) => (
            <ModuleCard
              key={m.key}
              m={m}
              contribution={contributions[m.key] !== undefined ? contributions[m.key] / totalContribution : undefined}
              focused={focus === m.key}
              onFocus={() => setFocus((f) => (f === m.key ? null : m.key))}
            />
          ))}
          <p className="pt-2 text-xs muted">
            Scores are on the 0-10 scale per module (8-10 green, 4-8 amber, 0-4 red). Fusion: {r.fusion.method}. Engine v{r.engine_version}.
          </p>
        </div>
      </div>
    </>
  );
}
