import type {CrawlerFormValues} from "./types";

export function buildCrawlerRunParams(values: CrawlerFormValues): URLSearchParams {
  const params = new URLSearchParams();
  const crawlerType = values.crawler_type;
  params.set("crawler_type", crawlerType);

  if (crawlerType === "leaderboard") {
    params.set("once", String(values.once ?? true));
    if (values.limit) params.set("limit", String(values.limit));
    if (values.source) params.set("source", values.source);
    return params;
  }

  if (crawlerType === "player") {
    if (values.limit) params.set("limit", String(values.limit));
    if (values.rpm) params.set("rpm", String(values.rpm));
    if (values.uid) params.set("uid", String(values.uid));
    if (values.uid_range) params.set("uid_range", String(values.uid_range));
    if (values.max_workers) params.set("max_workers", String(values.max_workers));
    if (values.days_since_update) params.set("days_since_update", String(values.days_since_update));
    if (values.from_db) params.set("from_db", "true");
    return params;
  }

  params.set("once", String(values.once ?? true));
  if (values.limit) params.set("limit", String(values.limit));
  if (values.source) params.set("source", values.source);
  if (values.rpm) params.set("rpm", String(values.rpm));
  if (values.cid_crawl) params.set("cid_crawl", "true");
  if (values.sid_crawl) params.set("sid_crawl", "true");
  if (values.retry_failed) params.set("retry_failed", "true");
  if (values.start) params.set("start", String(values.start));
  if (values.end) params.set("end", String(values.end));
  if (values.resume === false) params.set("resume", "false");
  return params;
}

export function paramsToObject(params: URLSearchParams): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  params.forEach((value, key) => {
    const current = out[key];
    if (Array.isArray(current)) {
      current.push(value);
    } else if (typeof current !== "undefined") {
      out[key] = [current, value];
    } else {
      out[key] = value;
    }
  });
  return out;
}
