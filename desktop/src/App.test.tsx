import React from "react";
import {beforeEach, describe, expect, it, vi} from "vitest";
import {render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import App, {buildCrawlerRunParams} from "./App";
import * as api from "./api";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="chart-mock" />
}));

vi.mock("./api", () => {
  return {
    getDashboardOverview: vi.fn().mockResolvedValue({
      generated_at: "2026-01-01T00:00:00",
      database: {
        path: "x",
        file_size_bytes: 1024,
        fragmentation_ratio: 0,
        quick_check: "ok"
      },
      players_mm: { freshness: {}, tracked_players: {} },
      charts: { total_charts: 1, unique_songs: 1, unique_creators: 1, status_distribution: {} },
      crawler_tasks: { total: 0, running: 0, failed: 0, finished: 0, latest: [] }
    }),
    getCrawlerStatus: vi.fn().mockResolvedValue({ tasks: { running: 0, failed: 0, finished: 0 } }),
    getCrawlerTasks: vi.fn().mockResolvedValue({ tasks: [], count: 0 }),
    getCrawlerTaskLog: vi.fn().mockResolvedValue({ lines: [] }),
    getDbHealth: vi.fn().mockResolvedValue({ db_path: "x", file_size_bytes: 1024, fragmentation_ratio: 0, quick_check: "ok" }),
    getDbMaintenanceHistory: vi.fn().mockResolvedValue({ history: [] }),
    getPlugins: vi.fn().mockResolvedValue({ plugins: [] }),
    getPredefinedQueries: vi.fn().mockResolvedValue({}),
    executeAdvancedQuery: vi.fn().mockResolvedValue([]),
    getModeComparison: vi.fn().mockResolvedValue([]),
    getPlayerCompare: vi.fn().mockResolvedValue({ players: [] }),
    getChartTrends: vi.fn().mockResolvedValue([]),
    getChartExportUrl: vi.fn().mockReturnValue("http://127.0.0.1:18765/charts/export/charts?format=csv"),
    getQualityReport: vi.fn().mockResolvedValue({ score: 90, severity: "low", trend: "stable", issues: [] }),
    getAnalysisAppStatus: vi.fn().mockResolvedValue({ root: "x", entry_exists: false }),
    launchAnalysisApp: vi.fn().mockResolvedValue({ ok: false }),
    runCrawler: vi.fn().mockResolvedValue({ command: [], task: { task_id: "t1" } }),
    runDbMaintenance: vi.fn().mockResolvedValue({ action: "analyze", success: true }),
    runPlugin: vi.fn().mockResolvedValue({ plugin_id: "p1", ok: true }),
    startQualityCheckJob: vi.fn(),
    getQualityCheckJob: vi.fn()
  };
});

function renderApp() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false }
    }
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}

