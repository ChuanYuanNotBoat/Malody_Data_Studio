import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {Button, Card, Form, Input, InputNumber, Select, Space, Table, Tag} from "antd";
import {createSystemTask, getCrawlerStatus, getCrawlerTaskLog, getCrawlerTasks} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {buildCrawlerRunParams, paramsToObject} from "../shared/crawler";
import {statusColor, statusLabel} from "../shared/formatters";
import type {ApiRecord, CrawlerFormValues, CrawlerTaskRow, CrawlerType} from "../shared/types";

type CrawlerPageProps = {
  t: (key: string) => string;
};

const boolOptions = [
  {value: false, label: "false"},
  {value: true, label: "true"}
];

export function CrawlerPage({t}: CrawlerPageProps) {
  const queryClient = useQueryClient();
  const [crawlerType, setCrawlerType] = useState<CrawlerType>("leaderboard");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const statusQuery = useQuery({
    queryKey: ["crawler-status"],
    queryFn: getCrawlerStatus,
    refetchInterval: 5_000
  });
  const tasksQuery = useQuery({
    queryKey: ["crawler-tasks"],
    queryFn: getCrawlerTasks,
    refetchInterval: 5_000
  });
  const logQuery = useQuery({
    queryKey: ["crawler-task-log", selectedTaskId],
    queryFn: () => getCrawlerTaskLog(selectedTaskId, 200),
    enabled: Boolean(selectedTaskId),
    refetchInterval: 3_000
  });
  const runMutation = useMutation({
    mutationFn: (params: URLSearchParams) => createSystemTask("crawler.run", paramsToObject(params)),
    onSuccess: async (data) => {
      if (data?.task_id) setSelectedTaskId(String(data.task_id));
      await Promise.all([
        queryClient.invalidateQueries({queryKey: ["system-tasks"]}),
        queryClient.invalidateQueries({queryKey: ["crawler-tasks"]}),
        queryClient.invalidateQueries({queryKey: ["crawler-status"]})
      ]);
    }
  });
  const tasks: CrawlerTaskRow[] = tasksQuery.data?.tasks ?? [];
  const counts = statusQuery.data?.tasks ?? {};

  return (
    <PageFrame title={t("tab_crawler")} description={t("crawler_desc")}>
      <QueryErrorAlert error={statusQuery.error ?? tasksQuery.error ?? logQuery.error ?? runMutation.error} t={t} />
      <Card title={t("crawler_snapshot")} className="section-card">
        <Space wrap>
          <Tag color="blue">{t("running")}: {counts.running ?? 0}</Tag>
          <Tag color="green">{t("finished_status")}: {counts.finished ?? 0}</Tag>
          <Tag color="red">{t("failed")}: {counts.failed ?? 0}</Tag>
        </Space>
      </Card>
      <Card title={t("start_crawler")} className="section-card">
        <Form<CrawlerFormValues>
          layout="vertical"
          initialValues={{crawler_type: "leaderboard", once: true}}
          onValuesChange={(changed) => {
            if (changed.crawler_type) setCrawlerType(changed.crawler_type as CrawlerType);
          }}
          onFinish={(values) => runMutation.mutate(buildCrawlerRunParams(values))}
        >
          <div className="form-grid">
            <Form.Item name="crawler_type" label={t("type")}>
              <Select options={[
                {value: "leaderboard", label: "leaderboard"},
                {value: "player", label: "player"},
                {value: "stb", label: "stb"}
              ]} />
            </Form.Item>
            <Form.Item name="source" label={t("source")}><Input placeholder={t("optional")} /></Form.Item>
            <Form.Item name="limit" label={t("limit")}><InputNumber min={1} style={{width: "100%"}} /></Form.Item>
            <Form.Item name="rpm" label="rpm"><InputNumber min={1} style={{width: "100%"}} /></Form.Item>
            {crawlerType !== "player" ? (
              <Form.Item name="once" label="once"><Select options={[{value: true, label: "true"}, {value: false, label: "false"}]} /></Form.Item>
            ) : null}
            {crawlerType === "player" ? (
              <>
                <Form.Item name="uid" label="uid"><Input /></Form.Item>
                <Form.Item name="uid_range" label="uid_range"><Input placeholder="1000-2000" /></Form.Item>
                <Form.Item name="from_db" label="from_db"><Select options={boolOptions} /></Form.Item>
                <Form.Item name="max_workers" label="max_workers"><InputNumber min={1} max={8} style={{width: "100%"}} /></Form.Item>
                <Form.Item name="days_since_update" label="days_since_update"><InputNumber min={1} style={{width: "100%"}} /></Form.Item>
              </>
            ) : null}
            {crawlerType === "stb" ? (
              <>
                <Form.Item name="cid_crawl" label="cid_crawl"><Select options={boolOptions} /></Form.Item>
                <Form.Item name="sid_crawl" label="sid_crawl"><Select options={boolOptions} /></Form.Item>
                <Form.Item name="retry_failed" label="retry_failed"><Select options={boolOptions} /></Form.Item>
                <Form.Item name="start" label="start"><InputNumber min={1} style={{width: "100%"}} /></Form.Item>
                <Form.Item name="end" label="end"><InputNumber min={1} style={{width: "100%"}} /></Form.Item>
                <Form.Item name="resume" label="resume"><Select options={[{value: true, label: "true"}, {value: false, label: "false"}]} /></Form.Item>
              </>
            ) : null}
          </div>
          <Button type="primary" htmlType="submit" loading={runMutation.isPending}>{t("run")}</Button>
        </Form>
      </Card>
      <Card title={t("task_list")} className="section-card">
        <Table<CrawlerTaskRow>
          rowKey="task_id"
          dataSource={tasks}
          pagination={{pageSize: 8}}
          locale={{emptyText: t("no_data")}}
          onRow={(record) => ({onClick: () => setSelectedTaskId(record.task_id)})}
          columns={[
            {title: t("task_id"), dataIndex: "task_id"},
            {title: t("type"), dataIndex: "crawler_type"},
            {title: t("status"), dataIndex: "status", render: (value: string) => <Tag color={statusColor(value)}>{statusLabel(value, t)}</Tag>},
            {title: t("started_at"), dataIndex: "started_at"},
            {title: t("ended_at"), dataIndex: "ended_at"}
          ]}
        />
      </Card>
      <Card title={`${t("task_log")} ${selectedTaskId ? `(${selectedTaskId})` : ""}`} className="section-card">
        <Input.TextArea rows={12} value={(logQuery.data?.lines ?? []).join("\n")} placeholder={t("select_task_log")} readOnly />
      </Card>
    </PageFrame>
  );
}

export {buildCrawlerRunParams};
