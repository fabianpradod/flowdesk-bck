from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from app.schemas.analytics import SalesCustomerType
from app.schemas.inventory import AnalyticsPeriod

AnalysisScope = Literal["inventory", "sales", "catalog", "business"]
InsightSeverity = Literal["info", "warning", "critical"]
RecommendationPriority = Literal["low", "medium", "high"]

class IntelligentAnalysisRequest(BaseModel):
    scope: AnalysisScope = "inventory"
    period: AnalyticsPeriod = "30d"
    product_id: UUID | None = None
    supplier_id: UUID | None = None
    client_id: UUID | None = None
    customer_type: SalesCustomerType = "all"
    start_date: date | None = None
    end_date: date | None = None
    question: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized

    @field_validator("customer_type")
    @classmethod
    def validate_customer_filters(cls, value: SalesCustomerType, info):
        if value == "final_consumer" and info.data.get("client_id") is not None:
            raise ValueError("client_id cannot be combined with final_consumer customer_type")
        return value

class AnalysisInsight(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    severity: InsightSeverity = "info"

class AnalysisRecommendation(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    priority: RecommendationPriority = "medium"

class IntelligentAnalysisContent(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    insights: list[AnalysisInsight] = Field(default_factory=list, max_length=10)
    recommendations: list[AnalysisRecommendation] = Field(default_factory=list, max_length=10)

class IntelligentAnalysisResponse(BaseModel):
    analysis_id: UUID
    generated_at: datetime
    provider: str
    scope: AnalysisScope
    period: AnalyticsPeriod
    start_date: date
    end_date: date
    product_id: UUID | None
    analysis: IntelligentAnalysisContent