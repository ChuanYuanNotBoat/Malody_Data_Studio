import type {PluginSchema, SchemaProperty} from "./types";

export function parseApiError(error: unknown, t: (key: string) => string): {summary: string; detail?: string} {
  const raw = error instanceof Error ? error.message : String(error ?? t("error_unknown"));
  if (!raw) return {summary: t("error_unknown")};
  if (raw.includes("Request timeout")) {
    return {summary: t("error_timeout"), detail: raw};
  }
  if (raw.startsWith("HTTP ")) {
    const match = raw.match(/^HTTP\s+(\d+)\s+([^:]+):\s*(.*)$/);
    if (match) {
      const [, code, endpoint, detail] = match;
      return {
        summary: `${t("error_request_failed")} (HTTP ${code})`,
        detail: `${endpoint} - ${detail || raw}`
      };
    }
    return {summary: t("error_request_failed"), detail: raw};
  }
  return {summary: raw};
}

export function statusLabel(status: unknown, t: (key: string) => string): string {
  const mapping: Record<string, string> = {
    queued: t("status_queued"),
    pending: t("status_queued"),
    running: t("status_running"),
    finished: t("status_finished"),
    succeeded: t("op_succeeded"),
    failed: t("status_failed"),
    cancelled: t("status_failed"),
    started: t("op_started")
  };
  if (!status) return "-";
  return mapping[String(status)] ?? String(status);
}

export function statusColor(status: unknown): string {
  if (status === "failed" || status === "cancelled") return "red";
  if (status === "running" || status === "queued" || status === "pending") return "blue";
  return "green";
}

export function formatBytes(value: unknown): string {
  const bytes = typeof value === "number" ? value : Number(value ?? 0);
  if (!Number.isFinite(bytes)) return "-";
  return (bytes / (1024 * 1024)).toFixed(2);
}

export function buildDefaultPayload(schema?: PluginSchema): Record<string, unknown> {
  const props = schema?.properties ?? {};
  const out: Record<string, unknown> = {};
  Object.entries(props).forEach(([key, definition]) => {
    const def = definition as SchemaProperty;
    if (typeof def.default !== "undefined") {
      out[key] = def.default;
    } else if (def.type === "boolean") {
      out[key] = false;
    } else if (def.type === "integer" || def.type === "number") {
      out[key] = def.minimum ?? 0;
    } else {
      out[key] = "";
    }
  });
  return out;
}

export function exportRowsToCsv(rows: Record<string, unknown>[], filename: string): void {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const escapeCsv = (value: unknown): string => {
    const raw = String(value ?? "");
    return raw.includes(",") || raw.includes('"') || raw.includes("\n")
      ? `"${raw.replace(/"/g, '""')}"`
      : raw;
  };
  const lines = [headers.join(",")];
  rows.forEach((row) => lines.push(headers.map((key) => escapeCsv(row[key])).join(",")));
  const blob = new Blob([`\uFEFF${lines.join("\n")}`], {type: "text/csv;charset=utf-8;"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}
