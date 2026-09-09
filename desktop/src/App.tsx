import {useCallback, useEffect, useState} from "react";
import {ConfigProvider} from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import {AppShell} from "./app/AppShell";
import {NAV_ITEMS, type PageKey} from "./app/navigation";
import {AnalyticsPage} from "./pages/AnalyticsPage";
import {CrawlerPage} from "./pages/CrawlerPage";
import {DatabasePage} from "./pages/DatabasePage";
import {OverviewPage} from "./pages/OverviewPage";
import {PluginsPage} from "./pages/PluginsPage";
import {QualityPage} from "./pages/QualityPage";
import {QueryPage} from "./pages/QueryPage";
import {TaskCenterPage} from "./pages/TaskCenterPage";
import {dictionaries, type AppLocale} from "./i18n";

export {buildCrawlerRunParams} from "./shared/crawler";

function readLocale(): AppLocale {
  if (typeof localStorage === "undefined") return "zh-CN";
  const value = localStorage.getItem("app.locale");
  return value === "en-US" || value === "zh-CN" ? value : "zh-CN";
}

function App() {
  const [activePage, setActivePage] = useState<PageKey>(NAV_ITEMS[0].key);
  const [locale, setLocale] = useState<AppLocale>(readLocale);
  const t = useCallback((key: string) => dictionaries[locale][key] ?? key, [locale]);

  useEffect(() => {
    localStorage.setItem("app.locale", locale);
  }, [locale]);

  const page = (() => {
    switch (activePage) {
      case "analytics": return <AnalyticsPage t={t} />;
      case "tasks": return <TaskCenterPage t={t} />;
      case "crawler": return <CrawlerPage t={t} />;
      case "quality": return <QualityPage t={t} />;
      case "db": return <DatabasePage t={t} />;
      case "plugins": return <PluginsPage t={t} />;
      case "query": return <QueryPage t={t} />;
      case "overview":
      default:
        return <OverviewPage t={t} />;
    }
  })();

  return (
    <ConfigProvider locale={locale === "zh-CN" ? zhCN : enUS}>
      <AppShell
        activePage={activePage}
        locale={locale}
        onLocaleChange={setLocale}
        onPageChange={setActivePage}
        t={t}
      >
        {page}
      </AppShell>
    </ConfigProvider>
  );
}

export default App;
