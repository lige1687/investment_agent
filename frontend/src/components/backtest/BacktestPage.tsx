import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  InputNumber,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  Input,
} from 'antd'
import { PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { backtestApi } from '@/api/backtest'
import PageContainer from '@/components/layout/PageContainer'
import type { BacktestEvent, BacktestResponse, BacktestTrade, RunPresetPayload } from '@/types/backtest'
import BacktestLinkedReviewChart from './BacktestLinkedReviewChart'

const { Title, Text } = Typography
const { TextArea } = Input

const DEFAULT_STRATEGY_TEXT = `总仓位上限 90%，必须永远保留 10% 现金。
特别看好的标的最高 50%。
总账户最大回撤红线 10%。
弱买点：只观察，不视为正式建仓信号。
首次建仓：只上计划资金的一半。
高波动成长（半导体、人工智能、通信、光模块）：18%~22%。
启动监控点：盈利 15%，移动止盈回撤阈值：8%~10%。`

export default function BacktestPage() {
  const [form] = Form.useForm()
  const [selected, setSelected] = useState<{ trade?: BacktestTrade; event?: BacktestEvent } | null>(null)
  const [result, setResult] = useState<BacktestResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: presets = [], isLoading: loadingPresets } = useQuery({
    queryKey: ['backtest-presets'],
    queryFn: async () => {
      const resp = await backtestApi.getPresets()
      return resp.data.presets
    },
  })

  const presetOptions = useMemo(
    () => presets.map((preset) => ({ label: preset.title, value: preset.preset_id })),
    [presets],
  )

  const runBacktest = async () => {
    const values = await form.validateFields()
    setRunning(true)
    setError(null)
    try {
      const payload: RunPresetPayload = {
        preset_id: values.preset_id,
        start_date: values.range[0].format('YYYY-MM-DD'),
        end_date: values.range[1].format('YYYY-MM-DD'),
        initial_cash: values.initial_cash,
        initial_position_pct: 0, // 默认从空仓开始
        target_position_pct: values.target_position_pct / 100,
        fund_nav_page_size: 100,
        signal_limit: values.signal_limit,
        current_correlated_growth_exposure_pct: 0, // 暂不使用单赛道风险限制
        strategy_text: values.strategy_text,
        use_ai_strategy_compiler: false, // AI策略编译功能开发中，暂时关闭
        test_mode: values.test_mode,
      }
      const resp = await backtestApi.runPreset(payload)
      setResult(resp.data)
    } catch (err: any) {
      const isTimeout = err.code === 'ECONNABORTED' || String(err.message || '').includes('timeout')
      setError(
        isTimeout
          ? '回测请求耗时较长：行情数据、AI策略编译和回放计算还没完成。已把回测接口超时放宽到3分钟，请再跑一次；如果仍超时，可以先关闭AI编译策略。'
          : err.response?.data?.detail || err.message || '回测失败',
      )
    } finally {
      setRunning(false)
    }
  }

  const metrics = result?.metrics

  return (
    <PageContainer
      title="策略回测"
      subtitle="基金净值曲线上的买卖点、账户曲线和每次动作原因"
      size="wide"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => form.resetFields()}>
            重置
          </Button>
          <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runBacktest}>
            跑策略
          </Button>
        </Space>
      }
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          preset_id: 'yifangda_info_industry_communication',
          range: [dayjs('2020-01-01'), dayjs('2022-12-31')],
          initial_cash: 100000,
          target_position_pct: 20,
          signal_limit: 2200,
          strategy_text: DEFAULT_STRATEGY_TEXT,
          use_ai_strategy_compiler: false,
          test_mode: false,
        }}
      >
        <Row gutter={12}>
          <Col xs={24} lg={7}>
            <Form.Item name="preset_id" label="策略预设" rules={[{ required: true }]}>
              <Select loading={loadingPresets} options={presetOptions} />
            </Form.Item>
          </Col>
          <Col xs={24} lg={5}>
            <Form.Item name="range" label="回测区间" rules={[{ required: true }]}>
              <DatePicker.RangePicker style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col xs={12} lg={3}>
            <Form.Item name="initial_cash" label="初始资金">
              <InputNumber min={1000} step={10000} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          {/* 初始仓位已默认为0，不需要用户设置 */}
          {/* <Col xs={12} lg={3}>
            <Form.Item name="initial_position_pct" label="初始仓位%">
              <InputNumber min={0} max={90} style={{ width: '100%' }} />
            </Form.Item>
          </Col> */}
          <Col xs={12} lg={3}>
            <Form.Item name="target_position_pct" label="目标仓位%">
              <InputNumber min={0} max={50} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          {/* 相关暴露功能暂未使用，后续需要时再开启 */}
          {/* <Col xs={12} lg={3}>
            <Form.Item name="current_correlated_growth_exposure_pct" label="相关暴露%">
              <InputNumber min={0} max={90} style={{ width: '100%' }} />
            </Form.Item>
          </Col> */}
          <Col xs={12} lg={3}>
            <Form.Item name="signal_limit" label="K线数量">
              <InputNumber min={200} max={3000} step={100} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          {/* AI策略编译功能开发中，暂时关闭 */}
          {/* <Col xs={12} lg={3}>
            <Form.Item name="use_ai_strategy_compiler" label="AI编译策略" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </Col> */}
          <Col xs={12} lg={3}>
            <Form.Item name="test_mode" label="测试模式" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="strategy_text" label="本次策略文本">
              <TextArea
                autoSize={{ minRows: 5, maxRows: 12 }}
                placeholder="把你的交易系统规则粘贴到这里。本次回测会先解析这段文本，再覆盖预设参数。"
              />
            </Form.Item>
          </Col>
        </Row>
      </Form>

      {error ? <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} /> : null}

      {metrics ? (
        <>
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            <Col xs={12} md={6}>
              <Statistic title="总收益" value={metrics.total_return_pct} precision={2} suffix="%" valueStyle={metricColor(metrics.total_return_pct)} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="年化收益" value={metrics.annual_return_pct} precision={2} suffix="%" valueStyle={metricColor(metrics.annual_return_pct)} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="最大回撤" value={metrics.max_drawdown_pct} precision={2} suffix="%" valueStyle={{ color: '#3f8600' }} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="交易次数" value={metrics.trade_count} suffix="笔" />
            </Col>
          </Row>
          {result?.strategy_profile ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="本次策略文本解析结果"
              description={
                <Space direction="vertical" size={6}>
                  <Space wrap>
                    {result.strategy_profile.recognized_rules.length
                      ? result.strategy_profile.recognized_rules.map((rule) => <Tag key={rule} color="blue">{rule}</Tag>)
                      : <Tag>未识别到可执行覆盖项</Tag>}
                  </Space>
                  {result.strategy_profile.notes?.map((note) => (
                    <Text type="secondary" key={note}>{note}</Text>
                  ))}
                </Space>
              }
            />
          ) : null}
        </>
      ) : null}

      {result ? (
        <>
          <BacktestLinkedReviewChart
            equityCurve={result.equity_curve}
            signalBars={result.signal_bars}
            trades={result.trades}
            events={result.events}
            onSelectTrade={(trade, event) => setSelected({ trade, event })}
            onSelectEvent={(event) => setSelected({ event })}
          />
          <Table
            size="small"
            rowKey={(record) => `${record.date}-${record.action}-${record.shares}`}
            dataSource={result.trades}
            pagination={{ pageSize: 8 }}
            columns={[
              { title: '日期', dataIndex: 'date', width: 110 },
              {
                title: '动作',
                dataIndex: 'action',
                width: 80,
                render: (action: string) => <Tag color={action === 'buy' ? 'red' : 'green'}>{action === 'buy' ? '买入' : '卖出'}</Tag>,
              },
              { title: '净值', dataIndex: 'nav', width: 90, render: (value: number) => value.toFixed(3) },
              { title: '金额', dataIndex: 'cash_delta', width: 120, render: (value: number) => Math.abs(value).toFixed(2) },
              { title: '份额', dataIndex: 'shares', width: 120, render: (value: number) => value.toFixed(2) },
              {
                title: '批次',
                dataIndex: 'batch_type',
                width: 110,
                render: (value?: string) => value ? <Tag>{batchTypeLabel(value)}</Tag> : '-',
              },
              {
                title: '批次收益',
                dataIndex: 'batch_return_pct',
                width: 110,
                render: (value?: number) => value == null ? '-' : (
                  <Tag color={value >= 0 ? 'red' : 'green'}>{value.toFixed(2)}%</Tag>
                ),
              },
              { title: '原因', dataIndex: 'reason', ellipsis: true },
              {
                title: '',
                width: 80,
                render: (_, record) => (
                  <Button size="small" onClick={() => setSelected({ trade: record, event: findEvent(record, result.events) })}>
                    详情
                  </Button>
                ),
              },
            ]}
          />
        </>
      ) : (
        <Alert
          type="info"
          showIcon
          message="选择区间后点击跑策略，买卖点会标在基金净值曲线上。"
        />
      )}

      <Drawer
        title={selected ? selected.trade
          ? `${selected.trade.date} ${selected.trade.action === 'buy' ? '买入' : '卖出'}原因`
          : `${selected.event?.date || ''} 系统判断`
          : ''}
        open={!!selected}
        width={560}
        onClose={() => setSelected(null)}
      >
        {selected ? <TradeDetail trade={selected.trade} event={selected.event} /> : null}
      </Drawer>
    </PageContainer>
  )
}

