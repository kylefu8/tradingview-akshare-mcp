"""
测试 AKShare MCP 核心功能
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import asyncio
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import akshare as ak

# 导入我们的多源数据管理器
from server import DataSourceManager, CacheManager

# 初始化
data_source = DataSourceManager()
cache = CacheManager()


def calculate_bollinger_bands(df, window=20, num_std=2):
    df = df.copy()
    df['SMA20'] = df['收盘'].rolling(window=window).mean()
    df['BB_std'] = df['收盘'].rolling(window=window).std()
    df['BB_upper'] = df['SMA20'] + (df['BB_std'] * num_std)
    df['BB_lower'] = df['SMA20'] - (df['BB_std'] * num_std)
    df['BBW'] = (df['BB_upper'] - df['BB_lower']) / df['SMA20']
    return df


def calculate_rsi(df, window=14):
    df = df.copy()
    delta = df['收盘'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df


def calculate_macd(df, fast=12, slow=26, signal=9):
    df = df.copy()
    df['EMA12'] = df['收盘'].ewm(span=fast, adjust=False).mean()
    df['EMA26'] = df['收盘'].ewm(span=slow, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']
    return df


def test_stock_analysis(symbol="601138"):
    """测试个股分析"""
    print(f"\n{'='*60}")
    print(f"测试 stock_analysis: {symbol}")
    print('='*60)
    
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        
        # 使用多源数据管理器
        df = data_source.get_stock_history(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"
        )
        
        if df.empty:
            print(f"❌ 未找到数据: {symbol}")
            return False
        
        df = calculate_bollinger_bands(df)
        df = calculate_rsi(df)
        df = calculate_macd(df)
        
        latest = df.iloc[-1]
        
        print(f"✅ 获取到 {len(df)} 条数据")
        print(f"   最新价: {latest['收盘']:.2f}")
        print(f"   涨跌幅: {latest['涨跌幅']:.2f}%")
        print(f"   RSI: {latest['RSI']:.2f}")
        print(f"   MACD: {latest['MACD']:.4f}")
        print(f"   BB上轨: {latest['BB_upper']:.2f}")
        print(f"   BB下轨: {latest['BB_lower']:.2f}")
        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def test_stock_quote(symbol="600519"):
    """测试实时行情"""
    print(f"\n{'='*60}")
    print(f"测试 stock_quote: {symbol}")
    print('='*60)
    
    try:
        # 使用多源数据管理器
        df = data_source.get_realtime_quotes()
        stock = df[df['代码'] == symbol]
        
        if stock.empty:
            print(f"❌ 未找到股票: {symbol}")
            return False
        
        row = stock.iloc[0]
        print(f"✅ 股票: {row['名称']}")
        print(f"   最新价: {row['最新价']}")
        print(f"   涨跌幅: {row['涨跌幅']}%")
        print(f"   成交额: {row['成交额']:,.0f}")
        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def test_top_gainers():
    """测试涨幅榜"""
    print(f"\n{'='*60}")
    print("测试 top_gainers")
    print('='*60)
    
    try:
        # 使用多源数据管理器
        df = data_source.get_realtime_quotes()
        df = df.sort_values('涨跌幅', ascending=False).head(5)
        
        print(f"✅ 涨幅前5:")
        for _, row in df.iterrows():
            print(f"   {row['代码']} {row['名称']}: {row['涨跌幅']}%")
        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def test_stock_search(keyword="茅台"):
    """测试股票搜索"""
    print(f"\n{'='*60}")
    print(f"测试 stock_search: {keyword}")
    print('='*60)
    
    try:
        # 使用多源数据管理器
        df = data_source.get_realtime_quotes()
        matches = df[df['名称'].str.contains(keyword, na=False)].head(5)
        
        print(f"✅ 找到 {len(matches)} 个匹配:")
        for _, row in matches.iterrows():
            print(f"   {row['代码']} {row['名称']}")
        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def test_index_analysis(symbol="000001"):
    """测试指数分析"""
    print(f"\n{'='*60}")
    print(f"测试 index_analysis: {symbol}")
    print('='*60)
    
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        
        # 使用多源数据管理器
        df = data_source.get_index_history(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date
        )
        
        if df.empty:
            print(f"❌ 未找到指数数据: {symbol}")
            return False
        
        latest = df.iloc[-1]
        print(f"✅ 上证指数")
        print(f"   收盘: {latest['收盘']:.2f}")
        print(f"   涨跌幅: {latest['涨跌幅']:.2f}%")
        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


if __name__ == "__main__":
    import time
    
    print("\n" + "="*60)
    print("  AKShare MCP 功能测试")
    print("="*60)
    
    results = []
    
    # 添加请求间隔避免触发速率限制
    results.append(("stock_analysis", test_stock_analysis("601138")))
    time.sleep(2)  # 等待2秒
    
    results.append(("stock_quote", test_stock_quote("600519")))
    time.sleep(2)
    
    results.append(("top_gainers", test_top_gainers()))
    time.sleep(2)
    
    results.append(("stock_search", test_stock_search("茅台")))
    time.sleep(2)
    
    results.append(("index_analysis", test_index_analysis("000001")))
    
    print("\n" + "="*60)
    print("  测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {name}: {status}")
    
    print(f"\n  通过: {passed}/{total}")
    print("="*60)
