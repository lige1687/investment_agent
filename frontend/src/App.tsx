import { Routes, Route } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import DashboardPage from './components/dashboard/DashboardPage'
import MarketPage from './components/market/MarketPage'
import FundSearchPage from './components/fund/FundSearchPage'
import SignalPage from './components/signal/SignalPage'
import PortfolioPage from './components/portfolio/PortfolioPage'
import AlertPage from './components/alerts/AlertPage'
import SettingsPage from './components/settings/SettingsPage'
import AgentChatPage from './components/agent/AgentChatPage'
import GuardianDashboardPage from './components/guardian/GuardianDashboardPage'
import BacktestPage from './components/backtest/BacktestPage'
import SectorRankingBoard from './components/sector/SectorRankingBoard'
import TradingRoomPage from './components/trading-room/TradingRoomPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/market" element={<MarketPage />} />
        <Route path="/sectors" element={<SectorRankingBoard />} />
        <Route path="/funds" element={<FundSearchPage />} />
        <Route path="/signals" element={<SignalPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/alerts" element={<AlertPage />} />
        <Route path="/agent" element={<AgentChatPage />} />
        <Route path="/trading-room" element={<TradingRoomPage />} />
        <Route path="/guardian" element={<GuardianDashboardPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
