import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, History as HistoryIcon, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import AnalysisTable from "../components/AnalysisTable";
import { Button, EmptyState, ErrorNote, PageHeader, Spinner } from "../components/ui";

const PAGE = 20;

export default function HistoryPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const verdict = params.get("verdict") ?? "";
  const scope = params.get("scope") === "all" && user?.role === "admin" ? "all" : "mine";
  const page = Math.max(0, Number(params.get("page") ?? 0));
  const [q, setQ] = useState(params.get("q") ?? "");

  // debounce the search box into the URL
  useEffect(() => {
    const t = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (q) next.set("q", q);
      else next.delete("q");
      if ((params.get("q") ?? "") !== q) {
        next.delete("page");
        setParams(next, { replace: true });
      }
    }, 300);
    return () => clearTimeout(t);
  }, [q, params, setParams]);

  const query = useQuery({
    queryKey: ["analyses", "list", scope, verdict, params.get("q"), page],
    queryFn: () => api.analyses({ limit: PAGE, offset: page * PAGE, verdict, q: params.get("q") ?? "", scope }),
    placeholderData: keepPreviousData,
    refetchInterval: (qr) => (qr.state.data?.items.some((a) => a.status === "queued" || a.status === "running") ? 2000 : false),
  });

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setParams(next);
  };
  const total = query.data?.total ?? 0;

  return (
    <>
      <PageHeader title="History" subtitle="Every document you've verified, newest first." />
      <div className="card">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-4 dark:border-slate-800">
          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" />
            <input className="input pl-9" placeholder="Search by file name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search by file name" />
          </div>
          <select className="input w-auto" value={verdict} onChange={(e) => set("verdict", e.target.value)} aria-label="Filter by result">
            <option value="">All results</option>
            <option value="authentic">Accepted</option>
            <option value="suspicious">Suspicious</option>
            <option value="tampered">Rejected</option>
          </select>
          {user?.role === "admin" && (
            <select className="input w-auto" value={scope} onChange={(e) => set("scope", e.target.value === "all" ? "all" : "")} aria-label="Whose documents">
              <option value="mine">My documents</option>
              <option value="all">All users</option>
            </select>
          )}
        </div>
        {query.error ? (
          <div className="p-5">
            <ErrorNote error={query.error} />
          </div>
        ) : query.isPending ? (
          <Spinner />
        ) : total === 0 ? (
          <EmptyState icon={<HistoryIcon className="size-6" />} title="Nothing here yet">
            {verdict || params.get("q") ? "No documents match these filters." : "Documents you verify will be listed here."}
          </EmptyState>
        ) : (
          <>
            <AnalysisTable items={query.data!.items} showOwner={scope === "all"} />
            <div className="flex items-center justify-between border-t border-slate-200 px-5 py-3 text-sm dark:border-slate-800">
              <span className="muted">
                {page * PAGE + 1}-{Math.min(total, (page + 1) * PAGE)} of {total}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => set("page", String(page - 1))} icon={<ChevronLeft className="size-4" />}>
                  Previous
                </Button>
                <Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => set("page", String(page + 1))}>
                  Next <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
