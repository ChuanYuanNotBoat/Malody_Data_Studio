import {Alert, Space, Typography} from "antd";
import {parseApiError} from "./formatters";

type QueryErrorAlertProps = {
  error?: unknown;
  t: (key: string) => string;
};

export function QueryErrorAlert({error, t}: QueryErrorAlertProps) {
  if (!error) return null;
  const parsed = parseApiError(error, t);
  return (
    <Alert
      type="error"
      showIcon
      message={parsed.summary}
      description={
        parsed.detail ? (
          <Space direction="vertical" size={4}>
            <details>
              <summary>{t("error_details")}</summary>
              <Typography.Text type="secondary">{parsed.detail}</Typography.Text>
            </details>
          </Space>
        ) : undefined
      }
      style={{marginBottom: 16}}
    />
  );
}
