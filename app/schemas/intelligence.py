from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator
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

    @model_validator(mode="after")
    def validate_filter_compatibility(self):
        sales_filters_requested = (
            self.client_id is not None
            or self.customer_type != "all"
        )

        if self.scope in {"inventory", "catalog"} and sales_filters_requested:
            raise ValueError(
                "client_id and customer_type filters require a sales or business analysis"
            )

        if self.customer_type == "final_consumer" and self.client_id is not None:
            raise ValueError(
                "client_id cannot be combined with final_consumer customer_type"
            )

        if self.period == "custom":
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "custom period requires both start_date and end_date"
                )

        elif self.start_date is not None or self.end_date is not None:
            raise ValueError(
                "start_date and end_date are only valid with period=custom"
            )

        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date must be before or equal to end_date")

        return self

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