import type {
  QueryTemplateDefinition,
  QueryTemplateParameters,
  QueryTemplateUiConfig
} from "./types";

export const QUERY_TEMPLATE_UI: Record<string, QueryTemplateUiConfig> = {
  top_players_by_mode: {
    titleKey: "query_template_top_players_title",
    descriptionKey: "query_template_top_players_desc",
    fields: [
      {name: "mode", labelKey: "mode", type: "number", min: 0, max: 9, placeholder: "0"},
      {name: "maxRank", labelKey: "query_field_max_rank", type: "number", min: 1, max: 100, defaultValue: 10},
      {name: "limit", labelKey: "limit", type: "number", min: 1, max: 1000}
    ]
  },
  chart_statistics_by_status: {
    titleKey: "query_template_chart_status_title",
    descriptionKey: "query_template_chart_status_desc",
    fields: [
      {
        name: "status",
        labelKey: "query_field_status",
        type: "select",
        defaultValue: 2,
        options: [
          {value: 0, label: "status=0"},
          {value: 1, label: "status=1"},
          {value: 2, label: "status=2"}
        ]
      }
    ]
  },
  player_ranking_history: {
    titleKey: "query_template_player_history_title",
    descriptionKey: "query_template_player_history_desc",
    fields: [
      {name: "playerName", labelKey: "query_field_player_name", type: "text", defaultValue: "Zani", placeholder: "Alice"},
      {name: "limit", labelKey: "limit", type: "number", min: 1, max: 1000}
    ]
  },
  top_creators_by_stable_charts: {
    titleKey: "query_template_creator_title",
    descriptionKey: "query_template_creator_desc",
    fields: [
      {name: "creatorName", labelKey: "query_field_creator", type: "text", placeholder: "Alice"},
      {name: "limit", labelKey: "limit", type: "number", min: 1, max: 1000}
    ]
  }
};

export function cloneTemplateParams(params?: QueryTemplateParameters): QueryTemplateParameters {
  if (!params) {
    return {table: "", columns: [], filters: [], order_by: [], group_by: [], having: [], limit: 100, offset: 0, distinct: false};
  }
  return {
    table: String(params.table ?? ""),
    columns: [...(params.columns ?? [])],
    filters: [...(params.filters ?? [])],
    order_by: [...(params.order_by ?? [])],
    group_by: [...(params.group_by ?? [])],
    having: [...(params.having ?? [])],
    limit: params.limit,
    offset: params.offset,
    distinct: params.distinct
  };
}

function upsertFilter(
  filters: Array<Record<string, unknown>>,
  next: {field: string; operator: string; value?: unknown},
  removeWhenEmpty = false
): Array<Record<string, unknown>> {
  const out = filters.filter((item) => !(item.field === next.field && item.operator === next.operator));
  const isEmpty = next.value === undefined || next.value === null || next.value === "";
  if (!removeWhenEmpty || !isEmpty) {
    out.push({field: next.field, operator: next.operator, value: next.value ?? null});
  }
  return out;
}

export function buildQueryPayloadFromTemplate(
  queryKey: string,
  definition: QueryTemplateDefinition | undefined,
  formValues: Record<string, unknown>
) {
  const params = cloneTemplateParams(definition?.parameters);
  let filters = [...(params.filters ?? [])];
  const limit = typeof formValues.limit === "number" ? formValues.limit : undefined;
  if (typeof limit === "number") params.limit = limit;

  if (queryKey === "top_players_by_mode") {
    if (typeof formValues.maxRank === "number") filters = upsertFilter(filters, {field: "rank", operator: "<=", value: formValues.maxRank});
    if (typeof formValues.mode === "number") filters = upsertFilter(filters, {field: "mode", operator: "=", value: formValues.mode}, true);
  }
  if (queryKey === "chart_statistics_by_status" && typeof formValues.status === "number") {
    filters = upsertFilter(filters, {field: "status", operator: "=", value: formValues.status}, true);
  }
  if (queryKey === "player_ranking_history") {
    filters = upsertFilter(filters, {field: "name", operator: "LIKE", value: formValues.playerName}, true);
  }
  if (queryKey === "top_creators_by_stable_charts" && typeof formValues.creatorName === "string" && formValues.creatorName.trim()) {
    filters = upsertFilter(filters, {field: "creator_name", operator: "LIKE", value: formValues.creatorName.trim()});
  }

  return {
    table: params.table,
    columns: params.columns ?? [],
    filters,
    order_by: params.order_by ?? [],
    group_by: params.group_by ?? [],
    having: params.having ?? [],
    limit: params.limit ?? 100,
    offset: params.offset ?? 0,
    distinct: Boolean(params.distinct)
  };
}

export function getQueryInitialValues(queryKey: string, definition?: QueryTemplateDefinition): Record<string, unknown> {
  if (!queryKey) return {};
  const defaults: Record<string, unknown> = {};
  (QUERY_TEMPLATE_UI[queryKey]?.fields ?? []).forEach((field) => {
    if (typeof field.defaultValue !== "undefined") defaults[field.name] = field.defaultValue;
  });
  if (typeof definition?.parameters?.limit === "number") defaults.limit = definition.parameters.limit;
  return defaults;
}
