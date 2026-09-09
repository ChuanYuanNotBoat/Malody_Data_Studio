import {useEffect, useMemo, useState} from "react";
import {useMutation, useQuery} from "@tanstack/react-query";
import {Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Table, Tag, Typography} from "antd";
import {executeAdvancedQuery, getChartExportUrl, getPredefinedQueries} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {exportRowsToCsv} from "../shared/formatters";
import {buildQueryPayloadFromTemplate, getQueryInitialValues, QUERY_TEMPLATE_UI} from "../shared/queryTemplates";
import type {ApiRecord, QueryTemplateDefinition} from "../shared/types";

type QueryPageProps = {
  t: (key: string) => string;
};

export function QueryPage({t}: QueryPageProps) {
  const [form] = Form.useForm();
  const [selectedKey, setSelectedKey] = useState("");
  const [resultRows, setResultRows] = useState<ApiRecord[]>([]);
  const [resultTitle, setResultTitle] = useState("");
  const predefinedQuery = useQuery({queryKey: ["query-predefined"], queryFn: getPredefinedQueries});
  const templates = useMemo(
    () => Object.entries((predefinedQuery.data ?? {}) as Record<string, QueryTemplateDefinition>),
    [predefinedQuery.data]
  );
  const selectedDefinition = templates.find(([key]) => key === selectedKey)?.[1];
  const executeMutation = useMutation({
    mutationFn: (payload: Parameters<typeof executeAdvancedQuery>[0]) => executeAdvancedQuery(payload),
    onSuccess: (data) => setResultRows(Array.isArray(data) ? data : [])
  });

  useEffect(() => {
    if (!selectedKey && templates.length) setSelectedKey(templates[0][0]);
    if (selectedKey && !templates.some(([key]) => key === selectedKey)) setSelectedKey(templates[0]?.[0] ?? "");
  }, [selectedKey, templates]);

  const selectedUi = QUERY_TEMPLATE_UI[selectedKey];

  return (
    <PageFrame title={t("tab_query")} description={t("query_desc")}>
      <QueryErrorAlert error={predefinedQuery.error ?? executeMutation.error} t={t} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card title={t("query_task_templates")} className="stretch-card">
            <Space direction="vertical" style={{width: "100%"}} size={10}>
              {templates.map(([key, definition]) => {
                const ui = QUERY_TEMPLATE_UI[key];
                return (
                  <Card key={key} size="small" className={selectedKey === key ? "query-template selected" : "query-template"}>
                    <Space direction="vertical" style={{width: "100%"}} size={8}>
                      <Typography.Text strong>{t(ui?.titleKey ?? key)}</Typography.Text>
                      <Typography.Text type="secondary">{t(ui?.descriptionKey ?? "query_template_generic_desc")}</Typography.Text>
                      <Space size={6} wrap>
                        <Tag>{String(definition.parameters?.table ?? "-")}</Tag>
                        <Tag>{`limit=${String(definition.parameters?.limit ?? 100)}`}</Tag>
                      </Space>
                      <Button block type={selectedKey === key ? "primary" : "default"} onClick={() => setSelectedKey(key)}>
                        {t("query_use_template")}
                      </Button>
                    </Space>
                  </Card>
                );
              })}
              {!templates.length ? <Typography.Text type="secondary">{t("no_data")}</Typography.Text> : null}
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card title={t("query_task_runner")} className="stretch-card">
            {selectedKey ? (
              <Space direction="vertical" style={{width: "100%"}} size={12}>
                <Typography.Text strong>{t(selectedUi?.titleKey ?? selectedKey)}</Typography.Text>
                <Typography.Text type="secondary">{t(selectedUi?.descriptionKey ?? "query_template_generic_desc")}</Typography.Text>
                <Form
                  key={selectedKey}
                  form={form}
                  layout="vertical"
                  initialValues={getQueryInitialValues(selectedKey, selectedDefinition)}
                  onFinish={(values) => {
                    const payload = buildQueryPayloadFromTemplate(selectedKey, selectedDefinition, values);
                    setResultTitle(t(selectedUi?.titleKey ?? selectedKey));
                    executeMutation.mutate(payload);
                  }}
                >
                  <Row gutter={12}>
                    {(selectedUi?.fields ?? []).map((field) => (
                      <Col span={12} key={field.name}>
                        <Form.Item name={field.name} label={t(field.labelKey)}>
                          {field.type === "number" ? (
                            <InputNumber min={field.min} max={field.max} style={{width: "100%"}} />
                          ) : field.type === "select" ? (
                            <Select options={field.options ?? []} />
                          ) : (
                            <Input placeholder={field.placeholder} />
                          )}
                        </Form.Item>
                      </Col>
                    ))}
                  </Row>
                  <Space>
                    <Button type="primary" htmlType="submit" loading={executeMutation.isPending}>{t("query_run_task")}</Button>
                    <Button onClick={() => form.resetFields()}>{t("reset")}</Button>
                  </Space>
                </Form>
              </Space>
            ) : <Typography.Text type="secondary">{t("no_data")}</Typography.Text>}
          </Card>
          <Card title={t("query_export")} className="section-card">
            <Form
              layout="inline"
              initialValues={{format: "csv", statuses: [2]}}
              onFinish={(values) => {
                const statuses = Array.isArray(values.statuses)
                  ? values.statuses.map((value: string | number) => String(value)).join(",")
                  : undefined;
                window.open(getChartExportUrl({
                  mode: typeof values.mode === "number" ? values.mode : undefined,
                  creators: values.creators,
                  statuses,
                  format: values.format
                }), "_blank");
              }}
            >
              <Form.Item name="mode" label={t("mode")}><InputNumber min={0} max={9} /></Form.Item>
              <Form.Item name="creators" label={t("query_field_creator")}><Input style={{width: 180}} placeholder="Alice,Bob" /></Form.Item>
              <Form.Item name="statuses" label={t("query_field_status")}>
                <Select mode="multiple" style={{width: 180}} options={[{value: 0, label: "0"}, {value: 1, label: "1"}, {value: 2, label: "2"}]} />
              </Form.Item>
              <Form.Item name="format" label="format">
                <Select style={{width: 120}} options={[{value: "csv", label: "csv"}, {value: "xlsx", label: "xlsx"}]} />
              </Form.Item>
              <Form.Item><Button htmlType="submit">{t("export")}</Button></Form.Item>
            </Form>
          </Card>
        </Col>
      </Row>
      <Card
        title={`${t("query_result")} ${resultTitle ? `(${resultTitle})` : ""}`}
        className="section-card"
        extra={<Button size="small" disabled={!resultRows.length} onClick={() => exportRowsToCsv(resultRows, "query_result.csv")}>{t("query_export_result_csv")}</Button>}
      >
        <Space className="table-summary">
          <Tag>{`${t("query_rows_count")}: ${resultRows.length}`}</Tag>
          <Tag>{`${t("query_columns_count")}: ${Object.keys(resultRows[0] ?? {}).length}`}</Tag>
        </Space>
        <Table<ApiRecord>
          rowKey={(row) => String(Object.values(row).join("|"))}
          dataSource={resultRows}
          pagination={{pageSize: 8}}
          locale={{emptyText: t("no_data")}}
          columns={Object.keys(resultRows[0] ?? {}).map((key) => ({
            title: key,
            dataIndex: key,
            render: (value: unknown) => String(value ?? "")
          }))}
        />
      </Card>
    </PageFrame>
  );
}
