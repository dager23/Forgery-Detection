import { FileText, Image as ImageIcon } from "lucide-react";
import { Link } from "react-router";
import type { AnalysisSummary } from "../api";
import { formatBytes, timeAgo } from "../format";
import { StatusBadge } from "./ui";

export default function AnalysisTable({ items, showOwner }: { items: AnalysisSummary[]; showOwner?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium tracking-wide text-slate-500 uppercase dark:border-slate-800">
            <th className="px-5 py-3">Document</th>
            <th className="px-3 py-3">Result</th>
            <th className="px-3 py-3 text-right">Score</th>
            {showOwner && <th className="px-3 py-3">User</th>}
            <th className="px-5 py-3 text-right">Submitted</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {items.map((a) => (
            <tr key={a.id} className="group hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="px-5 py-3">
                <Link to={`/app/analyses/${a.id}`} className="flex items-center gap-3">
                  <span className="rounded-lg bg-slate-100 p-2 text-slate-500 dark:bg-slate-800">
                    {a.mime === "application/pdf" ? <FileText className="size-4" /> : <ImageIcon className="size-4" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block max-w-xs truncate font-medium text-slate-900 group-hover:text-brand-700 dark:text-white dark:group-hover:text-brand-300">
                      {a.filename}
                    </span>
                    <span className="text-xs muted">
                      {formatBytes(a.size_bytes)}
                      {a.page_count && a.page_count > 1 ? ` - ${a.page_count} pages` : ""}
                    </span>
                  </span>
                </Link>
              </td>
              <td className="px-3 py-3">
                <StatusBadge status={a.status} verdict={a.verdict} />
              </td>
              <td className="px-3 py-3 text-right font-mono tabular-nums">{a.score != null ? Math.round(a.score) : "-"}</td>
              {showOwner && <td className="px-3 py-3 whitespace-nowrap muted">{a.owner_name ?? `#${a.user_id}`}</td>}
              <td className="px-5 py-3 text-right whitespace-nowrap muted">{timeAgo(a.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
