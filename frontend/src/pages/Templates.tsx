import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileStack, Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api, templateImageUrl } from "../api";
import { useAuth } from "../auth";
import { Button, EmptyState, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { formatDate } from "../format";

function NewTemplate({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () => api.createTemplate(file!, name.trim(), docType.trim(), description.trim()),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      navigate(`/app/templates/${t.id}`);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (file && name.trim()) create.mutate();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <form onSubmit={submit} className="card relative w-full max-w-lg p-6" role="dialog" aria-label="New template">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New reference template</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800">
            <X className="size-4" />
          </button>
        </div>
        <p className="mb-4 text-sm muted">
          Upload a clean, verified copy of a document type. After saving you'll mark the fields that legitimately differ between
          holders (name, photo, dates) so they're ignored during comparison.
        </p>
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="tfile">
              Reference image or single-page PDF
            </label>
            <input id="tfile" type="file" accept="image/*,.pdf" className="input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="tname">
                Name
              </label>
              <input id="tname" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Income certificate (MH)" required />
            </div>
            <div>
              <label className="label" htmlFor="ttype">
                Document type
              </label>
              <input id="ttype" className="input" value={docType} onChange={(e) => setDocType(e.target.value)} placeholder="income" />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="tdesc">
              Description
            </label>
            <textarea id="tdesc" rows={2} className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <ErrorNote error={create.error} />
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending} disabled={!file || !name.trim()}>
            Save & mark fields
          </Button>
        </div>
      </form>
    </div>
  );
}

export default function Templates() {
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const [adding, setAdding] = useState(false);
  const q = useQuery({ queryKey: ["templates"], queryFn: api.templates });

  return (
    <>
      <PageHeader
        title="Reference templates"
        subtitle="Verified originals used by the SSIM template-matching module to spot added or missing content."
        actions={
          admin && (
            <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
              New template
            </Button>
          )
        }
      />
      {q.isPending ? (
        <Spinner />
      ) : q.error ? (
        <ErrorNote error={q.error} />
      ) : q.data!.length === 0 ? (
        <div className="card">
          <EmptyState icon={<FileStack className="size-6" />} title="No templates yet">
            {admin
              ? "Add a verified copy of each document type you check. Tip: run `docauth seed-demo` to load demo templates."
              : "An administrator hasn't added any reference templates yet."}
          </EmptyState>
        </div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {q.data!.map((t) => (
            <Link key={t.id} to={`/app/templates/${t.id}`} className="card group overflow-hidden">
              <div className="aspect-[3/4] overflow-hidden border-b border-slate-200 bg-slate-100 dark:border-slate-800 dark:bg-slate-800">
                <img src={templateImageUrl(t.id)} alt="" loading="lazy" className="size-full object-cover object-top transition-transform group-hover:scale-[1.02]" />
              </div>
              <div className="p-4">
                <div className="font-medium text-slate-900 group-hover:text-brand-700 dark:text-white dark:group-hover:text-brand-300">{t.name}</div>
                <div className="mt-0.5 text-xs muted">
                  {t.doc_type} - {t.ignore_regions.length} variable field(s) - added {formatDate(t.created_at)}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
      {adding && <NewTemplate onClose={() => setAdding(false)} />}
    </>
  );
}
