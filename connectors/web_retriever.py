#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络检索器 - 支持多引擎(Tavily/百度) + LRU缓存"""

from __future__ import annotations

import requests
import hashlib
import time
from typing import Dict, List, Optional, Any
from collections import OrderedDict


class WebSearchCache:
    """LRU 缓存 - 基于 query + max_results 生成缓存键"""

    def __init__(self, max_size: int = 200, ttl_seconds: int = 300):
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl_seconds

    def _key(self, query: str, max_results: int) -> str:
        """生成缓存键: 归一化 query + 结果数"""
        # 归一化: 去除首尾空格,转小写
        norm = query.strip().lower()
        # MD5 取前 16 位作为键
        key = hashlib.md5(f"{norm}:{max_results}".encode()).hexdigest()[:16]
        return key

    def get(self, query: str, max_results: int) -> Optional[List[Dict]]:
        """获取缓存结果"""
        k = self._key(query, max_results)
        entry = self._store.get(k)
        if entry is None:
            return None

        # 检查是否过期
        if time.time() - entry["ts"] > self.ttl:
            del self._store[k]
            return None

        # LRU: 访问时移动到末尾
        self._store.move_to_end(k)
        return entry["results"]

    def set(self, query: str, max_results: int, results: List[Dict]):
        """设置缓存"""
        k = self._key(query, max_results)
        self._store[k] = {
            "ts": time.time(),
            "results": results
        }

        # 超过容量时移除最老的(首项)
        if len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def clear(self):
        """清空缓存"""
        self._store.clear()


class WebRetriever:
    """网络检索器 - 统一接口,支持多引擎"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化检索器

        Args:
            config: 配置字典,格式参考 ai_config.json 中的 web_search 节
        """
        self.enabled = config.get("enabled", False)
        self.engines = config.get("engines", [])
        self.cache_config = config.get("cache", {})

        # 初始化缓存
        cache_enabled = self.cache_config.get("enabled", True)
        if cache_enabled:
            self.cache = WebSearchCache(
                max_size=self.cache_config.get("max_size", 200),
                ttl_seconds=self.cache_config.get("ttl_seconds", 300)
            )
        else:
            self.cache = None

        # Tavily 配置
        tavily_config = config.get("tavily", {})
        self.tavily_api_key = tavily_config.get("api_key", "")
        self.tavily_max_results = tavily_config.get("max_results", 3)
        self.tavily_include_answer = tavily_config.get("include_answer", True)

        # 百度配置(待实现)
        baidu_config = config.get("baidu", {})
        self.baidu_api_key = baidu_config.get("api_key", "")
        self.baidu_secret = baidu_config.get("secret", "")

        if not self.enabled:
            print("[WebRetriever] 网络检索功能已禁用")
        elif not self.tavily_api_key and "tavily" in self.engines:
            print("[WebRetriever] 警告: Tavily 已启用但未配置 API Key")

    def _search_tavily(self, query: str, max_results: int, timeout: float = 2.0) -> List[Dict]:
        """
        使用 Tavily API 检索

        Args:
            query: 查询字符串
            max_results: 最大结果数
            timeout: 超时时间(秒)

        Returns:
            标准化结果列表: [{"title", "url", "content", "score"}]
        """
        if not self.tavily_api_key:
            return []

        url = "https://api.tavily.com/search"
        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": self.tavily_include_answer,
            "include_images": False,
            "include_raw_content": False,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()

            # 标准化结果格式
            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "score": item.get("score", 0.0),
                    "source": "tavily"
                })

            return results

        except requests.exceptions.Timeout:
            print(f"[WebRetriever] Tavily 请求超时 ({timeout}s)")
            return []
        except requests.exceptions.RequestException as e:
            print(f"[WebRetriever] Tavily 请求失败: {e}")
            return []
        except Exception as e:
            print(f"[WebRetriever] Tavily 解析失败: {e}")
            return []

    def _search_baidu(self, _query: str, _max_results: int, _timeout: float = 2.0) -> List[Dict]:
        """
        使用百度搜索 API 检索(待实现)

        Args:
            query: 查询字符串
            max_results: 最大结果数
            timeout: 超时时间(秒)

        Returns:
            标准化结果列表
        """
        # TODO: 实现百度搜索 API 集成
        print("[WebRetriever] 百度搜索 API 尚未实现")
        return []

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict]:
        """
        执行网络检索(多引擎支持 + 缓存)

        Args:
            query: 查询字符串
            max_results: 最大结果数(默认使用配置值)

        Returns:
            标准化结果列表: [{"title", "url", "content", "score"}]
        """
        if not self.enabled:
            return []

        if not query or not query.strip():
            return []

        # 使用配置的默认值
        if max_results is None:
            max_results = self.tavily_max_results

        # 1. 检查缓存
        if self.cache:
            cached = self.cache.get(query, max_results)
            if cached is not None:
                print(f"[WebRetriever] 缓存命中: {query}")
                return cached

        # 2. 执行检索(按引擎顺序尝试)
        all_results = []
        for engine in self.engines:
            try:
                if engine == "tavily":
                    results = self._search_tavily(query, max_results)
                elif engine == "baidu":
                    results = self._search_baidu(query, max_results)
                else:
                    continue

                if results:
                    all_results.extend(results)
                    # 成功则不再尝试其他引擎
                    break

            except Exception as e:
                print(f"[WebRetriever] 引擎 {engine} 检索失败: {e}")
                continue

        # 3. 去重并排序
        if all_results:
            # 按 URL 去重
            seen_urls = set()
            deduped = []
            for r in all_results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    deduped.append(r)

            # 按 score 排序(降序)
            deduped.sort(key=lambda x: x.get("score", 0), reverse=True)

            # 限制返回数量
            final_results = deduped[:max_results]

            # 4. 写入缓存
            if self.cache:
                self.cache.set(query, max_results, final_results)

            print(f"[WebRetriever] 检索成功: {query} -> {len(final_results)} 条结果")
            return final_results

        print(f"[WebRetriever] 检索无结果: {query}")
        return []

    def clear_cache(self):
        """清空缓存"""
        if self.cache:
            self.cache.clear()
            print("[WebRetriever] 缓存已清空")
