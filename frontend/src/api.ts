// Typed client for the DocAuth API. Auth rides on the httpOnly session cookie.

export type Role = "user" | "admin";
export type Verdict = "authentic" | "suspicious" | "tampered";
export type Status = "queued" | "running" | "done" | "failed";
export type Severity = "info" | "low" | "medium" | "high";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  analysis_count?: number;
}

export interface Finding {
  severity: Severity;
  message: string;
  page: number | null;
}

export interface Box {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  score: number;
}

export interface ArtifactRef {
  key: string;
  label: string;
  page: number;
  kind: "heatmap" | "overlay" | "image";
  file: string;
}

export interface ModuleResult {
  key: string;
  title: string;
  status: "ok" | "skipped" | "error";
  suspicion: number;
  confidence: number;
  score10: number;
  summary: string;
  findings: Finding[];
  boxes: Box[];
  artifacts: ArtifactRef[];
  metrics: Record<string, unknown>;
  duration_ms: number;
}

export interface PageInfo {
  index: number;
  width: number;
  height: number;
  source: string;
  format: string | null;
  image: string;
}

export interface Report {
  engine_version: string;
  verdict: Verdict;
  score: number;
  summary: string;
  thresholds: { authentic: number; tampered: number };
  fusion: { method: string; contributions: Record<string, number>; weights: Record<string, number> };
  template: { name: string; auto_selected: boolean } | null;
  document: {
    filename: string;
    mime: string;
    kind: "image" | "pdf";
    page_count: number;
    analysed_pages: number;
    notes: string[];
  };
  pages: PageInfo[];
  modules: ModuleResult[];
  duration_ms: number;
}

export interface AnalysisSummary {
  id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  status: Status;
  verdict: Verdict | null;
  score: number | null;
  page_count: number | null;
  template_id: number | null;
  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  user_id: number;
  owner_name: string | null;
}

export interface Analysis extends AnalysisSummary {
  sha256: string;
  error: string | null;
  result: Report | null;
  template_name: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Stats {
  total: number;
  authentic: number;
  suspicious: number;
  tampered: number;
  pending: number;
  failed: number;
}

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
  label?: string;
}

export interface Template {
  id: number;
  name: string;
  doc_type: string;
  description: string;
  width: number;
  height: number;
  ignore_regions: Region[];
  created_at: string;
}

export interface Health {
  status: string;
  version: string;
  modules: { key: string; title: string; description: string; available: boolean; reason: string }[];
  models: Record<string, { version?: string; trained_on?: string[]; val_metrics?: Record<string, number> }>;
  calibrated: boolean;
  limits: { max_upload_mb: number; max_pdf_pages: number };
  registration_open: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) {
      return d
        .map((e: { msg?: string; loc?: unknown[] }) => {
          const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
          const msg = (e.msg ?? "Invalid value").replace(/^Value error, /, "");
          return field && field !== "body" ? `${String(field)}: ${msg}` : msg;
        })
        .join("; ");
    }
  }
  return fallback;
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Cannot reach the DocAuth server. Is the backend running?");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) onUnauthorized?.();
    throw new ApiError(res.status, detailMessage(body, `Request failed (${res.status})`));
  }
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  health: () => request<Health>("/api/health"),

  me: () => request<User>("/api/auth/me"),
  login: (email: string, password: string) =>
    request<{ user: User }>("/api/auth/login", { method: "POST", body: json({ email, password }) }),
  register: (name: string, email: string, password: string) =>
    request<{ user: User }>("/api/auth/register", { method: "POST", body: json({ name, email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  analyses: (params: Record<string, string | number | undefined>) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
    return request<Page<AnalysisSummary>>(`/api/analyses?${q}`);
  },
  stats: (scope: "mine" | "all" = "mine") => request<Stats>(`/api/analyses/stats?scope=${scope}`),
  analysis: (id: string) => request<Analysis>(`/api/analyses/${id}`),
  upload: (file: File, templateId: number | "auto" | "none") => {
    const fd = new FormData();
    fd.append("file", file);
    if (typeof templateId === "number") fd.append("template_id", String(templateId));
    fd.append("auto_template", templateId === "auto" ? "true" : "false");
    return request<Analysis>("/api/analyses", { method: "POST", body: fd });
  },
  rerun: (id: string) => request<Analysis>(`/api/analyses/${id}/rerun`, { method: "POST" }),
  remove: (id: string) => request<void>(`/api/analyses/${id}`, { method: "DELETE" }),

  templates: () => request<Template[]>("/api/templates"),
  template: (id: number) => request<Template>(`/api/templates/${id}`),
  createTemplate: (file: File, name: string, docType: string, description: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    fd.append("doc_type", docType || "generic");
    fd.append("description", description);
    return request<Template>("/api/templates", { method: "POST", body: fd });
  },
  updateTemplate: (id: number, patch: Partial<Pick<Template, "name" | "doc_type" | "description" | "ignore_regions">>) =>
    request<Template>(`/api/templates/${id}`, { method: "PATCH", body: json(patch) }),
  deleteTemplate: (id: number) => request<void>(`/api/templates/${id}`, { method: "DELETE" }),

  users: () => request<User[]>("/api/admin/users"),
  updateUser: (id: number, patch: { role?: Role; is_active?: boolean }) =>
    request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: json(patch) }),
};

export const fileUrl = (analysisId: string, name: string) => `/api/analyses/${analysisId}/files/${name}`;
export const templateImageUrl = (id: number, size: "full" | "thumb" = "full") =>
  `/api/templates/${id}/image${size === "thumb" ? "?size=thumb" : ""}`;
