"""
AKShare MCP Server - A股市场技术分析工具
支持上交所、深交所全部A股的技术分析

MCP Protocol: https://modelcontextprotocol.io/
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
import numpy as np
import pandas as pd

import akshare as ak
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    Resource,
    Prompt,
    PromptMessage,
    PromptArgument,
)


# 创建 MCP Server 实例
server = Server("tradingview-akshare-mcp")


# ============== 技术指标计算函数 ==============

def calculate_bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: int = 2) -> pd.DataFrame:
    """计算布林带"""
    df = df.copy()
    df['SMA20'] = df['收盘'].rolling(window=window).mean()
    df['BB_std'] = df['收盘'].rolling(window=window).std()
    df['BB_upper'] = df['SMA20'] + (df['BB_std'] * num_std)
    df['BB_lower'] = df['SMA20'] - (df['BB_std'] * num_std)
    df['BBW'] = (df['BB_upper'] - df['BB_lower']) / df['SMA20']
    return df


def calculate_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """计算RSI"""
    df = df.copy()
    delta = df['收盘'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算MACD"""
    df = df.copy()
    df['EMA12'] = df['收盘'].ewm(span=fast, adjust=False).mean()
    df['EMA26'] = df['收盘'].ewm(span=slow, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']
    return df


def calculate_stochastic(df: pd.DataFrame, k_window: int = 14, d_window: int = 3) -> pd.DataFrame:
    """计算随机指标 KDJ"""
    df = df.copy()
    low_min = df['最低'].rolling(window=k_window).min()
    high_max = df['最高'].rolling(window=k_window).max()
    df['Stoch_K'] = 100 * (df['收盘'] - low_min) / (high_max - low_min)
    df['Stoch_D'] = df['Stoch_K'].rolling(window=d_window).mean()
    return df


def calculate_adx(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """计算ADX趋势强度"""
    df = df.copy()
    df['TR'] = np.maximum(
        df['最高'] - df['最低'],
        np.maximum(
            abs(df['最高'] - df['收盘'].shift(1)),
            abs(df['最低'] - df['收盘'].shift(1))
        )
    )
    df['+DM'] = np.where(
        (df['最高'] - df['最高'].shift(1)) > (df['最低'].shift(1) - df['最低']),
        np.maximum(df['最高'] - df['最高'].shift(1), 0),
        0
    )
    df['-DM'] = np.where(
        (df['最低'].shift(1) - df['最低']) > (df['最高'] - df['最高'].shift(1)),
        np.maximum(df['最低'].shift(1) - df['最低'], 0),
        0
    )
    
    df['TR_smooth'] = df['TR'].rolling(window=window).sum()
    df['+DI'] = 100 * (df['+DM'].rolling(window=window).sum() / df['TR_smooth'])
    df['-DI'] = 100 * (df['-DM'].rolling(window=window).sum() / df['TR_smooth'])
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].rolling(window=window).mean()
    return df


def get_bb_signal(price: float, upper: float, lower: float, middle: float) -> tuple[int, str]:
    """根据布林带位置判断信号"""
    if pd.isna(upper) or pd.isna(lower):
        return 0, "N/A"
    
    if price > upper:
        return -2, "SELL (超买)"
    elif price < lower:
        return 2, "BUY (超卖)"
    elif price > middle:
        return 1, "NEUTRAL (偏多)"
    else:
        return -1, "NEUTRAL (偏空)"


def get_comprehensive_score(latest: pd.Series, prev: pd.Series) -> tuple[int, list[str], str]:
    """计算综合评分"""
    score = 0
    signals = []
    
    # RSI
    if latest['RSI'] < 30:
        score += 2
        signals.append("RSI超卖(+2)")
    elif latest['RSI'] > 70:
        score -= 2
        signals.append("RSI超买(-2)")
    elif latest['RSI'] < 45:
        score -= 1
        signals.append("RSI偏弱(-1)")
    elif latest['RSI'] > 55:
        score += 1
        signals.append("RSI偏强(+1)")
    
    # MACD
    if latest['MACD'] > latest['MACD_signal'] and latest['MACD_hist'] > prev['MACD_hist']:
        score += 2
        signals.append("MACD金叉向上(+2)")
    elif latest['MACD'] > latest['MACD_signal']:
        score += 1
        signals.append("MACD金叉(+1)")
    elif latest['MACD'] < latest['MACD_signal'] and latest['MACD_hist'] < prev['MACD_hist']:
        score -= 2
        signals.append("MACD死叉向下(-2)")
    else:
        score -= 1
        signals.append("MACD死叉(-1)")
    
    # 布林带
    bb_rating, bb_signal = get_bb_signal(
        latest['收盘'], latest['BB_upper'], latest['BB_lower'], latest['SMA20']
    )
    score += bb_rating
    signals.append(f"布林带{bb_signal}({bb_rating:+d})")
    
    # 价格与均线
    if latest['收盘'] > latest['EMA50'] > latest.get('EMA200', 0):
        score += 2
        signals.append("多头排列(+2)")
    elif latest['收盘'] < latest['EMA50']:
        score -= 1
        signals.append("价格<EMA50(-1)")
    
    # 随机指标
    if latest['Stoch_K'] < 20:
        score += 1
        signals.append("KD超卖(+1)")
    elif latest['Stoch_K'] > 80:
        score -= 1
        signals.append("KD超买(-1)")
    
    # 综合判断
    if score >= 4:
        overall = "强烈看多"
    elif score >= 2:
        overall = "看多"
    elif score >= -1:
        overall = "中性"
    elif score >= -3:
        overall = "看空"
    else:
        overall = "强烈看空"
    
    return score, signals, overall


# ============== MCP 工具定义 ==============

@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用工具"""
    return [
        Tool(
            name="stock_analysis",
            description="A股个股完整技术分析，包括布林带、RSI、MACD、KDJ等指标",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '601138' (工业富联), '000001' (平安银行)"
                    },
                    "period": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                        "default": "daily",
                        "description": "时间周期: daily(日线), weekly(周线), monthly(月线)"
                    },
                    "days": {
                        "type": "integer",
                        "default": 365,
                        "description": "获取多少天的历史数据"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="stock_quote",
            description="获取A股实时行情快照",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '601138', '000001'"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="top_gainers",
            description="获取A股涨幅榜",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "返回数量"
                    }
                }
            }
        ),
        Tool(
            name="top_losers",
            description="获取A股跌幅榜",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "返回数量"
                    }
                }
            }
        ),
        Tool(
            name="stock_search",
            description="搜索A股股票代码和名称",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如 '工业富联', '平安', '茅台'"
                    }
                },
                "required": ["keyword"]
            }
        ),
        Tool(
            name="index_analysis",
            description="分析A股指数（上证、深证、创业板等）",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "指数代码: '000001'(上证指数), '399001'(深证成指), '399006'(创业板指)"
                    },
                    "period": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                        "default": "daily"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="sector_flow",
            description="获取行业资金流向",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "返回数量"
                    }
                }
            }
        ),
        Tool(
            name="north_flow",
            description="获取北向资金（沪港通、深港通）流入数据",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """执行工具调用"""
    
    try:
        if name == "stock_analysis":
            result = await analyze_stock(
                arguments["symbol"],
                arguments.get("period", "daily"),
                arguments.get("days", 365)
            )
        elif name == "stock_quote":
            result = await get_stock_quote(arguments["symbol"])
        elif name == "top_gainers":
            result = await get_top_gainers(arguments.get("limit", 20))
        elif name == "top_losers":
            result = await get_top_losers(arguments.get("limit", 20))
        elif name == "stock_search":
            result = await search_stock(arguments["keyword"])
        elif name == "index_analysis":
            result = await analyze_index(
                arguments["symbol"],
                arguments.get("period", "daily")
            )
        elif name == "sector_flow":
            result = await get_sector_flow(arguments.get("limit", 20))
        elif name == "north_flow":
            result = await get_north_flow()
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e),
            "tool": name,
            "arguments": arguments
        }, ensure_ascii=False))]


# ============== 工具实现 ==============

async def analyze_stock(symbol: str, period: str = "daily", days: int = 365) -> dict:
    """完整股票技术分析"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
    # 获取历史数据
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date,
        adjust="qfq"
    )
    
    if df.empty:
        return {"error": f"No data found for {symbol}"}
    
    # 计算技术指标
    df = calculate_bollinger_bands(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_stochastic(df)
    df = calculate_adx(df)
    df['EMA50'] = df['收盘'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['收盘'].ewm(span=200, adjust=False).mean()
    
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    
    # 获取股票名称
    try:
        stock_info = ak.stock_individual_info_em(symbol=symbol)
        stock_name = stock_info[stock_info['item'] == '股票简称']['value'].values[0]
    except:
        stock_name = symbol
    
    # 布林带信号
    bb_rating, bb_signal = get_bb_signal(
        latest['收盘'], latest['BB_upper'], latest['BB_lower'], latest['SMA20']
    )
    
    # 综合评分
    score, signals, overall = get_comprehensive_score(latest, prev)
    
    return {
        "symbol": symbol,
        "name": stock_name,
        "period": period,
        "timestamp": datetime.now().isoformat(),
        "price_data": {
            "current_price": round(float(latest['收盘']), 2),
            "open": round(float(latest['开盘']), 2),
            "high": round(float(latest['最高']), 2),
            "low": round(float(latest['最低']), 2),
            "change_percent": round(float(latest['涨跌幅']), 2),
            "volume": int(latest['成交量']),
            "amount": float(latest['成交额']),
            "turnover": round(float(latest['换手率']), 2)
        },
        "bollinger_analysis": {
            "rating": bb_rating,
            "signal": bb_signal,
            "bbw": round(float(latest['BBW']) * 100, 2),
            "bb_upper": round(float(latest['BB_upper']), 2),
            "bb_middle": round(float(latest['SMA20']), 2),
            "bb_lower": round(float(latest['BB_lower']), 2)
        },
        "technical_indicators": {
            "rsi": round(float(latest['RSI']), 2),
            "rsi_signal": "超买" if latest['RSI'] > 70 else "超卖" if latest['RSI'] < 30 else "中性",
            "sma20": round(float(latest['SMA20']), 2),
            "ema50": round(float(latest['EMA50']), 2),
            "ema200": round(float(latest['EMA200']), 2),
            "macd": round(float(latest['MACD']), 4),
            "macd_signal": round(float(latest['MACD_signal']), 4),
            "macd_hist": round(float(latest['MACD_hist']), 4),
            "macd_cross": "金叉" if latest['MACD'] > latest['MACD_signal'] else "死叉",
            "adx": round(float(latest['ADX']), 2),
            "trend_strength": "强趋势" if latest['ADX'] > 25 else "中等" if latest['ADX'] > 20 else "弱趋势",
            "stoch_k": round(float(latest['Stoch_K']), 2),
            "stoch_d": round(float(latest['Stoch_D']), 2)
        },
        "key_levels": {
            "resistance_1": round(float(latest['SMA20']), 2),
            "resistance_2": round(float(latest['EMA50']), 2),
            "resistance_3": round(float(latest['BB_upper']), 2),
            "support_1": round(float(latest['BB_lower']), 2),
            "support_2": round(float(latest['EMA200']), 2)
        },
        "comprehensive_analysis": {
            "score": score,
            "signals": signals,
            "overall": overall
        }
    }


async def get_stock_quote(symbol: str) -> dict:
    """获取实时行情"""
    try:
        df = ak.stock_zh_a_spot_em()
        stock = df[df['代码'] == symbol]
        if stock.empty:
            return {"error": f"Stock {symbol} not found"}
        
        row = stock.iloc[0]
        return {
            "symbol": symbol,
            "name": row['名称'],
            "price": float(row['最新价']),
            "change": float(row['涨跌额']),
            "change_percent": float(row['涨跌幅']),
            "open": float(row['今开']),
            "high": float(row['最高']),
            "low": float(row['最低']),
            "volume": int(row['成交量']),
            "amount": float(row['成交额']),
            "turnover": float(row['换手率']),
            "pe_ratio": float(row['市盈率-动态']) if pd.notna(row['市盈率-动态']) else None,
            "pb_ratio": float(row['市净率']) if pd.notna(row['市净率']) else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


async def get_top_gainers(limit: int = 20) -> dict:
    """获取涨幅榜"""
    df = ak.stock_zh_a_spot_em()
    df = df.sort_values('涨跌幅', ascending=False).head(limit)
    
    stocks = []
    for _, row in df.iterrows():
        stocks.append({
            "symbol": row['代码'],
            "name": row['名称'],
            "price": float(row['最新价']),
            "change_percent": float(row['涨跌幅']),
            "volume": int(row['成交量']),
            "amount": float(row['成交额'])
        })
    
    return {
        "type": "top_gainers",
        "count": len(stocks),
        "timestamp": datetime.now().isoformat(),
        "stocks": stocks
    }


async def get_top_losers(limit: int = 20) -> dict:
    """获取跌幅榜"""
    df = ak.stock_zh_a_spot_em()
    df = df.sort_values('涨跌幅', ascending=True).head(limit)
    
    stocks = []
    for _, row in df.iterrows():
        stocks.append({
            "symbol": row['代码'],
            "name": row['名称'],
            "price": float(row['最新价']),
            "change_percent": float(row['涨跌幅']),
            "volume": int(row['成交量']),
            "amount": float(row['成交额'])
        })
    
    return {
        "type": "top_losers",
        "count": len(stocks),
        "timestamp": datetime.now().isoformat(),
        "stocks": stocks
    }


async def search_stock(keyword: str) -> dict:
    """搜索股票"""
    df = ak.stock_zh_a_spot_em()
    
    # 按名称或代码搜索
    matches = df[
        df['名称'].str.contains(keyword, na=False) |
        df['代码'].str.contains(keyword, na=False)
    ].head(20)
    
    stocks = []
    for _, row in matches.iterrows():
        stocks.append({
            "symbol": row['代码'],
            "name": row['名称'],
            "price": float(row['最新价']),
            "change_percent": float(row['涨跌幅'])
        })
    
    return {
        "keyword": keyword,
        "count": len(stocks),
        "results": stocks
    }


async def analyze_index(symbol: str, period: str = "daily") -> dict:
    """分析指数"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    
    df = ak.index_zh_a_hist(
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date
    )
    
    if df.empty:
        return {"error": f"No data found for index {symbol}"}
    
    # 计算技术指标
    df = calculate_bollinger_bands(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    
    latest = df.iloc[-1]
    
    # 指数名称映射
    index_names = {
        "000001": "上证指数",
        "399001": "深证成指",
        "399006": "创业板指",
        "000300": "沪深300",
        "000016": "上证50",
        "000905": "中证500"
    }
    
    return {
        "symbol": symbol,
        "name": index_names.get(symbol, symbol),
        "period": period,
        "price_data": {
            "current": round(float(latest['收盘']), 2),
            "open": round(float(latest['开盘']), 2),
            "high": round(float(latest['最高']), 2),
            "low": round(float(latest['最低']), 2),
            "change_percent": round(float(latest['涨跌幅']), 2),
            "volume": int(latest['成交量']),
            "amount": float(latest['成交额'])
        },
        "technical_indicators": {
            "rsi": round(float(latest['RSI']), 2),
            "sma20": round(float(latest['SMA20']), 2),
            "bb_upper": round(float(latest['BB_upper']), 2),
            "bb_lower": round(float(latest['BB_lower']), 2),
            "macd": round(float(latest['MACD']), 4),
            "macd_signal": round(float(latest['MACD_signal']), 4)
        },
        "timestamp": datetime.now().isoformat()
    }


async def get_sector_flow(limit: int = 20) -> dict:
    """获取行业资金流向"""
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日")
        df = df.head(limit)
        
        sectors = []
        for _, row in df.iterrows():
            sectors.append({
                "name": row['名称'],
                "change_percent": float(row['今日涨跌幅']) if pd.notna(row['今日涨跌幅']) else 0,
                "main_net_inflow": float(row['今日主力净流入-净额']) if pd.notna(row['今日主力净流入-净额']) else 0,
                "main_net_inflow_percent": float(row['今日主力净流入-净占比']) if pd.notna(row['今日主力净流入-净占比']) else 0
            })
        
        return {
            "type": "sector_flow",
            "count": len(sectors),
            "timestamp": datetime.now().isoformat(),
            "sectors": sectors
        }
    except Exception as e:
        return {"error": str(e)}


async def get_north_flow() -> dict:
    """获取北向资金流向"""
    try:
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
        latest = df.iloc[-1] if not df.empty else None
        
        if latest is None:
            return {"error": "No north flow data available"}
        
        return {
            "type": "north_flow",
            "date": str(latest['日期']),
            "net_inflow": float(latest['当日成交净买额']) if pd.notna(latest['当日成交净买额']) else 0,
            "buy_amount": float(latest['当日买入成交额']) if pd.notna(latest.get('当日买入成交额', 0)) else 0,
            "sell_amount": float(latest['当日卖出成交额']) if pd.notna(latest.get('当日卖出成交额', 0)) else 0,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


# ============== 资源定义 ==============

@server.list_resources()
async def list_resources() -> list[Resource]:
    """列出可用资源"""
    return [
        Resource(
            uri="exchanges://list",
            name="支持的交易所列表",
            mimeType="application/json"
        ),
        Resource(
            uri="indices://list",
            name="主要A股指数列表",
            mimeType="application/json"
        )
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """读取资源"""
    if uri == "exchanges://list":
        return json.dumps({
            "exchanges": [
                {"code": "SSE", "name": "上海证券交易所", "prefix": "60, 68"},
                {"code": "SZSE", "name": "深圳证券交易所", "prefix": "00, 30"},
                {"code": "BSE", "name": "北京证券交易所", "prefix": "8, 4"}
            ]
        }, ensure_ascii=False)
    
    elif uri == "indices://list":
        return json.dumps({
            "indices": [
                {"symbol": "000001", "name": "上证指数"},
                {"symbol": "399001", "name": "深证成指"},
                {"symbol": "399006", "name": "创业板指"},
                {"symbol": "000300", "name": "沪深300"},
                {"symbol": "000016", "name": "上证50"},
                {"symbol": "000905", "name": "中证500"},
                {"symbol": "000688", "name": "科创50"}
            ]
        }, ensure_ascii=False)
    
    return json.dumps({"error": f"Unknown resource: {uri}"})


# ============== Prompts 定义 ==============

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """列出可用提示模板"""
    return [
        Prompt(
            name="analyze_stock",
            description="分析指定股票的技术面",
            arguments=[
                PromptArgument(
                    name="symbol",
                    description="股票代码",
                    required=True
                )
            ]
        ),
        Prompt(
            name="market_overview",
            description="获取A股市场概览",
            arguments=[]
        )
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> list[PromptMessage]:
    """获取提示内容"""
    if name == "analyze_stock":
        symbol = arguments.get("symbol", "000001") if arguments else "000001"
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"请对股票 {symbol} 进行完整的技术分析，包括：\n"
                         f"1. 当前价格和涨跌情况\n"
                         f"2. 布林带位置和信号\n"
                         f"3. RSI、MACD、KDJ等技术指标\n"
                         f"4. 关键支撑位和阻力位\n"
                         f"5. 综合评级和建议"
                )
            )
        ]
    
    elif name == "market_overview":
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text="请提供今日A股市场概览，包括：\n"
                         "1. 上证指数、深证成指、创业板指的表现\n"
                         "2. 涨幅榜前10\n"
                         "3. 跌幅榜前10\n"
                         "4. 行业资金流向\n"
                         "5. 北向资金动态"
                )
            )
        ]
    
    return []


# ============== 主入口 ==============

async def main():
    """运行 MCP Server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
