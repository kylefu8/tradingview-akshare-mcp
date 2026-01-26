# TradingView AKShare MCP Server

A股市场技术分析 MCP (Model Context Protocol) Server，基于 AKShare 数据源。

## 功能特性

- 📊 **个股技术分析**: 布林带、RSI、MACD、KDJ、ADX 等指标
- 📈 **涨跌幅榜**: 实时获取 A 股涨幅/跌幅排行
- 🔍 **股票搜索**: 按名称或代码搜索股票
- 📉 **指数分析**: 上证指数、深证成指、创业板指等
- 💰 **资金流向**: 行业资金流向、北向资金动态
- 🎯 **综合评级**: 基于多指标的综合买卖信号

## 安装

### 方法 1: 使用 uv (推荐)

```bash
uv tool install git+https://github.com/kylefu8/tradingview-akshare-mcp.git
```

### 方法 2: 本地安装

```bash
cd tradingview-akshare-mcp
pip install -e .
```

## 配置

### OpenCode 配置

编辑 `~/.config/opencode/mcp.json`:

```json
{
  "mcpServers": {
    "tradingview-akshare-mcp": {
      "command": "python",
      "args": ["C:/path/to/tradingview-akshare-mcp/server.py"]
    }
  }
}
```

### Claude Desktop 配置

编辑 `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tradingview-akshare-mcp": {
      "command": "python",
      "args": ["C:/path/to/tradingview-akshare-mcp/server.py"]
    }
  }
}
```

## 可用工具

| 工具 | 说明 |
|------|------|
| `stock_analysis` | 个股完整技术分析 |
| `stock_quote` | 获取实时行情 |
| `top_gainers` | A股涨幅榜 |
| `top_losers` | A股跌幅榜 |
| `stock_search` | 搜索股票 |
| `index_analysis` | 指数分析 |
| `sector_flow` | 行业资金流向 |
| `north_flow` | 北向资金流入 |

## 使用示例

### 分析个股

```python
# 分析工业富联
stock_analysis(symbol="601138", period="daily")

# 分析贵州茅台 (周线)
stock_analysis(symbol="600519", period="weekly")
```

### 获取涨跌幅榜

```python
# 涨幅前20
top_gainers(limit=20)

# 跌幅前10
top_losers(limit=10)
```

### 搜索股票

```python
# 按名称搜索
stock_search(keyword="茅台")

# 按代码搜索
stock_search(keyword="6001")
```

## 技术指标说明

### 布林带评级

| 评级 | 信号 | 含义 |
|-----|------|------|
| +2 | BUY | 价格跌破下轨 (超卖) |
| +1 | NEUTRAL | 价格在中轨上方 |
| -1 | NEUTRAL | 价格在中轨下方 |
| -2 | SELL | 价格突破上轨 (超买) |

### RSI 信号

- RSI > 70: 超买
- RSI < 30: 超卖
- 30 < RSI < 70: 中性

### 综合评分

- +4 及以上: 强烈看多
- +2 至 +3: 看多
- -1 至 +1: 中性
- -3 至 -2: 看空
- -4 及以下: 强烈看空

## 注意事项

1. 本工具仅提供技术分析数据，不构成投资建议
2. 数据来源于 AKShare，可能存在延迟
3. 首次请求可能较慢（需要加载数据）
4. A股交易时间为工作日 9:30-15:00

## License

MIT
