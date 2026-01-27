"""
AKShare MCP Server - A股市场技术分析工具
支持上交所、深交所全部A股的技术分析

MCP Protocol: https://modelcontextprotocol.io/
"""

import asyncio
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional
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


# ============== 缓存系统 ==============

class CacheManager:
    """
    缓存管理器
    - 内存缓存：用于实时数据（全市场行情等），带 TTL
    - 本地缓存：用于历史K线数据，持久化存储
    """
    
    def __init__(self, cache_dir: str = None):
        # 内存缓存 {key: (data, timestamp)}
        self._memory_cache: dict[str, tuple[Any, float]] = {}
        
        # 本地缓存目录
        if cache_dir is None:
            cache_dir = os.path.join(os.path.expanduser("~"), ".akshare_cache")
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 默认 TTL（秒）
        self._default_ttl = 60  # 实时数据缓存60秒
    
    def _get_cache_key(self, prefix: str, **kwargs) -> str:
        """生成缓存键"""
        params = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{prefix}_{params}"
    
    def _get_file_path(self, symbol: str, period: str, data_type: str = "stock") -> Path:
        """获取本地缓存文件路径"""
        return self._cache_dir / f"{data_type}_{symbol}_{period}.parquet"
    
    # ============== 内存缓存 ==============
    
    def get_memory(self, key: str, ttl: int = None) -> Optional[Any]:
        """获取内存缓存"""
        if key not in self._memory_cache:
            return None
        
        data, timestamp = self._memory_cache[key]
        ttl = ttl or self._default_ttl
        
        if datetime.now().timestamp() - timestamp > ttl:
            del self._memory_cache[key]
            return None
        
        return data
    
    def set_memory(self, key: str, data: Any) -> None:
        """设置内存缓存"""
        self._memory_cache[key] = (data, datetime.now().timestamp())
    
    def get_realtime_quotes(self) -> Optional[pd.DataFrame]:
        """获取缓存的实时行情"""
        return self.get_memory("realtime_quotes", ttl=30)  # 30秒TTL
    
    def set_realtime_quotes(self, df: pd.DataFrame) -> None:
        """缓存实时行情"""
        self.set_memory("realtime_quotes", df)
    
    # ============== 本地历史数据缓存 ==============
    
    def get_historical_data(
        self, 
        symbol: str, 
        period: str, 
        start_date: str, 
        end_date: str,
        data_type: str = "stock"
    ) -> Optional[pd.DataFrame]:
        """
        获取本地缓存的历史数据
        返回请求范围内的数据，如果缓存不完整则返回 None
        """
        file_path = self._get_file_path(symbol, period, data_type)
        
        if not file_path.exists():
            return None
        
        try:
            df = pd.read_parquet(file_path)
            if df.empty:
                return None
            
            # 确保日期列是字符串格式用于比较
            df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
            
            # 筛选请求的日期范围
            start_dt = datetime.strptime(start_date, "%Y%m%d").strftime('%Y-%m-%d')
            end_dt = datetime.strptime(end_date, "%Y%m%d").strftime('%Y-%m-%d')
            
            filtered = df[(df['日期'] >= start_dt) & (df['日期'] <= end_dt)].copy()
            
            if filtered.empty:
                return None
            
            # 检查是否有最新数据（缓存的最后日期是否接近请求的结束日期）
            cached_last_date = df['日期'].max()
            today = datetime.now().strftime('%Y-%m-%d')
            
            # 如果缓存数据落后超过2天，需要更新
            cached_last_dt = datetime.strptime(cached_last_date, '%Y-%m-%d')
            end_dt_obj = datetime.strptime(end_dt, '%Y-%m-%d')
            
            if (end_dt_obj - cached_last_dt).days > 2:
                return None  # 需要更新
            
            return filtered
            
        except Exception as e:
            print(f"读取缓存失败 {file_path}: {e}")
            return None
    
    def save_historical_data(
        self, 
        df: pd.DataFrame, 
        symbol: str, 
        period: str,
        data_type: str = "stock"
    ) -> None:
        """
        保存历史数据到本地（增量合并）
        """
        if df.empty:
            return
        
        file_path = self._get_file_path(symbol, period, data_type)
        
        try:
            # 确保新数据的日期格式一致
            new_df = df.copy()
            new_df['日期'] = pd.to_datetime(new_df['日期']).dt.strftime('%Y-%m-%d')
            
            if file_path.exists():
                # 读取现有数据并合并
                existing_df = pd.read_parquet(file_path)
                existing_df['日期'] = pd.to_datetime(existing_df['日期']).dt.strftime('%Y-%m-%d')
                
                # 合并并去重（以日期为准，保留新数据）
                combined = pd.concat([existing_df, new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=['日期'], keep='last')
                combined = combined.sort_values('日期').reset_index(drop=True)
            else:
                combined = new_df.sort_values('日期').reset_index(drop=True)
            
            # 保存为 parquet 格式（高效压缩）
            combined.to_parquet(file_path, index=False)
            
        except Exception as e:
            print(f"保存缓存失败 {file_path}: {e}")
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        stats = {
            "memory_cache_keys": len(self._memory_cache),
            "cache_dir": str(self._cache_dir),
            "local_files": []
        }
        
        for f in self._cache_dir.glob("*.parquet"):
            stats["local_files"].append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 2),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            })
        
        return stats
    
    def clear_memory_cache(self) -> None:
        """清空内存缓存"""
        self._memory_cache.clear()
    
    def clear_local_cache(self, symbol: str = None) -> int:
        """清空本地缓存，返回删除的文件数"""
        count = 0
        if symbol:
            for f in self._cache_dir.glob(f"*_{symbol}_*.parquet"):
                f.unlink()
                count += 1
        else:
            for f in self._cache_dir.glob("*.parquet"):
                f.unlink()
                count += 1
        return count


