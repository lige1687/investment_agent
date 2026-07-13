# 行情数据运行模式

系统通过后端环境变量 `MARKET_DATA_MODE` 控制行情可信边界：

- `live`（默认）：只使用真实数据源。数据源失败、关键字段缺失或数值异常时，接口返回 `unavailable` / `invalid`，页面显示原因并停止把该数据用于交易判断；不会自动填充模拟行情。
- `demo`：允许使用本地生成数据。接口固定返回 `mode=demo`、`source=demo/mock`、`is_mock=true`，页面持续显示“演示数据，不可用于真实交易”。

行情响应都包含 `meta`：数据来源、获取时间、模式、状态、是否过期、是否模拟和安全提示。`change` 表示涨跌点数，`change_pct` 表示涨跌幅，两者不能互相替代。

本地切换示例：

```bash
MARKET_DATA_MODE=live uvicorn app.main:app --reload
MARKET_DATA_MODE=demo uvicorn app.main:app --reload
```

切换模式后需要重启后端。真实数据不可用时页面变为不可用状态是预期行为，不应通过请求参数绕过。

