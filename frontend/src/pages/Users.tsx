import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Role } from "../api";
import { useAuth } from "../auth";
import { ErrorNote, PageHeader, Spinner } from "../components/ui";
import { formatDate } from "../format";

export default function Users() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users"], queryFn: api.users });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: { role?: Role; is_active?: boolean } }) => api.updateUser(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <>
      <PageHeader title="Users" subtitle="Manage who can verify documents and who administers templates." />
      <ErrorNote error={update.error} />
      <div className="card mt-2 overflow-x-auto">
        {q.isPending ? (
          <Spinner />
        ) : q.error ? (
          <div className="p-5">
            <ErrorNote error={q.error} />
          </div>
        ) : (
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium tracking-wide text-slate-500 uppercase dark:border-slate-800">
                <th className="px-5 py-3">User</th>
                <th className="px-3 py-3">Role</th>
                <th className="px-3 py-3 text-right">Documents</th>
                <th className="px-3 py-3">Joined</th>
                <th className="px-5 py-3 text-right">Access</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {q.data!.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id} className={u.is_active ? "" : "opacity-60"}>
                    <td className="px-5 py-3">
                      <div className="font-medium text-slate-900 dark:text-white">
                        {u.name} {self && <span className="text-xs muted">(you)</span>}
                      </div>
                      <div className="text-xs muted">{u.email}</div>
                    </td>
                    <td className="px-3 py-3">
                      <select
                        className="input w-auto py-1"
                        value={u.role}
                        disabled={self || update.isPending}
                        onChange={(e) => update.mutate({ id: u.id, patch: { role: e.target.value as Role } })}
                        aria-label={`Role for ${u.name}`}
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">{u.analysis_count ?? 0}</td>
                    <td className="px-3 py-3 whitespace-nowrap muted">{formatDate(u.created_at)}</td>
                    <td className="px-5 py-3 text-right">
                      <button
                        disabled={self || update.isPending}
                        onClick={() => update.mutate({ id: u.id, patch: { is_active: !u.is_active } })}
                        className={
                          u.is_active
                            ? "rounded-lg px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-40 dark:hover:bg-rose-500/10"
                            : "rounded-lg px-2.5 py-1 text-xs font-medium text-emerald-600 hover:bg-emerald-50 disabled:opacity-40 dark:hover:bg-emerald-500/10"
                        }
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
