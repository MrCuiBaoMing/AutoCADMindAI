#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识检索器"""

from __future__ import annotations

from typing import Dict, List

from .db import KBSQLServerDB
from .repository import KBRepository


class KBRetriever:
    def __init__(self, connection_string: str):
        self.db = KBSQLServerDB(connection_string)
        self.repo = KBRepository(self.db)

    def list_domains(self) -> List[Dict]:
        return self.repo.list_domains()

    def list_docs(self, domain_code: str = "") -> List[Dict]:
        return self.repo.list_docs(domain_code=domain_code or "")

    def retrieve(self, query: str, top_k: int = 8, domain_code: str = "", doc_code: str = "") -> List[Dict]:
        if not query or not query.strip():
            return []
        return self.repo.search_chunks(query=query.strip(), top_k=top_k, domain_code=domain_code or "", doc_code=doc_code or "")

    def list_sections(self, doc_code: str, version_no: str = "") -> List[Dict]:
        return self.repo.list_sections(doc_code=doc_code or "", version_no=version_no or "")

    def retrieve_domain_candidates(self, query: str, top_n: int = 5) -> List[Dict]:
        if not query or not query.strip():
            return []
        return self.repo.search_domain_candidates(query=query.strip(), top_n=top_n)

    def retrieve_candidates(self, query: str, top_n: int = 5, domain_code: str = "") -> List[Dict]:
        if not query or not query.strip():
            return []
        return self.repo.search_document_candidates(query=query.strip(), top_n=top_n, domain_code=domain_code or "")
