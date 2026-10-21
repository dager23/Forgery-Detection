import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, ScanLine, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { api } from "../api";
import Dropzone from "../components/Dropzone";
import { Button, ErrorNote, PageHeader } from "../components/ui";
import { formatBytes } from "../format";

export default function Verify() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const location = useLocation();
  // a file dropped on the dashboard's quick-check box arrives via router state
  const [file, setFile] = useState<File | null>(() => {
    const f = (location.state as { file?: unknown } | null)?.file;
    return f instanceof File ? f : null;
  });
  const [choice, setChoice] = useState<string>("auto");
  const [localError, setLocalError] = useState<string | null>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const maxMb = health.data?.limits.max_upload_mb ?? 25;

  const preview = useMemo(() => (file && file.type.startsWith("image/") ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);

  const upload = useMutation({
    mutationFn: () => {
      const t = choice === "auto" || choice === "none" ? (choice as "auto" | "none") : Number(choice);
      return api.upload(file!, t);
    },
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["analyses"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/app/analyses/${a.id}`);
    },
  });

  function pick(f: File) {
    setLocalError(null);
    upload.reset();
    if (f.size > maxMb * 1024 * 1024) {
      setLocalError(`${f.name} is ${formatBytes(f.size)}; the limit is ${maxMb} MB.`);
      return;
    }
    setFile(f);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Verify a document" subtitle="Upload a scan, photo or PDF. Analysis runs in the background and usually takes a few seconds per page." />

      {!file ? (
        <Dropzone onFile={pick} maxMb={maxMb} />
      ) : (
        <div className="card p-5">
          <div className="flex items-start gap-4">
            <div className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800">
              {preview ? <img src={preview} alt="" className="size-full object-cover" /> : <FileText className="size-8 text-slate-400" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium text-slate-900 dark:text-white">{file.name}</div>
              <div className="text-sm muted">
                {formatBytes(file.size)} - {file.type || "unknown type"}
              </div>
            </div>
            <button onClick={() => setFile(null)} aria-label="Remove file" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
              <X className="size-4" />
            </button>
          </div>

          <div className="mt-6">
            <label htmlFor="template" className="label">
              Reference template
            </label>
            <select id="template" className="input" value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value="auto">Auto-detect from registered templates</option>
              <option value="none">No template comparison</option>
              {templates.data?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.doc_type})
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-xs muted">
              Comparing against a verified original enables the SSIM template-matching module.
            </p>
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setFile(null)}>
              Cancel
            </Button>
            <Button icon={<ScanLine className="size-4" />} loading={upload.isPending} onClick={() => upload.mutate()}>
              Analyse document
            </Button>
          </div>
        </div>
      )}
      <div className="mt-4 space-y-2">
        {localError && <ErrorNote error={localError} />}
        <ErrorNote error={upload.error} />
      </div>
    </div>
  );
}
