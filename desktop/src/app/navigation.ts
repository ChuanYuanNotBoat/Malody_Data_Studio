export const NAV_ITEMS = [
  { key: "overview", labelKey: "tab_overview" },
  { key: "analytics", labelKey: "tab_analytics" },
  { key: "tasks", labelKey: "tab_tasks" },
  { key: "crawler", labelKey: "tab_crawler" },
  { key: "quality", labelKey: "tab_quality" },
  { key: "db", labelKey: "tab_db" },
  { key: "plugins", labelKey: "tab_plugins" },
  { key: "query", labelKey: "tab_query" }
] as const;

export type PageKey = (typeof NAV_ITEMS)[number]["key"];
