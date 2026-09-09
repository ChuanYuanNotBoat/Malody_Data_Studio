import {useEffect, useState} from "react";
import {useMutation, useQuery} from "@tanstack/react-query";
import {Alert, Button, Card, Input, InputNumber, Row, Select, Space, Switch, Table, Tag, Typography} from "antd";
import {getPlugins, runPlugin} from "../api";
import {PageFrame} from "../shared/PageFrame";
import {QueryErrorAlert} from "../shared/QueryErrorAlert";
import {buildDefaultPayload} from "../shared/formatters";
import type {PluginRow, SchemaProperty} from "../shared/types";

type PluginsPageProps = {
  t: (key: string) => string;
};

export function PluginsPage({t}: PluginsPageProps) {
  const pluginsQuery = useQuery({queryKey: ["plugins"], queryFn: getPlugins});
  const [selectedPluginId, setSelectedPluginId] = useState("");
  const [payload, setPayload] = useState<Record<string, unknown>>({});
  const plugins: PluginRow[] = pluginsQuery.data?.plugins ?? [];
  const selectedPlugin = plugins.find((plugin) => plugin.id === selectedPluginId);
  const runMutation = useMutation({
    mutationFn: ({pluginId, nextPayload}: {pluginId: string; nextPayload: Record<string, unknown>}) =>
      runPlugin(pluginId, {payload: nextPayload}),
    onSuccess: () => undefined
  });

  useEffect(() => {
    if (!selectedPlugin && plugins.length) {
      setSelectedPluginId(plugins[0].id);
    }
  }, [plugins, selectedPlugin]);

  useEffect(() => {
    if (selectedPlugin) setPayload(buildDefaultPayload(selectedPlugin.run_schema));
  }, [selectedPlugin]);

  const updatePayload = (key: string, value: unknown) => setPayload((previous) => ({...previous, [key]: value}));

  return (
    <PageFrame title={t("tab_plugins")} description={t("plugins_desc")}>
      <QueryErrorAlert error={pluginsQuery.error ?? runMutation.error} t={t} />
      <Alert type="info" message={t("plugin_hint_title")} description={t("plugin_hint_desc")} className="section-card" />
      <Row gutter={[16, 16]}>
        {plugins.map((plugin) => (
          <Card key={plugin.id} className="plugin-card" title={plugin.name} extra={<Tag>{plugin.version}</Tag>}>
            <Space direction="vertical" style={{width: "100%"}}>
              <Typography.Text code>{plugin.id}</Typography.Text>
              <Space wrap>{(plugin.capabilities ?? []).map((capability) => <Tag key={capability}>{capability}</Tag>)}</Space>
              <Button type={selectedPluginId === plugin.id ? "primary" : "default"} onClick={() => setSelectedPluginId(plugin.id)}>
                {t("config")}
              </Button>
            </Space>
          </Card>
        ))}
      </Row>
      {selectedPlugin ? (
        <Card title={`${t("plugin_runner")}: ${selectedPlugin.name}`} className="section-card">
          <Space direction="vertical" style={{width: "100%"}} size={12}>
            {Object.entries(selectedPlugin.run_schema?.properties ?? {}).map(([key, schema]) => {
              const definition = schema as SchemaProperty;
              const value = payload[key];
              if (definition.type === "boolean") {
                return (
                  <Space key={key}>
                    <Typography.Text>{key}</Typography.Text>
                    <Switch checked={Boolean(value)} onChange={(next) => updatePayload(key, next)} />
                  </Space>
                );
              }
              if (definition.enum?.length) {
                return (
                  <Space key={key}>
                    <Typography.Text>{key}</Typography.Text>
                    <Select
                      style={{width: 220}}
                      value={String(value ?? "")}
                      options={definition.enum.map((item) => ({value: item, label: item}))}
                      onChange={(next) => updatePayload(key, next)}
                    />
                  </Space>
                );
              }
              if (definition.type === "integer" || definition.type === "number") {
                return (
                  <Space key={key}>
                    <Typography.Text>{key}</Typography.Text>
                    <InputNumber
                      min={definition.minimum}
                      max={definition.maximum}
                      value={typeof value === "number" ? value : undefined}
                      onChange={(next) => updatePayload(key, next ?? undefined)}
                    />
                  </Space>
                );
              }
              return (
                <Space key={key}>
                  <Typography.Text>{key}</Typography.Text>
                  <Input value={String(value ?? "")} onChange={(event) => updatePayload(key, event.target.value)} />
                </Space>
              );
            })}
            <Space>
              <Button
                type="primary"
                loading={runMutation.isPending}
                onClick={() => runMutation.mutate({pluginId: selectedPlugin.id, nextPayload: payload})}
              >
                {t("run")}
              </Button>
              <Button onClick={() => setPayload(buildDefaultPayload(selectedPlugin.run_schema))}>{t("reset")}</Button>
            </Space>
          </Space>
        </Card>
      ) : null}
      {runMutation.data ? (
        <Card title={t("latest_plugin_result")} className="section-card">
          <pre>{JSON.stringify(runMutation.data, null, 2)}</pre>
        </Card>
      ) : null}
    </PageFrame>
  );
}
