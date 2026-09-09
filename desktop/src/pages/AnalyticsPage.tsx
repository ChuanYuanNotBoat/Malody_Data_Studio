import {useMutation} from "@tanstack/react-query";
import {Button, Card, Form, Input, InputNumber, Select, Table} from "antd";
import {getChartTrends, getModeComparison, getPlayerCompare} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import type {ApiRecord} from "../shared/types";

type AnalyticsPageProps = {
  t: (key: string) => string;
};

const textCell = (value: unknown) => String(value ?? "-");

export function AnalyticsPage({t}: AnalyticsPageProps) {
  const modeCompareMutation = useMutation({mutationFn: getModeComparison});
  const playerCompareMutation = useMutation({
    mutationFn: ({players, mode, days}: {players: string; mode: number; days: number}) =>
      getPlayerCompare(players, mode, days)
  });
  const chartTrendMutation = useMutation({
    mutationFn: ({mode, period}: {mode: number; period: "days" | "months"}) => getChartTrends(mode, period)
  });
  const modeRows: ApiRecord[] = Array.isArray(modeCompareMutation.data) ? modeCompareMutation.data : [];
  const playerRows: ApiRecord[] = Array.isArray(playerCompareMutation.data?.players)
    ? playerCompareMutation.data.players
    : [];
  const chartRows: ApiRecord[] = Array.isArray(chartTrendMutation.data) ? chartTrendMutation.data : [];

  return (
    <PageFrame title={t("tab_analytics")} description={t("analytics_desc")}>
      <Card title={t("analytics_mode_compare")} className="section-card">
        <Form layout="inline" initialValues={{modes: "0,1,2,3"}} onFinish={(values) => modeCompareMutation.mutate(values.modes)}>
          <Form.Item name="modes" label={t("modes")}>
            <Input style={{width: 220}} placeholder="0,1,2" />
          </Form.Item>
          <Form.Item>
            <Button htmlType="submit" loading={modeCompareMutation.isPending}>{t("run")}</Button>
          </Form.Item>
        </Form>
        <QueryErrorAlert error={modeCompareMutation.error} t={t} />
        <Table<ApiRecord>
          className="table-spacing"
          rowKey={(row) => String(row.mode ?? JSON.stringify(row))}
          dataSource={modeRows}
          size="small"
          pagination={{pageSize: 6}}
          locale={{emptyText: t("no_data")}}
          columns={[
            {title: "mode", dataIndex: "mode", render: textCell},
            {title: "total_charts", dataIndex: "total_charts", render: textCell},
            {title: "stable_charts", dataIndex: "stable_charts", render: textCell},
            {title: "avg_heat", dataIndex: "avg_heat", render: textCell}
          ]}
        />
      </Card>

      <Card title={t("analytics_player_compare")} className="section-card">
        <Form
          layout="inline"
          initialValues={{players: "alice,bob", mode: 0, days: 30}}
          onFinish={(values) =>
            playerCompareMutation.mutate({
              players: values.players,
              mode: Number(values.mode),
              days: Number(values.days)
            })
          }
        >
          <Form.Item name="players" label={t("players")}>
            <Input style={{width: 220}} placeholder="alice,bob" />
          </Form.Item>
          <Form.Item name="mode" label={t("mode")}><InputNumber min={0} max={9} /></Form.Item>
          <Form.Item name="days" label={t("days")}><InputNumber min={1} max={365} /></Form.Item>
          <Form.Item><Button htmlType="submit" loading={playerCompareMutation.isPending}>{t("run")}</Button></Form.Item>
        </Form>
        <QueryErrorAlert error={playerCompareMutation.error} t={t} />
        <Table<ApiRecord>
          className="table-spacing"
          rowKey={(row) => String(row.player_identifier ?? row.name ?? JSON.stringify(row))}
          dataSource={playerRows}
          size="small"
          pagination={{pageSize: 6}}
          locale={{emptyText: t("no_data")}}
          columns={[
            {title: "player", dataIndex: "player_identifier", render: textCell},
            {title: "start_rank", dataIndex: "start_rank", render: textCell},
            {title: "end_rank", dataIndex: "end_rank", render: textCell},
            {title: "rank_change", dataIndex: "rank_change", render: textCell}
          ]}
        />
      </Card>

      <Card title={t("analytics_chart_trends")} className="section-card">
        <Form
          layout="inline"
          initialValues={{mode: 0, period: "months"}}
          onFinish={(values) => chartTrendMutation.mutate({mode: Number(values.mode), period: values.period})}
        >
          <Form.Item name="mode" label={t("mode")}><InputNumber min={0} max={9} /></Form.Item>
          <Form.Item name="period" label={t("period")}>
            <Select
              style={{width: 140}}
              options={[{value: "days", label: "days"}, {value: "months", label: "months"}]}
            />
          </Form.Item>
          <Form.Item><Button htmlType="submit" loading={chartTrendMutation.isPending}>{t("run")}</Button></Form.Item>
        </Form>
        <QueryErrorAlert error={chartTrendMutation.error} t={t} />
        <Table<ApiRecord>
          className="table-spacing"
          rowKey={(row) => String(row.period ?? JSON.stringify(row))}
          dataSource={chartRows}
          size="small"
          pagination={{pageSize: 6}}
          locale={{emptyText: t("no_data")}}
          columns={[
            {title: "period", dataIndex: "period", render: textCell},
            {title: "total", dataIndex: "count", render: textCell},
            {title: "stable", dataIndex: "stable_count", render: textCell}
          ]}
        />
      </Card>
    </PageFrame>
  );
}
