import clsx from "clsx";
import { X } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import type { Region } from "../api";

/** Draw / delete normalised rectangles over an image. */
export default function RegionEditor({
  src,
  width,
  height,
  regions,
  onChange,
  readOnly,
}: {
  src: string;
  width: number;
  height: number;
  regions: Region[];
  onChange: (r: Region[]) => void;
  readOnly?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  const pos = (e: PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    };
  };

  const down = (e: PointerEvent) => {
    if (readOnly || e.button !== 0 || (e.target as HTMLElement).closest("[data-region]")) return;
    const p = pos(e);
    ref.current!.setPointerCapture(e.pointerId);
    setDraft({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  const move = (e: PointerEvent) => {
    if (!draft) return;
    const p = pos(e);
    setDraft({ ...draft, x1: p.x, y1: p.y });
  };
  const up = () => {
    if (!draft) return;
    const x = Math.min(draft.x0, draft.x1);
    const y = Math.min(draft.y0, draft.y1);
    const w = Math.abs(draft.x1 - draft.x0);
    const h = Math.abs(draft.y1 - draft.y0);
    setDraft(null);
    if (w * width > 6 && h * height > 6) onChange([...regions, { x, y, w, h, label: `field ${regions.length + 1}` }]);
  };

  return (
    <div
      ref={ref}
      className={clsx("relative touch-none select-none", !readOnly && "cursor-crosshair")}
      style={{ aspectRatio: `${width} / ${height}` }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={() => setDraft(null)}
    >
      <img src={src} alt="Template" className="absolute inset-0 size-full object-contain" draggable={false} />
      {regions.map((r, i) => (
        <div
          key={i}
          data-region
          className="group absolute border-2 border-amber-500 bg-amber-400/25"
          style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }}
        >
          <span className="absolute -top-5 left-0 max-w-[16rem] truncate rounded bg-amber-500 px-1 text-[10px] font-medium text-white">{r.label ?? `field ${i + 1}`}</span>
          {!readOnly && (
            <button
              type="button"
              aria-label="Remove region"
              onClick={() => onChange(regions.filter((_, j) => j !== i))}
              className="absolute -top-2.5 -right-2.5 hidden rounded-full bg-rose-600 p-0.5 text-white shadow group-hover:block"
            >
              <X className="size-3" />
            </button>
          )}
        </div>
      ))}
      {draft && (
        <div
          className="absolute border-2 border-dashed border-brand-600 bg-brand-500/20"
          style={{
            left: `${Math.min(draft.x0, draft.x1) * 100}%`,
            top: `${Math.min(draft.y0, draft.y1) * 100}%`,
            width: `${Math.abs(draft.x1 - draft.x0) * 100}%`,
            height: `${Math.abs(draft.y1 - draft.y0) * 100}%`,
          }}
        />
      )}
    </div>
  );
}
