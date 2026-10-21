import type { Verdict } from "./api";

export const VERDICT_META: Record<Verdict, { label: string; flag: string; tone: string; ring: string; hex: string }> = {
  authentic: {
    label: "Accepted",
    flag: "Green flag",
    tone: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-400/20",
    ring: "border-emerald-500",
    hex: "#10b981",
  },
  suspicious: {
    label: "Suspicious",
    flag: "Amber flag",
    tone: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/20",
    ring: "border-amber-500",
    hex: "#f59e0b",
  },
  tampered: {
    label: "Rejected",
    flag: "Red flag",
    tone: "bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-400/20",
    ring: "border-rose-500",
    hex: "#f43f5e",
  },
};

/** README bands on the 0-10 module scale: 8-10 green, 4-8 amber, 0-4 red. */
export function bandFor10(score10: number): Verdict {
  if (score10 >= 8) return "authentic";
  if (score10 >= 4) return "suspicious";
  return "tampered";
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}
