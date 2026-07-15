import { useMemo } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Typography } from 'antd'
import { RiseOutlined } from '@ant-design/icons'
import MainHeader from './MainHeader'
import { NAV_GROUPS } from './navConfig'

const { Sider, Content } = Layout
const { Text } = Typography

const menuItems = NAV_GROUPS.map(group => ({
  key: group.key,
  label: group.label,
  type: 'group' as const,
  children: group.items.map(item => ({
    key: item.key,
    icon: item.icon,
    label: item.label,
  })),
}))

const SIDER_WIDTH = 208

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  const openKeys = useMemo(() => NAV_GROUPS.map(g => g.key), [])

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={SIDER_WIDTH}
        style={{
          background: '#001529',
          position: 'fixed',
          insetInlineStart: 0,
          top: 0,
          bottom: 0,
          zIndex: 10,
          overflow: 'auto',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '20px 20px 16px',
            color: '#fff',
          }}
        >
          <RiseOutlined style={{ fontSize: 20, color: '#69b1ff' }} />
          <Text strong style={{ color: '#fff', fontSize: 16 }}>
            基金决策工作台
          </Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={openKeys}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>
      <Layout style={{ marginInlineStart: SIDER_WIDTH, background: '#f5f7fa' }}>
        <MainHeader />
        <Content style={{ padding: '20px 24px 40px' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
