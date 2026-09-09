export type ApiRecord = Record<string, unknown>;

export type DashboardOverview = {
  generated_at?: string;
  database?: {
    path?: string;
    file_size_bytes?: number;
    fragmentation_ratio?: number;
    quick_check?: string;
  };
  charts?: ApiRecord;
  players_mm?: ApiRecord;
  crawler_tasks?: ApiRecord;
};

export type CrawlerStatus = {
  tasks?: Record<string, number>;
  data_source_health?: {overall?: string; [key: string]: unknown};
};

export type SystemTask = {
  task_id?: string;
  scope?: string;
  action?: string;
  status?: string;
  started_at?: string;
  ended_at?: string;
  [key: string]: unknown;
};

export type TaskLog = {
  found?: boolean;
  task_id?: string;
  lines?: string[];
  events?: ApiRecord[];
  log_file?: string | null;
};

export type QualityReport = {
  score?: number;
  severity?: string;
  trend?: string;
  issues?: QualityIssueRow[];
  [key: string]: unknown;
};

export type QualityJob = {
  job_id?: string;
  status?: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  report?: QualityReport | null;
};

export type DBHealth = {
  db_path?: string;
  file_size_bytes?: number;
  fragmentation_ratio?: number;
  quick_check?: string;
};

export type PluginRunResult = {
  plugin_id?: string;
  ok?: boolean;
  result?: unknown;
  [key: string]: unknown;
};

export type AnalysisAppStatus = {
  root?: string;
  entry_exists?: boolean;
  ok?: boolean;
  error?: string;
};

export type CrawlerType = "leaderboard" | "player" | "stb";

export type CrawlerFormValues = {
  crawler_type: CrawlerType;
  once?: boolean;
  limit?: number;
  source?: string;
  rpm?: number;
  uid?: string;
  uid_range?: string;
  max_workers?: number;
  days_since_update?: number;
  from_db?: boolean;
  cid_crawl?: boolean;
  sid_crawl?: boolean;
  retry_failed?: boolean;
  start?: number;
  end?: number;
  resume?: boolean;
};

export type CrawlerTaskRow = {
  task_id: string;
  crawler_type: string;
  status: string;
  started_at?: string;
  ended_at?: string;
};

export type QualityIssueRow = {
  rule_id: string;
  severity: string;
  message: string;
  recommendation?: string;
};

export type DBHistoryRow = {
  action: string;
  success: boolean;
  started_at: string;
  finished_at?: string;
};

export type SchemaProperty = {
  type?: string;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  default?: unknown;
  description?: string;
};

export type PluginSchema = {
  type?: string;
  properties?: Record<string, SchemaProperty>;
};

export type PluginRow = {
  id: string;
  name: string;
  version: string;
  capabilities?: string[];
  config_schema?: PluginSchema;
  run_schema?: PluginSchema;
};

export type QueryTemplateParameters = {
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

export type QueryTemplateDefinition = {
  description?: string;
  endpoint?: string;
  method?: string;
  parameters?: QueryTemplateParameters;
};

export type QueryTemplateField = {
  name: string;
  labelKey: string;
  type: "text" | "number" | "select";
  min?: number;
  max?: number;
  placeholder?: string;
  options?: Array<{value: string | number; label: string}>;
  defaultValue?: string | number;
};

export type QueryTemplateUiConfig = {
  titleKey: string;
  descriptionKey: string;
  fields: QueryTemplateField[];
};
