import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
import saas.models  # noqa: F401 - register metadata
from scripts import sync_paddle_price_ids
from saas import models as saas_models


def _valid_mapping():
    return {
        "environment": "sandbox",
        "provider": "paddle",
        "currency_code": "USD",
        "prices": {
            "starter": {
                "monthly": "pri_test_starter_monthly",
                "annual": "pri_test_starter_annual",
            },
            "professional": {
                "monthly": "pri_test_professional_monthly",
                "annual": "pri_test_professional_annual",
            },
            "enterprise_ai": {
                "monthly": "pri_test_enterprise_ai_monthly",
                "annual": "pri_test_enterprise_ai_annual",
            },
        },
    }


class PaddlePriceSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(bind=self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _price_ids(self):
        rows = self.db.query(saas_models.SubscriptionPlanPrice).order_by(
            saas_models.SubscriptionPlanPrice.plan_id.asc(),
            saas_models.SubscriptionPlanPrice.billing_interval.asc(),
        ).all()
        return [row.provider_price_id for row in rows]

    def test_valid_mapping_updates_all_required_rows(self):
        summary = sync_paddle_price_ids.sync_paddle_price_ids(self.db, _valid_mapping())

        self.assertEqual(len(summary), 6)
        self.assertTrue(all(price_id and price_id.startswith("pri_") for price_id in self._price_ids()))

    def test_dry_run_does_not_update_rows(self):
        summary = sync_paddle_price_ids.sync_paddle_price_ids(self.db, _valid_mapping(), dry_run=True)

        self.assertEqual(len(summary), 6)
        self.assertTrue(all(price_id is None for price_id in self._price_ids()))

    def test_missing_mapping_fails_closed(self):
        payload = _valid_mapping()
        del payload["prices"]["professional"]["annual"]

        with self.assertRaises(sync_paddle_price_ids.PaddlePriceSyncError):
            sync_paddle_price_ids.sync_paddle_price_ids(self.db, payload)

    def test_unknown_plan_code_fails_closed(self):
        payload = _valid_mapping()
        payload["prices"]["unknown"] = {"monthly": "pri_test_unknown_monthly"}

        with self.assertRaises(sync_paddle_price_ids.PaddlePriceSyncError):
            sync_paddle_price_ids.sync_paddle_price_ids(self.db, payload)

    def test_missing_price_row_fails_closed(self):
        professional = self.db.query(saas_models.SubscriptionPlan).filter_by(plan_code="professional").first()
        self.db.query(saas_models.SubscriptionPlanPrice).filter(
            saas_models.SubscriptionPlanPrice.plan_id == professional.id,
            saas_models.SubscriptionPlanPrice.billing_interval == "annual",
            saas_models.SubscriptionPlanPrice.currency_code == "USD",
        ).delete(synchronize_session=False)
        self.db.commit()

        with self.assertRaises(sync_paddle_price_ids.PaddlePriceSyncError):
            sync_paddle_price_ids.sync_paddle_price_ids(self.db, _valid_mapping())

    def test_invalid_price_id_shape_fails_closed(self):
        payload = _valid_mapping()
        payload["prices"]["starter"]["monthly"] = "price_not_paddle"

        with self.assertRaises(sync_paddle_price_ids.PaddlePriceSyncError):
            sync_paddle_price_ids.sync_paddle_price_ids(self.db, payload)


if __name__ == "__main__":
    unittest.main()
