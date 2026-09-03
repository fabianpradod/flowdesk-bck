from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel
from app.schemas.inventory import AnalyticsPeriod, AnalyticsWindow

SalesCustomerType = Literal["all", "registered", "final_consumer"]
RiskLevel = Literal["critical", "high", "medium", "low", "healthy"]

class SalesMetricsResponse(BaseModel):
    period: AnalyticsPeriod
    customer_type: SalesCustomerType
    client_id: UUID | None
    start_date: date
    end_date: date
    sales_count: int
    gross_sales: Decimal
    discounts: Decimal
    taxes: Decimal
    net_sales: Decimal
    average_ticket: Decimal
    registered_customer_sales: int
    final_consumer_sales: int

class SalesTrendPoint(BaseModel):
    period_start: date
    period_label: str
    sales_count: int
    gross_sales: Decimal
    discounts: Decimal
    taxes: Decimal
    net_sales: Decimal
    average_ticket: Decimal

class SalesTrendResponse(BaseModel):
    period: AnalyticsPeriod
    window: AnalyticsWindow
    customer_type: SalesCustomerType
    client_id: UUID | None
    start_date: date
    end_date: date
    points: list[SalesTrendPoint]

class RiskDistributionBucket(BaseModel):
    level: RiskLevel
    product_count: int
    percentage: Decimal

class InventoryRiskDistributionResponse(BaseModel):
    period: AnalyticsPeriod
    supplier_id: UUID | None
    start_date: date
    end_date: date
    total_products: int
    distribution: list[RiskDistributionBucket]