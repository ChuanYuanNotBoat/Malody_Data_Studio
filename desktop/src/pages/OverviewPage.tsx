import {useMemo} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import {Button, Card, Col, Descriptions, message, Row, Space, Statistic, Tag, Typography} from "antd";
import {
  getAnalysisAppStatus,
  getCrawlerStatus,
  getDashboardOverview,
  getQualityReport,
  launchAnalysisApp
} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {formatBytes} from "../shared/formatters";

type OverviewPageProps = {
  t: (key: string) => string;
};

export function OverviewPage({t}: OverviewPageProps) {
  const queryClient = useQueryClient();
  const overviewQuery = useQuery({
    queryKey: ["overview"],
    queryFn: getDashboardOverview,
    refetchInterval: 10_000
  });
  const crawlerStatusQuery = useQuery({
    queryKey: ["crawler-status"],
    queryFn: getCrawlerStatus,
    refetchInterval: 5_000
  });
  const qualityQuery = useQuery({
    queryKey: ["quality-report"],
    queryFn: getQualityReport,
    refetchInterval: 20_000
  });
  const analysisAppStatusQuery = useQuery({
    queryKey: ["analysis-app-status"],
    queryFn: getAnalysisAppStatus,
    refetchInterval: 10_000
  });
  const launchAnalysisMutation = useMutation({
    mutationFn: () =>
      launchAnalysisApp({
        api_base: window.localStorage.getItem("app.api_base") ?? "http://127.0.0.1:8000"
      }),
    onSuccess: async (data) => {
      if (data?.ok) message.success(t("analysis_open"));
      else message.error(String(data?.error ?? t("analysis_not_found")));
      await queryClient.invalidateQueries({queryKey: ["analysis-app-status"]});
    },
    onError: (error) => message.error(String(error instanceof Error ? error.message : error))
  });

  const errors = [
    overviewQuery.error,
    crawlerStatusQuery.error,
    qualityQuery.error,
    analysisAppStatusQuery.error
  ].filter(Boolean);
  const chartOption = useMemo(() => {
    const tasks = crawlerStatusQuery.data?.tasks ?? {};
    return {
      tooltip: {trigger: "item"},
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          data: [
            {name: t("running"), value: tasks.running ?? 0},
            {name: t("finished_status"), value: tasks.finished ?? 0},
            {name: t("failed"), value: tasks.failed ?? 0}
          ]
        }
      ]
    };
  }, [crawlerStatusQuery.data, t]);
  const analysisStatus = analysisAppStatusQuery.data;

  return (
    <PageFrame title={t("tab_overview")} description={t("overview_desc")}>
      {errors.map((error, index) => (
        <QueryErrorAlert key={index} error={error} t={t} />
      ))}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title={t("db_size_mb")} value={formatBytes(overviewQuery.data?.database?.file_size_bytes)} /></Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title={t("crawler_running")} value={crawlerStatusQuery.data?.tasks?.running ?? 0} /></Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title={t("crawler_failed")} value={crawlerStatusQuery.data?.tasks?.failed ?? 0} /></Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title={t("quality_score")} value={qualityQuery.data?.score ?? "-"} /></Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} className="section-row">
        <Col xs={24} xl={12}>
          <Card title={t("analysis_app")} className="stretch-card">
            <Space direction="vertical" style={{width: "100%"}}>
              <Typography.Text>{t("analysis_path")}: {analysisStatus?.root ?? "-"}</Typography.Text>
              <Typography.Text type={analysisStatus?.entry_exists ? "success" : "danger"}>
                {t("analysis_status")}: {analysisStatus?.entry_exists ? t("analysis_found") : t("analysis_not_found")}
              </Typography.Text>
              <Space>
                <Button onClick={() => analysisAppStatusQuery.refetch()}>{t("analysis_refresh")}</Button>
                <Button type="primary" loading={launchAnalysisMutation.isPending} onClick={() => launchAnalysisMutation.mutate()}>
                  {t("analysis_open")}
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card title={t("crawler_distribution")} className="stretch-card">
            <ReactECharts option={chartOption} style={{height: 280}} />
          </Card>
        </Col>
      </Row>
      <Card title={t("db_snapshot")} className="section-card">
        <Descriptions bordered column={{xs: 1, sm: 2}} size="small">
          <Descriptions.Item label={t("path")}>{overviewQuery.data?.database?.path ?? "-"}</Descriptions.Item>
          <Descriptions.Item label={t("fragmentation")}>
            {overviewQuery.data?.database?.fragmentation_ratio ?? "-"}%
          </Descriptions.Item>
          <Descriptions.Item label={t("quick_check")}>{overviewQuery.data?.database?.quick_check ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="source_health">
            <Tag color={crawlerStatusQuery.data?.data_source_health?.overall === "healthy" ? "green" : "gold"}>
              {crawlerStatusQuery.data?.data_source_health?.overall ?? "-"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t("generated_at")}>{overviewQuery.data?.generated_at ?? "-"}</Descriptions.Item>
        </Descriptions>
      </Card>
    </PageFrame>
  );
}
