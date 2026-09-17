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

class TopSellingProduct(BaseModel):
    product_id: UUID
    sku: str
    name: str
    units_sold: Decimal
    sales_count: int
    revenue: Decimal

class TopSellingProductsResponse(BaseModel):
    period: AnalyticsPeriod
    customer_type: SalesCustomerType
    client_id: UUID | None
    supplier_id: UUID | None
    product_id: UUID | None
    start_date: date
    end_date: date
    products: list[TopSellingProduct]

class ProductCreationTrendPoint(BaseModel):
    period_start: date
    period_label: str
    created_products: int
    active_products: int
    inactive_products: int

class ProductCreationTrendResponse(BaseModel):
    period: AnalyticsPeriod
    window: AnalyticsWindow
    supplier_id: UUID | None
    active_only: bool | None
    start_date: date
    end_date: date
    total_created: int
    points: list[ProductCreationTrendPoint]