# 全局缓存管理器实例
cache = CacheManager()


# ============== 多数据源支持 ==============

class DataSourceManager:
    """
    多数据源管理器
    支持自动切换备份源，当主源失败时尝试其他数据源
    """
    
    def __init__(self):
        # 请求间隔（秒）
        self.request_interval = 1.0
        self.last_request_time = 0
        
        # 失败计数，用于判断是否需要切换源
        self.failure_count = {}
        self.max_failures = 3
    
    def _wait_for_rate_limit(self):
        """等待以满足速率限制"""
        import time
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _record_failure(self, source: str):
        """记录数据源失败"""
        self.failure_count[source] = self.failure_count.get(source, 0) + 1
    
    def _record_success(self, source: str):
        """记录数据源成功，重置失败计数"""
        self.failure_count[source] = 0
    
    def _is_source_healthy(self, source: str) -> bool:
        """检查数据源是否健康"""
        return self.failure_count.get(source, 0) < self.max_failures
    
    def get_realtime_quotes(self) -> pd.DataFrame:
        """
        获取实时行情，支持多源切换
        优先级：东方财富全市场 > 新浪 > 分市场合并
        """
        sources = [
            ("em", lambda: ak.stock_zh_a_spot_em()),
            ("sina", lambda: self._get_sina_realtime()),
            ("em_combined", lambda: self._get_combined_realtime()),
        ]
        
        last_error = None
        for source_name, fetch_func in sources:
            if not self._is_source_healthy(source_name):
                continue
            
            try:
                self._wait_for_rate_limit()
                df = fetch_func()
                if df is not None and not df.empty:
                    self._record_success(source_name)
                    return df
            except Exception as e:
                self._record_failure(source_name)
                last_error = e
                continue
        
        # 所有源都失败了，重置失败计数并抛出异常
        self.failure_count.clear()
        raise Exception(f"所有数据源都不可用: {last_error}")
    
    def _get_sina_realtime(self) -> pd.DataFrame:
        """从新浪获取实时行情"""
        # 新浪接口，返回格式需要转换为与东方财富一致
        try:
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                # 重命名列以保持一致性
                column_map = {
                    'symbol': '代码',
                    'code': '代码', 
                    'name': '名称',
                    'trade': '最新价',
                    'pricechange': '涨跌额',
                    'changepercent': '涨跌幅',
                    'open': '今开',
                    'high': '最高',
                    'low': '最低',
                    'volume': '成交量',
                    'amount': '成交额',
                    'turnoverratio': '换手率',
                }
                df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})
            return df
        except:
            return None
    
    def _get_combined_realtime(self) -> pd.DataFrame:
        """分市场获取后合并（当全市场接口被限制时的备用方案）"""
        try:
            dfs = []
            # 尝试获取各板块
            try:
                dfs.append(ak.stock_kc_a_spot_em())  # 科创板
            except:
                pass
            try:
                dfs.append(ak.stock_cy_a_spot_em())  # 创业板
            except:
                pass
            try:
                dfs.append(ak.stock_sh_a_spot_em())  # 上海A股
            except:
                pass
            try:
                dfs.append(ak.stock_sz_a_spot_em())  # 深圳A股
            except:
                pass
            
            if dfs:
                combined = pd.concat(dfs, ignore_index=True)
                # 去重（按代码）
                if '代码' in combined.columns:
                    combined = combined.drop_duplicates(subset=['代码'], keep='first')
                return combined
            return None
        except:
            return None

    def get_stock_history(
        self, 
        symbol: str, 
        period: str, 
        start_date: str, 
        end_date: str,
        adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        获取股票历史数据，支持多源切换
        优先级：东方财富 > 腾讯
        """
        sources = [
            ("em", lambda: ak.stock_zh_a_hist(
                symbol=symbol, period=period, 
                start_date=start_date, end_date=end_date, adjust=adjust
            )),
            ("tx", lambda: self._get_tencent_history(symbol, start_date, end_date, adjust)),
        ]
        
        last_error = None
        for source_name, fetch_func in sources:
            if not self._is_source_healthy(source_name):
                continue
            
            try:
                self._wait_for_rate_limit()
                df = fetch_func()
                if df is not None and not df.empty:
                    self._record_success(source_name)
                    return df
            except Exception as e:
                self._record_failure(source_name)
                last_error = e
                continue
        
        self.failure_count.clear()
        raise Exception(f"所有数据源都不可用: {last_error}")
    
    def _get_tencent_history(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str,
        adjust: str
    ) -> pd.DataFrame:
        """从腾讯获取历史数据"""
        try:
            # 腾讯接口
            df = ak.stock_zh_a_daily(symbol=symbol, adjust=adjust)
            if df is not None and not df.empty:
                # 转换日期格式并过滤
                df['date'] = pd.to_datetime(df['date'])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                
                # 重命名列以保持一致性
                column_map = {
                    'date': '日期',
                    'open': '开盘',
                    'high': '最高',
                    'low': '最低',
                    'close': '收盘',
                    'volume': '成交量',
                }
                df = df.rename(columns=column_map)
                
                # 添加缺失的列
                if '成交额' not in df.columns:
                    df['成交额'] = df['成交量'] * df['收盘']
                if '涨跌幅' not in df.columns:
                    df['涨跌幅'] = df['收盘'].pct_change() * 100
                if '换手率' not in df.columns:
                    df['换手率'] = 0
                    
            return df
        except:
            return None
    
    def get_index_history(
        self, 
        symbol: str, 
        period: str, 
        start_date: str, 
        end_date: str
    ) -> pd.DataFrame:
        """
        获取指数历史数据，支持多源切换
        优先级：东方财富 > 中证指数
        """
        sources = [
            ("em", lambda: ak.index_zh_a_hist(
                symbol=symbol, period=period,
                start_date=start_date, end_date=end_date
            )),
            ("csindex", lambda: self._get_csindex_history(symbol, start_date, end_date)),
        ]
        
        last_error = None
        for source_name, fetch_func in sources:
            if not self._is_source_healthy(source_name):
                continue
            
            try:
                self._wait_for_rate_limit()
                df = fetch_func()
                if df is not None and not df.empty:
                    self._record_success(source_name)
                    return df
            except Exception as e:
                self._record_failure(source_name)
                last_error = e
                continue
        
        self.failure_count.clear()
        raise Exception(f"所有数据源都不可用: {last_error}")
    
    def _get_csindex_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """从中证指数获取历史数据"""
        try:
            df = ak.stock_zh_index_hist_csindex(
                symbol=symbol, 
                start_date=start_date, 
                end_date=end_date
            )
            if df is not None and not df.empty:
                # 标准化列名
                column_map = {
                    '日期': '日期',
                    '开盘': '开盘',
                    '最高': '最高',
                    '最低': '最低',
                    '收盘': '收盘',
                    '涨跌幅': '涨跌幅',
                    '成交量': '成交量',
                    '成交金额': '成交额',
                }
                df = df.rename(columns=column_map)
                
                if '成交额' not in df.columns and '成交量' in df.columns:
                    df['成交额'] = df['成交量'] * df['收盘']
                    
            return df
        except:
            return None


# 全局数据源管理器
data_source = DataSourceManager()


def get_realtime_quotes_cached() -> pd.DataFrame:
    """
    获取实时行情（带缓存 + 多源支持）
    缓存30秒，避免频繁请求全市场数据
    """
    cached = cache.get_realtime_quotes()
    if cached is not None:
        return cached
    
    df = data_source.get_realtime_quotes()
    cache.set_realtime_quotes(df)
    return df


def get_stock_history_cached(
    symbol: str, 
    period: str, 
    start_date: str, 
    end_date: str,
    adjust: str = "qfq"
) -> pd.DataFrame:
    """
    获取股票历史数据（带本地缓存 + 多源支持）
    首先检查本地缓存，如果没有或不完整则从 API 获取并保存
    """
    # 尝试从本地缓存获取
    cached_df = cache.get_historical_data(symbol, period, start_date, end_date, "stock")
    
    if cached_df is not None and len(cached_df) > 0:
        return cached_df
    
    # 从 API 获取（多源）
    df = data_source.get_stock_history(
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date,
        adjust=adjust
    )
    
    if not df.empty:
        # 保存到本地缓存
        cache.save_historical_data(df, symbol, period, "stock")
    
    return df


def get_index_history_cached(
    symbol: str, 
    period: str, 
    start_date: str, 
    end_date: str
) -> pd.DataFrame:
    """
    获取指数历史数据（带本地缓存 + 多源支持）
    """
    # 尝试从本地缓存获取
    cached_df = cache.get_historical_data(symbol, period, start_date, end_date, "index")
    
    if cached_df is not None and len(cached_df) > 0:
        return cached_df
    
    # 从 API 获取（多源）
    df = data_source.get_index_history(
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date
    )
    
    if not df.empty:
        # 保存到本地缓存
        cache.save_historical_data(df, symbol, period, "index")
    
    return df


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
    # 避免除零错误
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    # 当 loss 为 0 时（连续上涨），RSI 设为 100
    df.loc[loss == 0, 'RSI'] = 100
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
    # 避免除零错误（当最高价等于最低价时）
    denominator = high_max - low_min
    df['Stoch_K'] = np.where(
        denominator != 0,
        100 * (df['收盘'] - low_min) / denominator,
        50  # 横盘时默认为中间值
    )
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
    # 避免除零错误
    df['+DI'] = 100 * (df['+DM'].rolling(window=window).sum() / df['TR_smooth'].replace(0, np.nan))
    df['-DI'] = 100 * (df['-DM'].rolling(window=window).sum() / df['TR_smooth'].replace(0, np.nan))
    di_sum = df['+DI'] + df['-DI']
    df['DX'] = np.where(di_sum != 0, 100 * abs(df['+DI'] - df['-DI']) / di_sum, 0)
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
    
    # RSI (检查 NaN)
    if pd.isna(latest['RSI']):
        signals.append("RSI数据不足")
    elif latest['RSI'] < 30:
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
    
    # MACD (检查 NaN)
    if pd.isna(latest['MACD']) or pd.isna(latest['MACD_signal']):
        signals.append("MACD数据不足")
    elif latest['MACD'] > latest['MACD_signal'] and latest['MACD_hist'] > prev['MACD_hist']:
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
    ema200 = latest.get('EMA200', np.nan)
    if pd.notna(latest['EMA50']) and pd.notna(ema200):
        if latest['收盘'] > latest['EMA50'] > ema200:
            score += 2
            signals.append("多头排列(+2)")
        elif latest['收盘'] < latest['EMA50']:
            score -= 1
            signals.append("价格<EMA50(-1)")
    elif pd.notna(latest['EMA50']) and latest['收盘'] < latest['EMA50']:
        score -= 1
        signals.append("价格<EMA50(-1)")
    
    # 随机指标 (检查 NaN)
    if pd.isna(latest['Stoch_K']):
        signals.append("KDJ数据不足")
    elif latest['Stoch_K'] < 20:
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
        ),
        Tool(
            name="cache_stats",
            description="获取缓存统计信息，查看已缓存的历史数据文件",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="clear_cache",
            description="清空缓存数据",
            inputSchema={
                "type": "object",
                "properties": {
                    "cache_type": {
                        "type": "string",
                        "enum": ["memory", "local", "all"],
                        "default": "memory",
                        "description": "缓存类型: memory(内存缓存), local(本地历史数据), all(全部)"
                    },
                    "symbol": {
                        "type": "string",
                        "description": "可选，指定清空某个股票的缓存"
                    }
                }
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
        elif name == "cache_stats":
            result = await get_cache_stats()
        elif name == "clear_cache":
            result = await clear_cache(
                arguments.get("cache_type", "memory"),
                arguments.get("symbol")
            )
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
    # 输入验证
    if not symbol or not symbol.isdigit() or len(symbol) != 6:
        return {"error": f"Invalid symbol format: {symbol}. Must be 6 digits."}
    
    # 限制 days 范围
    days = max(30, min(days, 3650))  # 30天 ~ 10年
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
    # 获取历史数据（使用本地缓存）
    try:
        df = get_stock_history_cached(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"
        )
    except Exception as e:
        return {"error": f"Failed to fetch data for {symbol}: {str(e)}"}
    
    if df.empty:
        return {"error": f"No data found for {symbol}"}
    
    # 检查数据量是否足够计算技术指标
    min_required = 30  # 至少需要30条数据
    if len(df) < min_required:
        return {"error": f"Insufficient data for {symbol}: only {len(df)} records, need at least {min_required}"}
    
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
        df = get_realtime_quotes_cached()
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
    df = get_realtime_quotes_cached()
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
    df = get_realtime_quotes_cached()
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
    df = get_realtime_quotes_cached()
    
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
    
    # 获取指数历史数据（使用本地缓存）
    try:
        df = get_index_history_cached(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date
        )
    except Exception as e:
        return {"error": f"Failed to fetch index data for {symbol}: {str(e)}"}
    
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
        # 使用新的接口名称
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        latest = df.iloc[-1] if not df.empty else None
        
        if latest is None:
            return {"error": "No north flow data available"}
        
        # 安全获取列值的辅助函数
        def safe_get(series, key, default=0):
            if key in series.index:
                val = series[key]
                return float(val) if pd.notna(val) else default
            return default
        
        return {
            "type": "north_flow",
            "date": str(latest['日期']),
            "net_inflow": safe_get(latest, '当日成交净买额'),
            "buy_amount": safe_get(latest, '买入成交额'),
            "sell_amount": safe_get(latest, '卖出成交额'),
            "accumulated": safe_get(latest, '历史累计净买额'),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


async def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    stats = cache.get_cache_stats()
    return {
        "type": "cache_stats",
        "memory_cache_keys": stats["memory_cache_keys"],
        "cache_directory": stats["cache_dir"],
        "local_cache_files": stats["local_files"],
        "total_files": len(stats["local_files"]),
        "total_size_kb": round(sum(f["size_kb"] for f in stats["local_files"]), 2),
        "timestamp": datetime.now().isoformat()
    }


async def clear_cache(cache_type: str = "memory", symbol: str = None) -> dict:
    """清空缓存"""
    result = {
        "type": "clear_cache",
        "cache_type": cache_type,
        "timestamp": datetime.now().isoformat()
    }
    
    if cache_type in ("memory", "all"):
        cache.clear_memory_cache()
        result["memory_cleared"] = True
    
    if cache_type in ("local", "all"):
        deleted_count = cache.clear_local_cache(symbol)
        result["local_files_deleted"] = deleted_count
        if symbol:
            result["symbol"] = symbol
    
    return result


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
