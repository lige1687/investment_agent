import { Alert } from 'antd'

export default function DemoDataBanner() {
  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 100, marginBottom: 12 }}>
      <Alert
        role="alert"
        banner
        showIcon
        type="warning"
        message="演示数据，不可用于真实交易"
      />
    </div>
  )
}

