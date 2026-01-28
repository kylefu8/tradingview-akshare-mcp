# TradingView AKShare MCP Server

A股市场技术分析 MCP (Model Context Protocol) Server，基于 AKShare 数据源。

## 功能特性

- 📊 **个股技术分析**: 布林带、RSI、MACD、KDJ、ADX 等指标
- 📈 **涨跌幅榜**: 实时获取 A 股涨幅/跌幅排行
- 🔍 **股票搜索**: 按名称或代码搜索股票
- 📉 **指数分析**: 上证指数、深证成指、创业板指等
- 💰 **资金流向**: 行业资金流向、北向资金动态
- 🎯 **综合评级**: 基于多指标的综合买卖信号
- 🔄 **多数据源**: 自动切换备份源，提高可用性
- 💾 **智能缓存**: 内存缓存 + 本地持久化，减少 API 请求

## 新特性 (v1.1)

### 多数据源支持
当主数据源不可用时，自动切换到备份源：

| 数据类型 | 主源 | 备份源 |
|---------|------|--------|
| 实时行情 | 东方财富 | 新浪 / 分市场合并 |
| 股票历史 | 东方财富 | 腾讯 |
| 指数历史 | 东方财富 | 中证指数 |

### 智能缓存系统
- **内存缓存**: 实时行情数据缓存 30 秒
- **本地缓存**: 历史 K 线数据持久化存储 (Parquet 格式)
- **增量更新**: 只获取缺失的新数据

### 请求速率控制
- 自动请求间隔 (1秒)
- 数据源健康检测
- 失败自动重试和切换

## 安装

### 方法 1: 让 AI 帮你安装（推荐）

将以下提示词复制粘贴给你的 AI 助手（Claude Code、OpenCode、Cursor 等），让它自动完成安装和配置：

```
请帮我安装和配置 tradingview-akshare-mcp，按照以下步骤操作：

1. 克隆仓库到本地: git clone https://github.com/kylefu8/tradingview-akshare-mcp.git
2. 使用 uv 或 pip 安装: uv tool install . 或 pip install -e .
3. 根据我使用的 AI 客户端（OpenCode/Claude Desktop）自动配置 MCP Server
4. 配置 Skills 技能文件，让 AI 具备专业的 A 股技术分析能力
5. 验证安装是否成功
```

### 方法 2: 使用 uv 一键安装

```bash
uv tool install git+https://github.com/kylefu8/tradingview-akshare-mcp.git
```

### 方法 3: 本地安装

```bash
git clone https://github.com/kylefu8/tradingview-akshare-mcp.git
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
      "command": "tradingview-akshare-mcp"
    }
  }
}
```

### Claude Desktop 配置

编辑 `%APPDATA%\Claude\claude_desktop_config.json` (Windows) 或 `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "tradingview-akshare-mcp": {
      "command": "tradingview-akshare-mcp"
    }
  }
}
```

> 💡 **提示**: 如果使用 `uv tool install` 安装，可以直接使用命令名 `tradingview-akshare-mcp`；如果是本地安装，需要使用 `python /path/to/mcp/server.py` 的方式。

## 卸载

### 卸载 MCP Server

```bash
# 如果使用 uv 安装
uv tool uninstall tradingview-akshare-mcp

# 如果使用 pip 安装
pip uninstall tradingview-akshare-mcp
```

### 移除配置

1. **OpenCode**: 编辑 `~/.config/opencode/mcp.json`，删除 `tradingview-akshare-mcp` 配置项
2. **Claude Desktop**: 编辑配置文件，删除 `tradingview-akshare-mcp` 配置项

### 清理缓存数据（可选）

```bash
# 删除本地缓存目录
rm -rf ~/.akshare_cache/
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
| `cache_stats` | 查看缓存统计信息 |
| `clear_cache` | 清空缓存数据 |

## Skills 技能文件

项目包含预定义的 AI 技能文件，位于 `skills/` 目录下，可用于增强 AI 助手的股票分析能力。

### 可用技能

| 技能 | 文件 | 说明 |
|------|------|------|
| A股技术分析专家 | `skills/stock-analysis.md` | 专业的 A 股技术分析师技能，包含完整的分析流程和指标解读 |

### 技能特性

- **完整的分析流程**: 从识别用户意图到输出格式化报告
- **技术指标解读**: RSI、MACD、KDJ、布林带、ADX 等指标的详细解读规则
- **综合评分系统**: 基于多指标的综合买卖信号判断
- **标准化输出格式**: 结构化的分析报告模板

### 配置方式

#### Claude Desktop

在 Claude Desktop 的 AGENTS.md 或项目根目录创建 `.claude/skills/` 目录，将技能文件复制进去：

```bash
# 创建技能目录
mkdir -p .claude/skills

# 复制技能文件
cp skills/stock-analysis.md .claude/skills/
```

或者在项目根目录创建 `AGENTS.md`，引用技能文件：

```markdown
## Skills

- [A股技术分析专家](skills/stock-analysis.md)
```

#### OpenCode

在项目根目录创建 `.opencode/skills/` 目录，将技能文件复制进去：

```bash
mkdir -p .opencode/skills
cp skills/stock-analysis.md .opencode/skills/
```

> 💡 **提示**: Skills 文件已内置 MCP 配置，OpenCode 会自动加载。

#### 验证配置

配置完成后，向 AI 助手发送以下消息测试：

```
分析一下贵州茅台的技术面
```

AI 助手应该会自动调用 `stock_search` 和 `stock_analysis` 工具进行分析。

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
5. 历史数据会自动缓存到 `~/.akshare_cache/` 目录
6. 如遇到数据源限制，系统会自动切换备用源

## 缓存管理

```python
# 查看缓存统计
cache_stats()

# 清空内存缓存
clear_cache(cache_type="memory")

# 清空本地缓存
clear_cache(cache_type="local")

# 清空指定股票的缓存
clear_cache(cache_type="local", symbol="600519")
```

## License

MIT
