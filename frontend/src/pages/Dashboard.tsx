import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleAlert, CircleCheck, CircleX, Cpu, FileStack, Gauge, ScanLine } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import AnalysisTable from "../components/AnalysisTable";
import Dropzone from "../components/Dropzone";
import { EmptyState, PageHeader, Spinner } from "../components/ui";

function Stat({ label, value, icon, tone }: { label: string; value: number | string; icon: React.ReactNode; tone: string }) {
  return (
    <div className="card flex items-center gap-4 p-5">
      <div className={`rounded-xl p-2.5 ${tone}`}>{icon}</div>
      <div>
        <div className="text-2xl font-semibold text-slate-900 tabular-nums dark:text-white">{value}</div>
        <div className="text-sm muted">{label}</div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const stats = useQuery({ queryKey: ["stats", "mine"], queryFn: () => api.stats("mine"), refetchInterval: 10_000 });
  const recent = useQuery({
    queryKey: ["analyses", "recent"],
    queryFn: () => api.analyses({ limit: 6 }),
    refetchInterval: (q) => (q.state.data?.items.some((a) => a.status === "queued" || a.status === "running") ? 2000 : false),
  });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  const s = stats.data;
  const deep = health.data?.modules.filter((m) => m.key === "cnn" || m.key === "segmentation") ?? [];

  return (
    <>
      <PageHeader
        title={`Hello, ${user?.name.split(" ")[0] ?? ""}`}
        subtitle="Upload a document to check it, or review your recent verifications."
        actions={
          <Link to="/app/verify" className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
            <ScanLine className="size-4" /> Verify document
          </Link>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Documents checked" value={s?.total ?? "-"} icon={<Gauge className="size-5" />} tone="bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300" />
        <Stat label="Accepted" value={s?.authentic ?? "-"} icon={<CircleCheck className="size-5" />} tone="bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300" />
        <Stat label="Suspicious" value={s?.suspicious ?? "-"} icon={<CircleAlert className="size-5" />} tone="bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300" />
        <Stat label="Rejected" value={s?.tampered ?? "-"} icon={<CircleX className="size-5" />} tone="bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <div className="card min-w-0 xl:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
            <h2 className="font-semibold text-slate-900 dark:text-white">Recent verifications</h2>
            <Link to="/app/history" className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">
              View all <ArrowRight className="size-4" />
            </Link>
          </div>
          {recent.isPending ? (
            <Spinner />
          ) : recent.data?.items.length ? (
            <AnalysisTable items={recent.data.items} />
          ) : (
            <EmptyState icon={<ScanLine className="size-6" />} title="No documents yet">
              Your verifications will appear here.
            </EmptyState>
          )}
        </div>

        <div className="min-w-0 space-y-6">
          <div className="card p-5">
            <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">Quick check</h2>
            <Dropzone compact onFile={(file) => navigate("/app/verify", { state: { file } })} />
          </div>
          <div className="card p-5">
            <h2 className="mb-3 flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
              <Cpu className="size-4" /> Engine status
            </h2>
            {health.data ? (
              <ul className="space-y-2 text-sm">
                <li className="flex justify-between">
                  <span className="muted">Forensic modules</span>
                  <span className="font-medium">
                    {health.data.modules.filter((m) => m.available).length} / {health.data.modules.length} active
                  </span>
                </li>
                {deep.map((m) => (
                  <li key={m.key} className="flex justify-between gap-3">
                    <span className="muted">{m.title}</span>
                    <span className={m.available ? "font-medium text-emerald-600 dark:text-emerald-400" : "font-medium text-amber-600"}>
                      {m.available ? "loaded" : "not trained"}
                    </span>
                  </li>
                ))}
                <li className="flex justify-between">
                  <span className="muted">Score calibration</span>
                  <span className="font-medium">{health.data.calibrated ? "fitted" : "default"}</span>
                </li>
                <li className="flex justify-between">
                  <span className="muted">Version</span>
                  <span className="font-mono">{health.data.version}</span>
                </li>
              </ul>
            ) : (
              <Spinner />
            )}
            <Link to="/app/templates" className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">
              <FileStack className="size-4" /> Reference templates
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
