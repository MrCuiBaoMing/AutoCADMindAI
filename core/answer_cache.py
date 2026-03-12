#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""答案缓存 - LRU 缓存 AI 生成的回答"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Optional, Dict, Any


class AnswerCache:
    """LRU 答案缓存 - 用于缓存 AI 生成结果,避免重复计算"""

    def __init__(self, max_size: int = 200, ttl_seconds: int = 300):
        """
        初始化缓存

        Args:
            max_size: 最大缓存条目数
            ttl_seconds: 缓存存活时间(秒)
        """
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl_seconds

    def _key(self, query: str, intent: str) -> str:
        """
        生成缓存键

        Args:
            query: 用户查询(归一化: 去除空格,转小写)
            intent: 意图类型(chat/kb_qa/command)

        Returns:
            MD5 哈希(前16位)
        """
        # 归一化: 去除首尾空格,转小写
        norm = query.strip().lower()
        key = hashlib.md5(f"{intent}:{norm}".encode()).hexdigest()[:16]
        return key

    def get(self, query: str, intent: str = "chat") -> Optional[str]:
        """
        获取缓存的回答

        Args:
            query: 用户查询
            intent: 意图类型

        Returns:
            缓存的回答文本,未命中返回 None
        """
        k = self._key(query, intent)
        entry = self._store.get(k)
        if entry is None:
            return None

        # 检查是否过期
        if time.time() - entry["ts"] > self.ttl:
            del self._store[k]
            return None

        # LRU: 访问时移动到末尾
        self._store.move_to_end(k)
        return entry["response"]

    def set(self, query: str, intent: str, response: str):
        """
        设置缓存

        Args:
            query: 用户查询
            intent: 意图类型
            response: AI 生成的回答
        """
        k = self._key(query, intent)
        self._store[k] = {
            "ts": time.time(),
            "response": response
        }

        # 超过容量时移除最老的(首项)
        if len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def clear(self):
        """清空缓存"""
        self._store.clear()

    def size(self) -> int:
        """获取当前缓存条目数"""
        return len(self._store)

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "size": len(self._store),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl,
            "utilization": f"{len(self._store) / self.max_size * 100:.1f}%"
        }
