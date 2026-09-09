import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Button, Card, Descriptions, message, Space, Table} from "antd";
import {getDbHealth, getDbMaintenanceHistory, runDbMaintenance} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {formatBytes} from "../shared/formatters";
import type {DBHistoryRow} from "../shared/types";

type DatabasePageProps = {
  t: (key: string) => string;
};

export function DatabasePage({t}: DatabasePageProps) {
  const queryClient = useQueryClient();
  const healthQuery = useQuery({
    queryKey: ["db-health"],
    queryFn: getDbHealth,
    refetchInterval: 20_000
  });
  const historyQuery = useQuery({
    queryKey: ["db-history"],
    queryFn: getDbMaintenanceHistory
  });
  const maintenanceMutation = useMutation({
    mutationFn: ({action, dryRun}: {action: "analyze" | "vacuum"; dryRun: boolean}) =>
      runDbMaintenance(action, true, dryRun),
    onSuccess: async () => {
      message.success(t("maintain_done"));
      await Promise.all([
        queryClient.invalidateQueries({queryKey: ["db-health"]}),
        queryClient.invalidateQueries({queryKey: ["db-history"]})
      ]);
    }
  });
  const health = healthQuery.data;
  const history: DBHistoryRow[] = historyQuery.data?.history ?? [];

  const run = (action: "analyze" | "vacuum", dryRun = false) => {
    const confirmation = action === "vacuum" ? t("confirm_vacuum") : t("confirm_analyze");
    if (!dryRun && !window.confirm(confirmation)) return;
    maintenanceMutation.mutate({action, dryRun});
  };

  return (
    <PageFrame title={t("tab_db")} description={t("db_desc")}>
      <QueryErrorAlert error={healthQuery.error ?? historyQuery.error ?? maintenanceMutation.error} t={t} />
      <Card title={t("db_health")} className="section-card">
        <Descriptions bordered size="small" column={{xs: 1, sm: 2}}>
          <Descriptions.Item label={t("db_path")}>{health?.db_path ?? "-"}</Descriptions.Item>
          <Descriptions.Item label={t("size_mb")}>{formatBytes(health?.file_size_bytes)}</Descriptions.Item>
          <Descriptions.Item label={t("fragmentation")}>{health?.fragmentation_ratio ?? "-"}%</Descriptions.Item>
          <Descriptions.Item label={t("quick_check")}>{health?.quick_check ?? "-"}</Descriptions.Item>
        </Descriptions>
        <Space className="section-actions" wrap>
          <Button loading={maintenanceMutation.isPending} onClick={() => run("analyze")}>{t("run_analyze")}</Button>
          <Button danger loading={maintenanceMutation.isPending} onClick={() => run("vacuum")}>{t("run_vacuum")}</Button>
          <Button loading={maintenanceMutation.isPending} onClick={() => run("analyze", true)}>{t("dry_run")}</Button>
        </Space>
      </Card>
      <Card title={t("maintain_history")} className="section-card">
        <Table<DBHistoryRow>
          rowKey={(row) => `${row.action}-${row.started_at}`}
          dataSource={history}
          pagination={{pageSize: 8}}
          locale={{emptyText: t("no_data")}}
          columns={[
            {title: t("action"), dataIndex: "action"},
            {title: t("success"), dataIndex: "success", render: (value: boolean) => String(value)},
            {title: t("started_at"), dataIndex: "started_at"},
            {title: t("finished"), dataIndex: "finished_at"}
          ]}
        />
      </Card>
    </PageFrame>
  );
}
