import { Outlet } from 'react-router-dom'
import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined,
  LineChartOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  WalletOutlined,
  AlertOutlined,
  SettingOutlined,
  RobotOutlined,
  FundProjectionScreenOutlined,
  HeatMapOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import HeaderBar from './Header'

const { Sider, Content } = Layout
const { Text } = Typography

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '概览' },
  { key: '/market', icon: <LineChartOutlined />, label: '行情' },
  { key: '/sectors', icon: <HeatMapOutlined />, label: '版块监控' },
  { key: '/funds', icon: <SearchOutlined />, label: '选基' },
  { key: '/signals', icon: <ThunderboltOutlined />, label: '信号' },
  { key: '/portfolio', icon: <WalletOutlined />, label: '持仓' },
  { key: '/alerts', icon: <AlertOutlined />, label: '预警' },
  { key: '/agent', icon: <RobotOutlined />, label: 'AI助手' },
  { key: '/guardian', icon: <SafetyOutlined />, label: '守护 Guardian' },
  { key: '/backtest', icon: <FundProjectionScreenOutlined />, label: '回测' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={200}
        style={{
          background: '#001529',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 10,
        }}
      >
        <div style={{ padding: '16px', textAlign: 'center' }}>
          <Text strong style={{ color: '#fff', fontSize: 18 }}>
            📈 基金助手
          </Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout style={{ marginLeft: 200 }}>
        <HeaderBar />
        <Content style={{ margin: 16, padding: 24, background: '#fff', borderRadius: 8, minHeight: 360 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
