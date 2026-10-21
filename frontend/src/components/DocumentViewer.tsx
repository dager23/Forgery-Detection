import clsx from "clsx";
import { ChevronLeft, ChevronRight, Eye, EyeOff, Layers, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { fileUrl, type ArtifactRef, type Box, type ModuleResult, type PageInfo } from "../api";

export const MODULE_COLORS: Record<string, string> = {
  metadata: "#0ea5e9",
  ela: "#f97316",
  noise: "#14b8a6",
  jpeg: "#eab308",
  copymove: "#a855f7",
  template: "#ef4444",
  cnn: "#ec4899",
  segmentation: "#f43f5e",
};

export default function DocumentViewer({
  analysisId,
  pages,
  modules,
  focus,
  onFocus,
}: {
  analysisId: string;
  pages: PageInfo[];
  modules: ModuleResult[];
  focus: string | null;
  onFocus: (key: string | null) => void;
}) {
  const [pageIdx, setPageIdx] = useState(0);
  const [overlayKey, setOverlayKey] = useState<string | null>(null);
  const [opacity, setOpacity] = useState(0.85);
  const [showBoxes, setShowBoxes] = useState(true);
  const page = pages[pageIdx];

  const overlays = useMemo(
    () =>
      modules.flatMap((m) =>
        m.artifacts
          .filter((a) => a.page === page.index && a.kind !== "image")
          .map((a) => ({ ...a, module: m.key })),
      ),
    [modules, page.index],
  );
  const boxes = useMemo(
    () =>
      modules
        // by default only modules with meaningful evidence draw boxes; focusing shows all of one
        .filter((m) => m.status === "ok" && (focus ? m.key === focus : m.suspicion >= 0.35))
        .flatMap((m) => m.boxes.filter((b) => b.page === page.index).map((b) => ({ ...b, module: m.key }))),
    [modules, page.index, focus],
  );

  // when a module card is focused, show its overlay automatically
  const effectiveOverlay: (ArtifactRef & { module: string }) | undefined = overlayKey
    ? overlays.find((o) => o.key === overlayKey)
    : focus
      ? overlays.find((o) => o.module === focus)
      : undefined;

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <Layers className="size-4 text-slate-500" />
        <select
          className="input w-auto max-w-full min-w-0 flex-1 truncate py-1.5 sm:flex-none"
          value={effectiveOverlay?.key ?? ""}
          onChange={(e) => {
            setOverlayKey(e.target.value || null);
            if (!e.target.value) onFocus(null);
          }}
          aria-label="Forensic overlay"
        >
          <option value="">Original only</option>
          {overlays.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
        {effectiveOverlay && (
          <label className="flex items-center gap-2 text-xs muted">
            Opacity
            <input type="range" min={0.2} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="w-24 accent-brand-600" />
          </label>
        )}
        <button
          onClick={() => setShowBoxes((v) => !v)}
          className={clsx(
            "ml-auto inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium",
            showBoxes ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800",
          )}
        >
          {showBoxes ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
          Regions ({boxes.length})
        </button>
        {focus && (
          <button onClick={() => onFocus(null)} className="rounded-lg px-2 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
            Show all modules
          </button>
        )}
      </div>

      <div className="checker relative bg-slate-100 p-3 dark:bg-slate-950">
        <div className="relative mx-auto" style={{ aspectRatio: `${page.width} / ${page.height}`, maxHeight: "75vh", maxWidth: "100%" }}>
          <img
            src={fileUrl(analysisId, page.image)}
            alt={`Page ${page.index + 1}`}
            className="absolute inset-0 size-full rounded-sm object-contain shadow"
            draggable={false}
          />
          {effectiveOverlay && (
            <img
              src={fileUrl(analysisId, effectiveOverlay.file)}
              alt={effectiveOverlay.label}
              className="pointer-events-none absolute inset-0 size-full object-contain"
              style={{ opacity }}
              draggable={false}
            />
          )}
          {showBoxes &&
            boxes.map((b, i) => <RegionBox key={i} box={b} page={page} color={MODULE_COLORS[b.module] ?? "#ef4444"} />)}
        </div>
      </div>

      {pages.length > 1 && (
        <div className="flex items-center justify-center gap-3 border-t border-slate-200 py-2.5 text-sm dark:border-slate-800">
          <button disabled={pageIdx === 0} onClick={() => setPageIdx((p) => p - 1)} className="rounded-lg p-1.5 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-slate-800" aria-label="Previous page">
            <ChevronLeft className="size-4" />
          </button>
          <span className="tabular-nums">
            Page {pageIdx + 1} / {pages.length}
          </span>
          <button
            disabled={pageIdx === pages.length - 1}
            onClick={() => setPageIdx((p) => p + 1)}
            className="rounded-lg p-1.5 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-slate-800"
            aria-label="Next page"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
      )}
      {showBoxes && boxes.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-200 px-4 py-2.5 text-xs dark:border-slate-800">
          {[...new Set(boxes.map((b) => b.module))].map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5 muted">
              <Square className="size-3" style={{ color: MODULE_COLORS[k], fill: `${MODULE_COLORS[k]}55` }} />
              {modules.find((m) => m.key === k)?.title}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function RegionBox({ box, page, color }: { box: Box & { module: string }; page: PageInfo; color: string }) {
  return (
    <div
      className="group absolute rounded-[2px]"
      style={{
        left: `${(box.x / page.width) * 100}%`,
        top: `${(box.y / page.height) * 100}%`,
        width: `${(Math.max(box.w, 2) / page.width) * 100}%`,
        height: `${(Math.max(box.h, 2) / page.height) * 100}%`,
        border: `2px solid ${color}`,
        background: `${color}22`,
      }}
    >
      <span
        className="pointer-events-none absolute -top-6 left-0 z-10 hidden rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap text-white shadow group-hover:block"
        style={{ background: color }}
      >
        {box.label}
        {box.score < 1 ? ` (${Math.round(box.score * 100)}%)` : ""}
      </span>
    </div>
  );
}
