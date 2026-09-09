import {useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {Card, Input, Table, Tag} from "antd";
import {getSystemTaskLog, getSystemTasks} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {statusColor, statusLabel} from "../shared/formatters";
import type {ApiRecord} from "../shared/types";

type TaskCenterPageProps = {
  t: (key: string) => string;
};

export function TaskCenterPage({t}: TaskCenterPageProps) {
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const tasksQuery = useQuery({
    queryKey: ["system-tasks"],
    queryFn: () => getSystemTasks(200),
    refetchInterval: 3_000
  });
  const taskLogQuery = useQuery({
    queryKey: ["system-task-log", selectedTaskId],
    queryFn: () => getSystemTaskLog(selectedTaskId, 300),
    enabled: Boolean(selectedTaskId),
    refetchInterval: 2_000
  });
  const tasks: ApiRecord[] = tasksQuery.data?.tasks ?? [];
  const events: ApiRecord[] = taskLogQuery.data?.events ?? [];

  return (
    <PageFrame title={t("tab_tasks")} description={t("tasks_desc")}>
      <QueryErrorAlert error={tasksQuery.error ?? taskLogQuery.error} t={t} />
      <Card title={t("task_list")} className="section-card">
        <Table<ApiRecord>
          rowKey={(row) => String(row.task_id ?? "")}
          dataSource={tasks}
          pagination={{pageSize: 10}}
          locale={{emptyText: t("no_data")}}
          onRow={(record) => ({onClick: () => setSelectedTaskId(String(record.task_id ?? ""))})}
          columns={[
            {title: t("task_id"), dataIndex: "task_id"},
            {title: t("op_scope"), dataIndex: "scope"},
            {title: t("action"), dataIndex: "action"},
            {
              title: t("status"),
              dataIndex: "status",
              render: (value: string) => <Tag color={statusColor(value)}>{statusLabel(value, t)}</Tag>
            },
            {title: t("started_at"), dataIndex: "started_at"},
            {title: t("ended_at"), dataIndex: "ended_at"}
          ]}
        />
      </Card>
      <Card title={`${t("task_log")} ${selectedTaskId ? `(${selectedTaskId})` : ""}`} className="section-card">
        <Input.TextArea
          rows={16}
          readOnly
          placeholder={t("select_task_log")}
          value={events.map((item) => JSON.stringify(item)).join("\n")}
        />
      </Card>
    </PageFrame>
  );
}
