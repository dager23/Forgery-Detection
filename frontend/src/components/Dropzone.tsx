import clsx from "clsx";
import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const ACCEPT = ".jpg,.jpeg,.png,.tif,.tiff,.bmp,.webp,.pdf,image/jpeg,image/png,image/tiff,image/bmp,image/webp,application/pdf";

export default function Dropzone({
  onFile,
  maxMb,
  compact,
}: {
  onFile: (f: File) => void;
  maxMb?: number;
  compact?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  // Paste a screenshot / copied image straight from the clipboard
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const f = Array.from(e.clipboardData?.files ?? [])[0];
      if (f) onFile(f);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onFile]);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files[0];
        if (f) onFile(f);
      }}
      className={clsx(
        "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed text-center transition-colors",
        compact ? "px-4 py-8" : "px-6 py-16",
        over
          ? "border-brand-500 bg-brand-50 dark:bg-brand-500/10"
          : "border-slate-300 bg-white hover:border-brand-400 hover:bg-brand-50/40 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800/50",
      )}
    >
      <div className="mb-3 rounded-full bg-brand-100 p-3 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
        <Upload className="size-6" />
      </div>
      <p className="font-medium text-slate-900 dark:text-white">
        Drop a document here, <span className="text-brand-600 dark:text-brand-400">browse</span>, or paste
      </p>
      <p className="mt-1 text-xs muted">
        JPEG, PNG, TIFF, BMP, WebP or PDF{maxMb ? ` - up to ${maxMb} MB` : ""}
      </p>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
