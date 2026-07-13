import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Typography, Card, Space, Button, Tag, Image, Statistic, Row, Col,
  Spin, message, Alert, Descriptions, Progress,
} from 'antd'
import {
  ScanOutlined, ReloadOutlined, LinkOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SyncOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { yangjibaoApi } from '@/api/yangjibao'
import FeishuConfigCard from '@/components/feishu/FeishuConfigCard'
import type { YangjibaoPortfolio, SyncResult } from '@/types/yangjibao'
import { formatNumber } from '@/utils/format'

const { Title, Text } = Typography

export default function SettingsPage() {
  const [qrImage, setQrImage] = useState<string | null>(null)
  const [qrStatus, setQrStatus] = useState<string>('')
  const [polling, setPolling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  // ── Status ──
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ['yangjibao-status'],
    queryFn: async () => {
      const resp = await yangjibaoApi.getStatus()
      return resp.data
    },
    refetchInterval: 30_000,
  })

  // ── Portfolio ──
  const { data: portfolio, refetch: refetchPortfolio } = useQuery({
    queryKey: ['yangjibao-portfolio'],
    queryFn: async () => {
      const resp = await yangjibaoApi.getPortfolio()
      return resp.data
    },
    enabled: !!status?.connected,
  })

  // ── Start QR Login ──
  const startLogin = useCallback(async () => {
    try {
      console.log('[YJB] Starting QR login...')
      const resp = await yangjibaoApi.startLogin()
      const data = resp.data
      console.log('[YJB] Got QR:', data.qr_id?.substring(0, 20), 'image len:', data.qr_image?.length)
      setQrImage(data.qr_image)
      setQrStatus('pending')
      setPolling(true)

      // Start polling every 2s
      pollRef.current = setInterval(async () => {
        try {
          const checkResp = await yangjibaoApi.checkLogin()
          const checkData = checkResp.data
          setQrStatus(checkData.status)

          if (checkData.status === 'confirmed') {
            clearInterval(pollRef.current)
            setPolling(false)
            message.success('养基宝连接成功！')
            refetchStatus()
            refetchPortfolio()
          } else if (checkData.status === 'expired' || checkData.status === 'failed') {
            clearInterval(pollRef.current)
            setPolling(false)
            message.warning(`登录${checkData.status === 'expired' ? '已过期' : '失败'}，请重试`)
          }
        } catch {
          // ignore poll errors
        }
      }, 2000)

      // Timeout after 5 minutes
      setTimeout(() => {
        if (pollRef.current) {
          clearInterval(pollRef.current)
          setPolling(false)
        }
      }, 300_000)
    } catch (e: any) {
      message.error('启动扫码失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'))
    }
  }, [refetchStatus, refetchPortfolio])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // ── Sync ──
  const syncMutation = useMutation({
    mutationFn: () => yangjibaoApi.syncPortfolio(),
    onSuccess: (resp) => {
      const data: SyncResult = resp.data
      if (data.success) {
        message.success(`同步成功！${data.positionsCount} 个持仓, ${data.totalValue > 0 ? `总市值 ¥${formatNumber(data.totalValue, 0)}` : ''}`)
        refetchPortfolio()
      } else if (data.error === 'not_authenticated') {
        message.warning('未连接养基宝，请先扫码登录')
      } else {
        message.error('同步失败: ' + (data.error || '未知错误'))
      }
    },
    onError: (e: any) => {
      message.error('同步请求失败: ' + (e?.response?.data?.detail || e?.message))
    },
  })

  return (
    <div>
      <Title level={4}>系统设置</Title>
      <Space direction="vertical" style={{ width: '100%' }} size={16}>

        {/* ── 养基宝连接 ── */}
        <Card
          title={
            <Space>
              <LinkOutlined /> 养基宝连接
              {status?.connected
                ? <Tag color="green" icon={<CheckCircleOutlined />}>已连接</Tag>
                : <Tag color="default" icon={<CloseCircleOutlined />}>未连接</Tag>
              }
            </Space>
          }
          extra={
            <Space>
              {status?.connected && (
                <Button
                  icon={<SyncOutlined />}
                  onClick={() => syncMutation.mutate()}
                  loading={syncMutation.isPending}
                >
                  同步持仓
                </Button>
              )}
              <Button icon={<ReloadOutlined />} onClick={() => refetchStatus()}>刷新状态</Button>
            </Space>
          }
        >
          {!status?.connected ? (
            <div style={{ textAlign: 'center', padding: 20 }}>
              <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
                扫码登录养基宝，自动同步持仓数据
              </Text>

              {!qrImage ? (
                <Button
                  type="primary"
                  size="large"
                  icon={<ScanOutlined />}
                  onClick={startLogin}
                >
                  获取登录二维码
                </Button>
              ) : (
                <div>
                  <Image
                    src={`data:image/png;base64,${qrImage}`}
                    alt="登录二维码"
                    width={200}
                    height={200}
                    style={{ border: '2px solid #f0f0f0', borderRadius: 8 }}
                    preview={false}
                  />
                  <div style={{ marginTop: 12 }}>
                    {polling && qrStatus === 'pending' && (
                      <Space>
                        <Spin size="small" />
                        <Text type="secondary">等待扫码...</Text>
                      </Space>
                    )}
                    {qrStatus === 'scanned' && (
                      <Alert message="已扫描，请在手机上确认登录" type="info" showIcon style={{ maxWidth: 300, margin: '0 auto' }} />
                    )}
                    {qrStatus === 'expired' && (
                      <Alert message="二维码已过期" type="warning" showIcon style={{ maxWidth: 300, margin: '0 auto' }}
                        action={<Button size="small" onClick={startLogin}>重新获取</Button>}
                      />
                    )}
                    {qrStatus === 'failed' && (
                      <Alert message="登录失败" type="error" showIcon style={{ maxWidth: 300, margin: '0 auto' }}
                        action={<Button size="small" onClick={startLogin}>重试</Button>}
                      />
                    )}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 16 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  首次使用：点击「获取登录二维码」→ 打开养基宝APP扫码 → 确认授权
                </Text>
              </div>
            </div>
          ) : (
            /* Connected - show portfolio summary */
            portfolio ? (
              <div>
                <Row gutter={[16, 16]}>
                  <Col span={6}>
                    <Statistic title="总市值" value={portfolio.totalValue} precision={2} prefix="¥" />
                  </Col>
                  <Col span={6}>
                    <Statistic title="总成本" value={portfolio.totalCost} precision={2} prefix="¥" />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="累计盈亏"
                      value={portfolio.totalPnl}
                      precision={2}
                      prefix="¥"
                      valueStyle={{ color: portfolio.totalPnl >= 0 ? '#cf1322' : '#3f8600' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="收益率"
                      value={portfolio.totalPnlPct}
                      precision={2}
                      suffix="%"
                      valueStyle={{ color: portfolio.totalPnlPct >= 0 ? '#cf1322' : '#3f8600' }}
                    />
                  </Col>
                </Row>

                {portfolio.positions.length > 0 && (
                  <Descriptions bordered size="small" style={{ marginTop: 16 }} column={1}>
                    {portfolio.positions.slice(0, 10).map((pos) => (
                      <Descriptions.Item key={pos.symbol} label={
                        <Space>
                          <Tag color={pos.type === 'etf' ? 'blue' : 'purple'}>{pos.type.toUpperCase()}</Tag>
                          {pos.symbol}
                        </Space>
                      }>
                        <Space split={<Text type="secondary">|</Text>}>
                          <Text>份额 {formatNumber(pos.shares, 2)}</Text>
                          <Text>成本 ¥{formatNumber(pos.avgCost, 3)}</Text>
                          <Text>现价 ¥{formatNumber(pos.currentPrice, 3)}</Text>
                          <Text strong style={{ color: (pos.unrealizedPnl || 0) >= 0 ? '#cf1322' : '#3f8600' }}>
                            {Number.isFinite(pos.unrealizedPnlPct)
                              ? `${(pos.unrealizedPnlPct ?? 0) >= 0 ? '+' : ''}${formatNumber(pos.unrealizedPnlPct, 2)}%`
                              : '--'}
                          </Text>
                        </Space>
                      </Descriptions.Item>
                    ))}
                  </Descriptions>
                )}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 20 }}>
                <Spin />
                <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>加载持仓数据...</Text>
              </div>
            )
          )}
        </Card>

        {/* ── 飞书推送配置 ── */}
        <FeishuConfigCard />

        {/* ── 定时任务 (placeholder) ── */}
        <Card title="定时任务">
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            任务列表 + 启用/禁用 + 手动触发（待实现）
          </div>
        </Card>

      </Space>
    </div>
  )
}
