import Layout from "./app/Layout.jsx";
import { useRoute } from "./app/router";
import BacktestPage from "./features/backtest/BacktestPage.jsx";
import QuotesPage from "./features/market/QuotesPage.jsx";
import OverviewPage from "./features/signals/OverviewPage.jsx";
import StatusPage from "./features/status/StatusPage.jsx";
import StockPage from "./features/stock/StockPage.jsx";

export default function App() {
  const { page, param } = useRoute();
  return (
    <Layout page={page}>
      {page === "overview" && <OverviewPage />}
      {page === "quotes" && <QuotesPage />}
      {page === "stock" && <StockPage symbol={param} />}
      {page === "backtest" && <BacktestPage />}
      {page === "status" && <StatusPage />}
    </Layout>
  );
}
