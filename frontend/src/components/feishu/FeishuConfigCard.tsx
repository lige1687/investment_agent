import { useState, useEffect } from 'react'
import { Card, Input, Button, Switch, Space, message, Typography, Tag } from 'antd'
import { SendOutlined, LinkOutlined, CheckCircleOutlined } from '@ant-design/icons'
import apiClient from '@/api/client'

const { Text } = Typography

export default function FeishuConfigCard() {
  const [webhookUrl, setWebhookUrl] = useState('')
  const [testing, setTesting] = useState(false)
  const [status, setStatus] = useState<{ configured: boolean; webhook_hint?: string } | null>(null)

  const loadConfig = async () => {
    try {
      const resp = await apiClient.get('/feishu/config')
      setStatus(resp.data)
      setWebhookUrl('')
    } catch { /* ignore */ }
  }

  // Load on mount
  useEffect(() => { loadConfig() }, [])

  const saveConfig = async () => {
    try {
      await apiClient.put('/feishu/config', {
        webhook_url: webhookUrl,
        notify_market_open: true,
        notify_market_close: true,
        notify_alerts: true,
        notify_signals: true,
        notify_pnl: true,
      })
      message.success('飞书配置已保存')
      loadConfig()
    } catch (e: any) {
      message.error('保存失败: ' + (e?.message || ''))
    }
  }

  const testPush = async () => {
    setTesting(true)
    try {
      const resp = await apiClient.post('/feishu/test')
      if (resp.data.ok) {
        message.success('测试消息已发送！请查看飞书群')
      } else {
        message.error(resp.data.error || '发送失败')
      }
    } catch (e: any) {
      message.error('测试失败: ' + (e?.response?.data?.detail || e?.message))
    } finally {
      setTesting(false)
    }
  }

  return (
    <Card
      title={<Space><LinkOutlined /> 飞书推送配置 {status?.configured && <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>}</Space>}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <div>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>Webhook URL</Text>
          <Input
            placeholder={status?.configured ? '已配置，留空则不修改' : '请输入新的飞书 Webhook URL'}
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
          />
          <Text type="secondary" style={{ fontSize: 11 }}>
            {status?.webhook_hint
              ? `当前配置：${status.webhook_hint}`
              : '飞书群 → 群设置 → 机器人 → 添加自定义机器人 → 复制 Webhook 地址'}
          </Text>
        </div>

        <Space style={{ width: '100%' }}>
          <Text strong>每日推送：</Text>
          <Text type="secondary">📈 9:25 开盘速报 + 📉 15:05 收盘总结 + 💼 15:30 持仓日报 + 🔄 20:00 养基宝同步</Text>
        </Space>

        <Space style={{ width: '100%' }}>
          <Text strong>实时预警：</Text>
          <Text type="secondary">持仓涨跌超 ±3% 立即推送</Text>
        </Space>

        <Space>
          <Button type="primary" onClick={saveConfig}>保存配置</Button>
          <Button icon={<SendOutlined />} onClick={testPush} loading={testing}>
            发送测试消息
          </Button>
        </Space>
      </Space>
    </Card>
  )
}
