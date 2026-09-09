import {useEffect, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Button, Card, message, Space, Table, Tag, Typography} from "antd";
import {getQualityCheckJob, getQualityReport, startQualityCheckJob} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {statusColor, statusLabel} from "../shared/formatters";
import type {QualityIssueRow} from "../shared/types";

type QualityPageProps = {
  t: (key: string) => string;
};

export function QualityPage({t}: QualityPageProps) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState("");
  const [notifiedStatus, setNotifiedStatus] = useState("");
  const reportQuery = useQuery({
    queryKey: ["quality-report"],
    queryFn: getQualityReport,
    refetchInterval: 20_000
  });
  const jobQuery = useQuery({
    queryKey: ["quality-job", jobId],
    queryFn: () => getQualityCheckJob(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = (query.state.data as {status?: string} | undefined)?.status;
      return status === "queued" || status === "running" ? 2_000 : false;
    }
  });
  const runMutation = useMutation({
    mutationFn: (staleHours: number) => startQualityCheckJob(staleHours),
    onSuccess: (data) => {
      setJobId(String(data?.job_id ?? ""));
      setNotifiedStatus("");
    }
  });
  const job = jobQuery.data;
  useEffect(() => {
    const status = job?.status;
    if (!status || status === notifiedStatus) return;
    setNotifiedStatus(status);
    if (status === "finished") {
      message.success(t("quality_done"));
      void queryClient.invalidateQueries({queryKey: ["quality-report"]});
    } else if (status === "failed") {
      message.error(String(job?.error ?? t("error_unknown")));
    }
  }, [job, notifiedStatus, queryClient, t]);
  const issues: QualityIssueRow[] = reportQuery.data?.issues ?? [];

  return (
    <PageFrame title={t("tab_quality")} description={t("quality_desc")}>
      <QueryErrorAlert error={reportQuery.error ?? jobQuery.error ?? runMutation.error} t={t} />
      <Card className="section-card">
        <Space wrap>
          <Button loading={runMutation.isPending} onClick={() => runMutation.mutate(72)}>{t("run_quality_check")}</Button>
          {jobId ? (
            <Tag color={statusColor(job?.status ?? "queued")}>
              job={jobId} status={statusLabel(job?.status ?? "queued", t)}
            </Tag>
          ) : null}
          <Tag color={reportQuery.data?.severity === "high" ? "red" : "gold"}>
            {t("severity")}: {reportQuery.data?.severity ?? "-"}
          </Tag>
          <Tag color="blue">{t("score")}: {reportQuery.data?.score ?? "-"}</Tag>
          <Tag>{t("trend")}: {reportQuery.data?.trend ?? "-"}</Tag>
        </Space>
        {job?.error ? <Typography.Text type="danger" className="inline-error">{String(job.error)}</Typography.Text> : null}
      </Card>
      <Card title={t("quality_issues")} className="section-card">
        <Table<QualityIssueRow>
          rowKey={(row) => `${row.rule_id}-${row.message}`}
          dataSource={issues}
          pagination={{pageSize: 8}}
          locale={{emptyText: t("no_data")}}
          columns={[
            {title: t("rule"), dataIndex: "rule_id"},
            {title: t("severity"), dataIndex: "severity"},
            {title: t("message"), dataIndex: "message"},
            {title: t("recommendation"), dataIndex: "recommendation"}
          ]}
        />
      </Card>
    </PageFrame>
  );
}
