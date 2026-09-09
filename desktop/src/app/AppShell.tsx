import type {ReactNode} from "react";
import {Layout, Menu, Select, Space, Tag, Typography} from "antd";
import type {AppLocale} from "../i18n";
import {NAV_ITEMS, type PageKey} from "./navigation";

const {Header, Sider, Content} = Layout;

type AppShellProps = {
  activePage: PageKey;
  locale: AppLocale;
  onLocaleChange: (locale: AppLocale) => void;
  onPageChange: (page: PageKey) => void;
  t: (key: string) => string;
  children: ReactNode;
};

export function AppShell({activePage, locale, onLocaleChange, onPageChange, t, children}: AppShellProps) {
  return (
    <Layout className="app-shell">
      <Sider className="app-sider" breakpoint="lg" collapsedWidth="0" theme="light">
        <div className="brand-block">
          <div className="brand-mark">MDS</div>
          <div>
            <Typography.Title level={4} className="brand-title">
              Malody Data Studio
            </Typography.Title>
            <Typography.Text type="secondary">{t("brand_subtitle")}</Typography.Text>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activePage]}
          items={NAV_ITEMS.map((item) => ({key: item.key, label: t(item.labelKey)}))}
          onClick={({key}) => onPageChange(key as PageKey)}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-title-group">
            <Typography.Title level={3} className="app-title">
              {t("app_title")}
            </Typography.Title>
            <Tag color="blue">{t("local_console")}</Tag>
          </div>
          <Space>
            <Typography.Text className="header-label">{t("lang_label")}</Typography.Text>
            <Select
              aria-label={t("lang_label")}
              value={locale}
              style={{width: 120}}
              onChange={(value: AppLocale) => onLocaleChange(value)}
              options={[
                {value: "zh-CN", label: "中文"},
                {value: "en-US", label: "English"}
              ]}
            />
          </Space>
        </Header>
        <Content className="app-content">{children}</Content>
      </Layout>
    </Layout>
  );
}
