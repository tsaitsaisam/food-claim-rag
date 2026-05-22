"""Pydantic schemas for the three-part response.

Used in three places:
1. Passed to Gemini as `response_schema` to enforce structured output.
2. Validated after parse to guarantee the contract for the frontend.
3. Importable for tests / consumer code.
"""
from __future__ import annotations
from typing import List
from pydantic import BaseModel, Field


class Violation(BaseModel):
    issue: str = Field(..., description="宣稱中具體哪句話或哪個用語有問題")
    legal_basis: str = Field(..., description="對應法條（食安法第X條第X項 / 健康食品管理法第X條）")
    explanation: str = Field(..., description="為什麼這構成違規，引用上方法規片段")


class LegalAnalysis(BaseModel):
    summary: str = Field(..., description="一段話總結涉及哪些違規類型")
    violations: List[Violation] = Field(default_factory=list, description="逐點違規列表")


class SimilarCase(BaseModel):
    year_month: str = Field(..., description="例如 114年5月")
    product: str = Field(..., description="產品名稱")
    company: str = Field(..., description="處分商號")
    fine: str = Field(..., description="罰鍰，含單位")
    penalty_basis: str = Field(..., description="罰則註記，食安法第幾條第幾項")
    key_violation_phrase: str = Field(..., description="該案違規宣稱的關鍵語句節錄")


class SuggestedRevision(BaseModel):
    revised_text: str = Field(..., description="改寫後的合法宣稱完整文字")
    changes_explained: List[str] = Field(default_factory=list, description="逐項修改說明")


class ComplianceResponse(BaseModel):
    """完整三段式回應。Gemini 必須輸出符合此 schema 的 JSON。"""
    legal_analysis: LegalAnalysis
    similar_cases: List[SimilarCase] = Field(default_factory=list, description="2-3 件，從 <cases> 來，不可虛構")
    suggested_revision: SuggestedRevision

    def make_empty_safe(self) -> "ComplianceResponse":
        """確保前端永遠拿到非 None 結構（供 fallback 使用）。"""
        return self
