import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MousePointerSquareDashed, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, templateImageUrl, type Region } from "../api";
import { useAuth } from "../auth";
import RegionEditor from "../components/RegionEditor";
import { Button, ErrorNote, PageHeader, Spinner } from "../components/ui";

export default function TemplateEditor() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["template", id], queryFn: () => api.template(id) });
  const [regions, setRegions] = useState<Region[]>([]);
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (q.data) {
      setRegions(q.data.ignore_regions);
      setName(q.data.name);
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: () => api.updateTemplate(id, { name: name.trim(), ignore_regions: regions }),
    onSuccess: (t) => {
      qc.setQueryData(["template", id], t);
      qc.invalidateQueries({ queryKey: ["templates"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteTemplate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      navigate("/app/templates", { replace: true });
    },
  });

  if (q.isPending) return <Spinner />;
  if (q.error) return <ErrorNote error={q.error} />;
  const t = q.data!;
  const dirty = JSON.stringify(regions) !== JSON.stringify(t.ignore_regions) || name.trim() !== t.name;

  return (
    <>
      <Link to="/app/templates" className="mb-4 inline-flex items-center gap-1.5 text-sm muted hover:text-slate-900 dark:hover:text-white">
        <ArrowLeft className="size-4" /> Templates
      </Link>
      <PageHeader
        title={t.name}
        subtitle={`${t.doc_type} - ${t.width} x ${t.height}px`}
        actions={
          admin && (
            <>
              <Button
                variant="secondary"
                icon={<Trash2 className="size-4" />}
                loading={del.isPending}
                onClick={() => window.confirm("Delete this template?") && del.mutate()}
              >
                Delete
              </Button>
              <Button icon={<Save className="size-4" />} loading={save.isPending} disabled={!dirty || !name.trim()} onClick={() => save.mutate()}>
                {saved ? "Saved" : "Save changes"}
              </Button>
            </>
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="card checker overflow-hidden p-3 lg:col-span-2">
          <RegionEditor src={templateImageUrl(t.id)} width={t.width} height={t.height} regions={regions} onChange={setRegions} readOnly={!admin} />
        </div>
        <div className="space-y-4">
          {admin && (
            <div className="card p-5">
              <label className="label" htmlFor="tn">
                Name
              </label>
              <input id="tn" className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          )}
          <div className="card p-5">
            <h2 className="mb-2 flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
              <MousePointerSquareDashed className="size-4" /> Variable fields
            </h2>
            <p className="text-sm muted">
              {admin
                ? "Drag on the image to mark regions that differ between genuine copies (name, photo, dates, serial numbers). Hover a region and click x to remove it."
                : "Highlighted regions are ignored during template comparison."}
            </p>
            {regions.length > 0 ? (
              <ul className="mt-4 space-y-1.5 text-sm">
                {regions.map((r, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="size-2.5 rounded-sm bg-amber-500" />
                    {admin ? (
                      <input
                        className="input py-1 text-xs"
                        value={r.label ?? ""}
                        aria-label={`Label for region ${i + 1}`}
                        onChange={(e) => setRegions(regions.map((x, j) => (j === i ? { ...x, label: e.target.value.slice(0, 60) } : x)))}
                      />
                    ) : (
                      <span>{r.label ?? `field ${i + 1}`}</span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-sm muted">No variable fields marked.</p>
            )}
            <ErrorNote error={save.error || del.error} />
          </div>
          {t.description && <div className="card p-5 text-sm muted">{t.description}</div>}
        </div>
      </div>
    </>
  );
}