describe("App GUI flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem("app.locale", "en-US");

    vi.mocked(api.startQualityCheckJob).mockResolvedValue({ job_id: "job-123", status: "queued" } as never);
    vi.mocked(api.getQualityCheckJob)
      .mockResolvedValueOnce({ job_id: "job-123", status: "running" } as never)
      .mockResolvedValue({
        job_id: "job-123",
        status: "finished",
        started_at: "2026-01-01T00:00:00",
        finished_at: "2026-01-01T00:00:02",
        report: { score: 91 }
      } as never);
  });

  it("renders overview and supports language toggle", async () => {
    renderApp();
    expect((await screen.findAllByText("Malody Data Studio")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Overview")).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("combobox"));
    const englishOptions = await screen.findAllByText("English");
    await userEvent.click(englishOptions[englishOptions.length - 1]);
    await waitFor(() => expect(screen.getAllByText("Overview").length).toBeGreaterThan(0));
  });

  it("starts quality job and shows job status tag", async () => {
    renderApp();
    await userEvent.click(await screen.findByText("Data Quality"));
    await userEvent.click(await screen.findByText("Run Quality Check"));
    await waitFor(() => expect(screen.getAllByText(/job=job-123/i).length).toBeGreaterThan(0));
  });

  it("shows failed status when quality job fails", async () => {
    vi.mocked(api.getQualityCheckJob).mockReset();
    vi.mocked(api.getQualityCheckJob).mockResolvedValue({
      job_id: "job-123",
      status: "failed",
      error: "boom"
    } as never);

    renderApp();
    await userEvent.click(await screen.findByText("Data Quality"));
    await userEvent.click(await screen.findByText("Run Quality Check"));

    await waitFor(() => expect(screen.getAllByText(/job=job-123/i).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText(/job=job-123 status=Failed/i)).toBeInTheDocument());
  });

  it("does not run vacuum maintenance when user cancels confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderApp();
    await userEvent.click(await screen.findByText("DB Maintenance"));
    await userEvent.click(await screen.findByText("Run VACUUM"));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(api.runDbMaintenance).not.toHaveBeenCalled();
  });

  it("shows request error summary when a query fails", async () => {
    vi.mocked(api.getDashboardOverview).mockRejectedValueOnce(new Error("overview failed") as never);
    renderApp();
    expect(await screen.findByText("overview failed")).toBeInTheDocument();
    expect(screen.getByText(/overview failed/i)).toBeInTheDocument();
  });

  it("shows concise HTTP error with expandable technical details", async () => {
    vi.mocked(api.getPlugins).mockRejectedValueOnce(new Error("HTTP 500 /plugins: boom") as never);
    renderApp();
    await userEvent.click(await screen.findByText("Plugins"));
    expect(screen.getByText(/request failed \(HTTP 500\)/i)).toBeInTheDocument();
    expect(screen.getByText("View technical details")).toBeInTheDocument();
    expect(screen.getByText(/\/plugins - boom/i)).toBeInTheDocument();
  });

  it("runs analytics mode comparison", async () => {
    renderApp();
    await userEvent.click(await screen.findByText("Analytics"));
    await userEvent.click((await screen.findAllByRole("button", { name: "Run" }))[0]);
    await waitFor(() => expect(api.getModeComparison).toHaveBeenCalled());
    expect(vi.mocked(api.getModeComparison).mock.calls[0][0]).toBe("0,1,2,3");
  });

  it("executes predefined query and renders result", async () => {
    vi.mocked(api.getPredefinedQueries).mockResolvedValueOnce({
      top_players_by_mode: {
        parameters: {
          table: "player_rankings",
          columns: ["mode", "rank", "name"],
          filters: [{ field: "rank", operator: "<=", value: 10 }],
          order_by: ["mode", "rank"],
          group_by: ["mode"],
          limit: 50
        }
      }
    } as never);
    vi.mocked(api.executeAdvancedQuery).mockResolvedValueOnce([{ mode: 0, rank: 1, name: "Alice" }] as never);

    renderApp();
    await userEvent.click(await screen.findByText("Query & Export"));
    await userEvent.click(await screen.findByRole("button", { name: "Run Task" }));

    await waitFor(() => expect(api.executeAdvancedQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.executeAdvancedQuery).mock.calls[0][0]).toEqual({
      table: "player_rankings",
      columns: ["mode", "rank", "name"],
      filters: [{ field: "rank", operator: "<=", value: 10 }],
      order_by: ["mode", "rank"],
      group_by: ["mode"],
      having: [],
      limit: 50,
      offset: 0,
      distinct: false
    });
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });

  it("runs plugin with schema-driven payload", async () => {
    vi.mocked(api.getPlugins).mockResolvedValueOnce({
      plugins: [
        {
          id: "analysis.quality_snapshot",
          name: "Quality Snapshot",
          version: "1.0.0",
          capabilities: ["analysis"],
          run_schema: {
            type: "object",
            properties: {
              stale_hours: { type: "integer", default: 24, minimum: 1, maximum: 168 },
              include_history: { type: "boolean", default: true }
            }
          }
        }
      ]
    } as never);

    renderApp();
    await userEvent.click(await screen.findByText("Plugins"));
    await userEvent.click(await screen.findByRole("button", { name: "Config" }));
    await userEvent.click((await screen.findAllByRole("button", { name: "Run" }))[0]);

    await waitFor(() =>
      expect(api.runPlugin).toHaveBeenCalledWith("analysis.quality_snapshot", {
        payload: { stale_hours: 24, include_history: true }
      })
    );
  });

  it("buildCrawlerRunParams keeps params isolated by crawler type", () => {
    const leaderboard = buildCrawlerRunParams({
      crawler_type: "leaderboard",
      source: "newapi",
      limit: 100,
      uid: "1001",
      from_db: true
    });
    expect(leaderboard.get("crawler_type")).toBe("leaderboard");
    expect(leaderboard.get("source")).toBe("newapi");
    expect(leaderboard.get("uid")).toBeNull();
    expect(leaderboard.get("from_db")).toBeNull();

    const player = buildCrawlerRunParams({
      crawler_type: "player",
      uid: "1001",
      from_db: true,
      cid_crawl: true
    });
    expect(player.get("crawler_type")).toBe("player");
    expect(player.get("uid")).toBe("1001");
    expect(player.get("from_db")).toBe("true");
    expect(player.get("cid_crawl")).toBeNull();
  });
});