function TradeDetail({ trade, event }: { trade?: BacktestTrade; event?: BacktestEvent }) {
  const buySignal = event?.details.buy_signal
  const triggerSignals = event?.details.trigger_signals || []
  const report = event?.analysis_report
  const skillRoute = event?.skill_route
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {trade ? (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="动作">{trade.action === 'buy' ? '买入' : '卖出'}</Descriptions.Item>
          <Descriptions.Item label="基金净值">{trade.nav.toFixed(4)}</Descriptions.Item>
          <Descriptions.Item label="成交金额">{Math.abs(trade.cash_delta).toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="份额">{trade.shares.toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="批次">{trade.batch_type ? batchTypeLabel(trade.batch_type) : '-'}</Descriptions.Item>
          <Descriptions.Item label="批次成本净值">{trade.batch_cost_nav?.toFixed(4) ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="批次当前收益">
            {trade.batch_return_pct == null ? '-' : `${trade.batch_return_pct.toFixed(2)}%`}
          </Descriptions.Item>
          <Descriptions.Item label="批次最大浮盈">
            {trade.batch_peak_return_pct == null ? '-' : `${trade.batch_peak_return_pct.toFixed(2)}%`}
          </Descriptions.Item>
          <Descriptions.Item label="费用">{trade.fee.toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="执行原因">{trade.reason}</Descriptions.Item>
        </Descriptions>
      ) : event ? (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="动作">系统判断</Descriptions.Item>
          <Descriptions.Item label="判断结果">{event.decision.action === 'observe' ? '观察/不交易' : event.decision.action}</Descriptions.Item>
          <Descriptions.Item label="不交易原因">{event.audit?.why_no_trade || event.decision.reason}</Descriptions.Item>
          <Descriptions.Item label="最终决定模块">{event.audit?.final_decider || '-'}</Descriptions.Item>
        </Descriptions>
      ) : null}
      {event ? (
        <Alert type="info" showIcon message="触发事件" description={event.reason} />
      ) : null}
      {triggerSignals.length ? <TriggerSignalTable signals={triggerSignals} /> : null}
      {skillRoute ? <BatchSkillRouteView route={skillRoute} /> : null}
      {report ? <AnalysisReportView report={report} /> : null}
      {!report && buySignal ? (
        <div>
          <Title level={5}>五维买入信号</Title>
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag color={buySignal.signal_level === 'strong_buy' ? 'red' : 'orange'}>{buySignal.signal_level}</Tag>
            <Tag>{buySignal.passed_count}/5 项通过</Tag>
            <Tag color={buySignal.account_allowed ? 'green' : 'red'}>{buySignal.account_allowed ? '账户允许' : '账户禁止'}</Tag>
          </Space>
          <Table
            size="small"
            rowKey="name"
            pagination={false}
            dataSource={buySignal.dimensions}
            columns={[
              {
                title: '维度',
                dataIndex: 'name',
                width: 120,
              },
              {
                title: '结果',
                dataIndex: 'passed',
                width: 80,
                render: (passed: boolean) => <Tag color={passed ? 'green' : 'default'}>{passed ? '通过' : '未过'}</Tag>,
              },
              { title: '判断', dataIndex: 'reason' },
            ]}
          />
        </div>
      ) : null}
      {event && !buySignal && !report ? (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="事件类型">{event.event_type}</Descriptions.Item>
          <Descriptions.Item label="系统判断">{event.decision.reason}</Descriptions.Item>
          <Descriptions.Item label="观察天数">{event.decision.observe_days}</Descriptions.Item>
        </Descriptions>
      ) : null}
    </Space>
  )
}

function BatchSkillRouteView({ route }: { route: NonNullable<BacktestEvent['skill_route']> }) {
  return (
    <div>
      <Title level={5}>批次交易系统 Skill 调度</Title>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="系统">{route.system_name}</Descriptions.Item>
        <Descriptions.Item label="意图">{routeIntentLabel(route.classified_intent)}</Descriptions.Item>
        <Descriptions.Item label="最高优先级">
          <Tag color={priorityColor(route.highest_priority)}>{route.highest_priority}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="允许直接结论">
          <Tag color={route.direct_answer_allowed ? 'green' : 'red'}>
            {route.direct_answer_allowed ? '允许' : '禁止'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="优先级说明">{route.priority_note}</Descriptions.Item>
      </Descriptions>
      <Space wrap style={{ marginTop: 8 }}>
        {route.required_skill_order.map((skill, index) => (
          <Tag key={`${skill}-${index}`} color={index === 0 ? 'default' : 'blue'}>
            {index + 1}. {skill}
          </Tag>
        ))}
      </Space>
      {route.immediate_vetoes.length ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message="前置否决"
          description={
            <Space direction="vertical" size={4}>
              {route.immediate_vetoes.map((veto) => (
                <Text key={`${veto.rule}-${veto.reason}`}>
                  {veto.blocking ? '阻断' : '提示'}：{veto.rule}，{veto.reason}
                </Text>
              ))}
            </Space>
          }
        />
      ) : null}
    </div>
  )
}

function TriggerSignalTable({ signals }: { signals: NonNullable<BacktestEvent['details']['trigger_signals']> }) {
  return (
    <div>
      <Title level={5}>机械触发信号</Title>
      <Table
        size="small"
        rowKey={(record) => `${record.priority}-${record.trigger_family}-${record.trigger_type}`}
        pagination={false}
        dataSource={signals}
        columns={[
          {
            title: '优先级',
            dataIndex: 'priority',
            width: 80,
            render: (priority: string) => <Tag color={priorityColor(priority)}>{priority}</Tag>,
          },
          {
            title: '类型',
            dataIndex: 'trigger_family',
            width: 120,
            render: (family: string) => triggerFamilyLabel(family),
          },
          { title: '触发原因', dataIndex: 'reason' },
        ]}
      />
    </div>
  )
}

function AnalysisReportView({ report }: { report: NonNullable<BacktestEvent['analysis_report']> }) {
  const signalRows = Object.entries(report.buy_signal_checks).map(([name, item]) => ({
    name,
    ...item,
  }))

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <div>
        <Title level={5}>当前结论</Title>
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="当前信号等级">
            <Tag color={signalColor(report.current_conclusion.signal_level)}>
              {report.current_conclusion.signal_level}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="当前建议动作">{report.current_conclusion.suggested_action}</Descriptions.Item>
          <Descriptions.Item label="是否符合账户风控">
            <Tag color={report.current_conclusion.risk_control_passed ? 'green' : 'red'}>
              {report.current_conclusion.risk_control_passed ? '是' : '否'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="系统判断">{report.current_conclusion.decision_reason}</Descriptions.Item>
        </Descriptions>
      </div>

      <div>
        <Title level={5}>账户检查</Title>
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="当前总仓位">{report.account_check.current_total_position_pct.toFixed(2)}%</Descriptions.Item>
          <Descriptions.Item label="当前总仓位是否安全">
            {report.account_check.current_total_position_safe ? '安全' : '越线'}
          </Descriptions.Item>
          <Descriptions.Item label="当前赛道暴露是否过高">
            {report.account_check.current_sector_exposure_too_high ? '过高' : '未过高'}
          </Descriptions.Item>
          <Descriptions.Item label="是否会突破限制">
            {report.account_check.would_break_single_or_sector_limit ? '会' : '不会'}
          </Descriptions.Item>
        </Descriptions>
        <Space wrap style={{ marginTop: 8 }}>
          {report.account_check.reasons.map((reason) => <Tag key={reason}>{reason}</Tag>)}
        </Space>
      </div>

      <div>
        <Title level={5}>五维买入信号判断</Title>
        <Table
          size="small"
          rowKey="name"
          pagination={false}
          dataSource={signalRows}
          columns={[
            { title: '维度', dataIndex: 'name', width: 120 },
            {
              title: '结果',
              dataIndex: 'passed',
              width: 80,
              render: (passed: boolean) => <Tag color={passed ? 'green' : 'default'}>{passed ? '通过' : '未过'}</Tag>,
            },
            { title: '判断', dataIndex: 'reason' },
          ]}
        />
      </div>

      <div>
        <Title level={5}>触发条件</Title>
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="本次触发">{report.trigger_conditions.event}</Descriptions.Item>
          <Descriptions.Item label="执行判断">{report.trigger_conditions.decision}</Descriptions.Item>
          <Descriptions.Item label="还差条件">
            <Space wrap>
              {report.trigger_conditions.missing_conditions.map((item) => <Tag key={item}>{item}</Tag>)}
            </Space>
          </Descriptions.Item>
          {report.trigger_conditions.upgrade_conditions.length ? (
            <Descriptions.Item label="升级条件">
              <Space wrap>
                {report.trigger_conditions.upgrade_conditions.map((item) => <Tag key={item} color="blue">{item}</Tag>)}
              </Space>
            </Descriptions.Item>
          ) : null}
        </Descriptions>
      </div>

      <div>
        <Title level={5}>风险提示</Title>
        <Space direction="vertical" size={6}>
          {report.risk_warnings.map((warning, index) => (
            <Text key={warning}>{index + 1}. {warning}</Text>
          ))}
        </Space>
      </div>

      <Alert type="warning" showIcon message="一句话执行建议" description={report.one_sentence} />
    </Space>
  )
}

function findEvent(trade: BacktestTrade, events: BacktestEvent[]) {
  return [...events]
    .reverse()
    .find((event) =>
      event.event_type === trade.event_type
      && event.date <= trade.date
      && event.decision.action === trade.action
    )
}

function metricColor(value: number) {
  return { color: value >= 0 ? '#cf1322' : '#3f8600' }
}

function signalColor(signalLevel: string) {
  if (signalLevel === '强买点') return 'red'
  if (signalLevel === '中买点') return 'orange'
  if (signalLevel === '弱买点') return 'gold'
  return 'default'
}

function priorityColor(priority: string) {
  if (priority === 'P0') return 'red'
  if (priority === 'P1') return 'volcano'
  if (priority === 'P2') return 'orange'
  if (priority === 'P3') return 'blue'
  return 'default'
}

function triggerFamilyLabel(family: string) {
  const labels: Record<string, string> = {
    account_risk: '账户风控',
    stop_loss: '止损',
    take_profit: '止盈',
    buy_observation: '买入观察',
    add_position: '补仓',
    market_regime: '市场环境',
    active_fund_strength: '基金强弱',
  }
  return labels[family] || family
}

function routeIntentLabel(intent: string) {
  const labels: Record<string, string> = {
    account_risk_control: '账户风控',
    stop_loss_or_breakdown: '止损/破位',
    take_profit: '止盈',
    buy_or_add: '买入/补仓',
    sell_execution: '卖出执行',
    observe_or_hold: '观察/持有',
  }
  return labels[intent] || intent
}

function batchTypeLabel(batchType: string) {
  const labels: Record<string, string> = {
    core: '核心仓',
    confirmation: '确认仓',
    high_position: '高位/灵活仓',
    trial: '试错仓',
  }
  return labels[batchType] || batchType
}
