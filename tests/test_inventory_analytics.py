import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.services.inventory import (
    _aggregate_movement_rows,
    _rank_product_rows,
    _resolve_analytics_range,
)
from app.utils.exceptions import AppError


class InventoryAnalyticsTests(unittest.TestCase):
    def test_monthly_aggregation_includes_month_over_month_delta(self):
        product_id = uuid4()
        rows = [
            self._row(product_id, "SKU-1", "Cereal", "entrada_compra", "2026-01-03", 20, 20),
            self._row(product_id, "SKU-1", "Cereal", "salida_venta", "2026-01-20", 5, 15),
            self._row(product_id, "SKU-1", "Cereal", "salida_venta", "2026-02-05", 7, 8),
            self._row(product_id, "SKU-1", "Cereal", "entrada_manual", "2026-02-10", 4, 12),
        ]

        points = _aggregate_movement_rows(rows, window="month", include_previous=True)

        self.assertEqual([point["period_label"] for point in points], ["2026-01", "2026-02"])
        self.assertEqual(points[0]["net_quantity"], Decimal("15"))
        self.assertIsNone(points[0]["net_change_quantity"])
        self.assertEqual(points[1]["net_quantity"], Decimal("-3"))
        self.assertEqual(points[1]["previous_net_quantity"], Decimal("15"))
        self.assertEqual(points[1]["net_change_quantity"], Decimal("-18"))
        self.assertEqual(points[1]["net_change_percent"], Decimal("-120.00"))
        self.assertEqual(points[1]["ending_stock"], Decimal("12"))

    def test_weekly_trend_buckets_start_on_monday(self):
        product_id = uuid4()
        rows = [
            self._row(product_id, "SKU-1", "Cereal", "salida_venta", "2026-05-06", 2, 18),
            self._row(product_id, "SKU-1", "Cereal", "salida_venta", "2026-05-10", 3, 15),
        ]

        points = _aggregate_movement_rows(rows, window="week", include_previous=False)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["period_start"], date(2026, 5, 4))
        self.assertEqual(points[0]["outbound_quantity"], Decimal("5"))
        self.assertEqual(points[0]["movement_count"], 2)

    def test_product_ranking_supports_actionable_stock_risk_view(self):
        risky_id = uuid4()
        healthy_id = uuid4()
        rows = [
            self._row(risky_id, "SKU-R", "Arroz", "salida_venta", "2026-05-02", 8, 2, stock_minimo=10),
            self._row(healthy_id, "SKU-H", "Frijol", "salida_venta", "2026-05-02", 12, 40, stock_minimo=10),
        ]

        ranked = _rank_product_rows(rows, sort_by="stock_risk", limit=10)

        self.assertEqual(ranked[0]["product_id"], risky_id)
        self.assertGreater(ranked[0]["stock_risk_score"], ranked[1]["stock_risk_score"])

    def test_custom_period_requires_both_dates(self):
        with self.assertRaises(AppError):
            _resolve_analytics_range("custom", start_date=date(2026, 5, 1), end_date=None)

    def _row(
        self,
        product_id,
        sku,
        nombre,
        tipo_movimiento,
        fecha,
        cantidad,
        stock_resultante,
        *,
        stock_minimo=5,
    ):
        return {
            "producto_id": product_id,
            "sku": sku,
            "nombre": nombre,
            "tipo_movimiento": tipo_movimiento,
            "fecha": datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc),
            "cantidad": Decimal(str(cantidad)),
            "stock_resultante": Decimal(str(stock_resultante)),
            "stock_actual": Decimal(str(stock_resultante)),
            "stock_minimo": Decimal(str(stock_minimo)),
        }


if __name__ == "__main__":
    unittest.main()
