const REQUEST_TIMEOUT_MS = 20_000;
const DEFAULT_BASES = ["http://127.0.0.1:18765", "http://127.0.0.1:8000"];
const API_BASE_KEY = "app.api_base";
export const API_BASE = DEFAULT_BASES[0];

export type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  message?: string;
  error?: string;
  timestamp?: string;
};

type RequestOptions = RequestInit & { timeoutMs?: number };

function getCandidateApiBases(): string[] {
  const preferred = typeof window !== "undefined" ? window.localStorage.getItem(API_BASE_KEY) : null;
  const envBase =
    (typeof import.meta !== "undefined" &&
      (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE) ||
    "";
  const candidates = [preferred || "", envBase || "", ...DEFAULT_BASES]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  return [...new Set(candidates)];
}

function rememberApiBase(base: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(API_BASE_KEY, base);
  } catch {
    // ignore
  }
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const bases = getCandidateApiBases();
  const perAttemptTimeoutMs = timeoutMs;
  let lastNetworkError: unknown = null;

  for (const base of bases) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), perAttemptTimeoutMs);

    let response: Response;
    try {
      response = await fetch(`${base}${path}`, {
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
        ...init,
        signal: controller.signal
      });
    } catch (error) {
      clearTimeout(timeout);
      if (error instanceof Error && error.name === "AbortError") {
        throw new Error(`Request timeout (${timeoutMs}ms): ${path}`);
      }
      lastNetworkError = error;
      continue;
    }

    clearTimeout(timeout);

    let json: ApiEnvelope<T> | null = null;
    try {
      json = (await response.json()) as ApiEnvelope<T>;
    } catch {
      json = null;
    }

    if (!response.ok || !json || !json.success) {
      const detail = json?.error || json?.message || "unknown error";
      throw new Error(`HTTP ${response.status} ${path}: ${detail}`);
    }

    rememberApiBase(base);
    return json.data as T;
  }

  if (lastNetworkError instanceof Error && lastNetworkError.name === "AbortError") {
    throw new Error(`Request timeout (${perAttemptTimeoutMs}ms/attempt): ${path}`);
  }
  throw new Error(`Unable to connect API for ${path}. Tried: ${bases.join(", ")}`);
}

export async function getDashboardOverview() {
  return request<any>("/analytics/dashboard-overview");
}

export async function getCrawlerStatus() {
  return request<any>("/crawler/status");
}

export async function getCrawlerTasks() {
  return request<any>("/crawler/tasks?limit=50");
}

export async function runCrawler(params: URLSearchParams) {
  return request<any>(`/crawler/run?${params.toString()}`, { method: "POST" });
}

export async function getCrawlerTaskLog(taskId: string, tail = 200) {
  return request<any>(`/crawler/tasks/${encodeURIComponent(taskId)}/log?tail=${tail}`);
}

export async function getQualityReport() {
  return request<any>("/quality/report");
}

export async function runQualityCheck(staleHours = 72) {
  return request<any>(`/quality/check?stale_hours=${staleHours}`, {
    method: "POST",
    body: "null"
  });
}

export async function startQualityCheckJob(staleHours = 72) {
  return request<any>(`/quality/check?stale_hours=${staleHours}&async_mode=true`, {
    method: "POST",
    body: "null",
    timeoutMs: 10_000
  });
}

export async function getQualityCheckJob(jobId: string) {
  return request<any>(`/quality/jobs/${encodeURIComponent(jobId)}`, {
    timeoutMs: 10_000
  });
}

export async function getPlugins() {
  return request<any>("/plugins");
}

export async function runPlugin(pluginId: string, payload?: Record<string, unknown>) {
  return request<any>(`/plugins/${encodeURIComponent(pluginId)}/run`, {
    method: "POST",
    body: JSON.stringify(payload ?? {})
  });
}

export async function createSystemTask(action: string, params?: Record<string, unknown>) {
  return request<any>("/system/tasks", {
    method: "POST",
    body: JSON.stringify({
      action,
      params: params ?? {}
    })
  });
}

export async function getSystemTasks(limit = 100) {
  return request<any>(`/system/tasks?limit=${limit}`);
}

export async function getSystemTask(taskId: string) {
  return request<any>(`/system/tasks/${encodeURIComponent(taskId)}`);
}

export async function getSystemTaskLog(taskId: string, tail = 200) {
  return request<any>(`/system/tasks/${encodeURIComponent(taskId)}/log?tail=${tail}`);
}

export async function getAnalysisAppStatus() {
  return request<any>("/system/analysis-app/status");
}

export async function launchAnalysisApp(payload?: { api_base?: string; open_task_id?: string }) {
  return request<any>("/system/analysis-app/launch", {
    method: "POST",
    body: JSON.stringify(payload ?? {})
  });
}

export async function getDbHealth() {
  return request<any>("/system/db/health");
}

export async function runDbMaintenance(action: "analyze" | "vacuum", confirm = true, dryRun = false) {
  return request<any>(
    `/system/db/maintain?action=${action}&confirm=${String(confirm)}&dry_run=${String(dryRun)}`,
    { method: "POST" }
  );
}

export async function getDbMaintenanceHistory() {
  return request<any>("/system/db/maintain/history?limit=20");
}

export async function getPredefinedQueries() {
  return request<Record<string, any>>("/query/predefined-queries");
}

export type AdvancedQueryPayload = {
  table: string;
  columns?: string[];
  filters?: Array<Record<string, unknown>>;
  order_by?: string[];
  group_by?: string[];
  having?: Array<Record<string, unknown>>;
  limit?: number;
  offset?: number;
  distinct?: boolean;
};

export async function executeAdvancedQuery(payload: AdvancedQueryPayload) {
  const params = new URLSearchParams();
  params.set("table", payload.table);
  (payload.columns ?? []).forEach((col) => params.append("columns", col));
  (payload.order_by ?? []).forEach((order) => params.append("order_by", order));
  (payload.group_by ?? []).forEach((group) => params.append("group_by", group));
  params.set("limit", String(payload.limit ?? 100));
  params.set("offset", String(payload.offset ?? 0));
  params.set("distinct", String(Boolean(payload.distinct)));
  return request<any>(`/query/execute?${params.toString()}`, {
    method: "POST",
    body: JSON.stringify({
      filters: payload.filters ?? null,
      having: payload.having ?? null
    })
  });
}

export async function getModeComparison(modes: string) {
  return request<any>(`/analytics/mode-comparison?modes=${encodeURIComponent(modes)}`);
}

export async function getPlayerCompare(players: string, mode: number, days: number) {
  return request<any>(
    `/analytics/player-compare?players=${encodeURIComponent(players)}&mode=${mode}&days=${days}`
  );
}

export async function getChartTrends(mode: number, period: "days" | "months") {
  return request<any>(`/analytics/chart-trends?mode=${mode}&period=${period}`);
}

export function getChartExportUrl(params: { mode?: number; creators?: string; statuses?: string; format?: "csv" | "xlsx" }) {
  const base = getCandidateApiBases()[0] || DEFAULT_BASES[0];
  const search = new URLSearchParams();
  if (typeof params.mode === "number") search.set("mode", String(params.mode));
  if (params.creators) search.set("creators", params.creators);
  if (params.statuses) search.set("statuses", params.statuses);
  if (params.format) search.set("format", params.format);
  return `${base}/charts/export/charts?${search.toString()}`;
}
