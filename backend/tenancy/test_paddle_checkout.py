from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .paddle_checkout import checkout_transaction_body, parse_checkout_transaction, verify_agency_catalog_price


class CheckoutContractTests(SimpleTestCase):
    def test_one_server_catalog_price_without_trial_currency_or_client_redirect(self):
        price = "pri_" + "a" * 26
        self.assertEqual(checkout_transaction_body(organization_id=17, price_id=price, attempt_id=19), {
            "items": [{"price_id": price, "quantity": 1}], "collection_mode": "automatic",
            "custom_data": {"organization_id": "17", "offer_version": "agency-launch-v1", "checkout_attempt_id": "19"},
        })
        for organization_id, price_id in ((0, price), (True, price), (17, "pri_other"),
                                          (17, "pri_" + "A" * 26), (17, None)):
            with self.subTest(organization_id=organization_id, price_id=price_id), self.assertRaises(ValidationError):
                checkout_transaction_body(organization_id=organization_id, price_id=price_id, attempt_id=19)

    def test_checkout_response_requires_exact_attempt_price_and_approved_link(self):
        class Attempt:
            pk = 19
            organization_id = 17
            price_id = "pri_" + "a" * 26

        attempt = Attempt()
        base = "https://app.example.com/account/billing/checkout"
        txn = "txn_" + "b" * 26
        response = {"data": {"id": txn, "status": "draft", "collection_mode": "automatic",
            "custom_data": checkout_transaction_body(organization_id=17, price_id=attempt.price_id, attempt_id=19)["custom_data"],
            "items": [{"price": {"id": attempt.price_id}, "quantity": 1}],
            "checkout": {"url": base + "?_ptxn=" + txn}}}
        self.assertEqual(parse_checkout_transaction(attempt=attempt, response=response, expected_checkout_base=base),
                         {"transaction_id": txn, "checkout_url": base + "?_ptxn=" + txn, "payment_confirmed": False})
        for field, bad in (("id", "txn_wrong"), ("status", "completed"), ("collection_mode", "manual"),
                           ("custom_data", {"organization_id": "18"}),
                           ("items", [{"price": {"id": attempt.price_id}, "quantity": 2}]),
                           ("checkout", {"url": "https://foreign.example/checkout?_ptxn=" + txn}),
                           ("checkout", {"url": base + "?_ptxn=" + txn + "&next=https://evil.example"})):
            with self.subTest(field=field, bad=bad), self.assertRaises(ValidationError):
                parse_checkout_transaction(attempt=attempt, response={"data": {**response["data"], field: bad}},
                                           expected_checkout_base=base)

    def test_current_provider_catalog_must_match_selected_recurring_offer(self):
        product_id, price_id = "pro_" + "a" * 26, "pri_" + "b" * 26
        response = {"data": {"id": price_id, "product_id": product_id, "type": "standard", "status": "active",
            "product": {"id": product_id, "type": "standard", "status": "active", "tax_category": "saas"},
            "billing_cycle": {"interval": "month", "frequency": 1}, "trial_period": None,
            "unit_price": {"amount": "14900", "currency_code": "USD"},
            "unit_price_overrides": [], "quantity": {"minimum": 1, "maximum": 1}}}
        self.assertEqual(verify_agency_catalog_price(product_id=product_id, price_id=price_id,
                                                    response=response)["amount"], "14900")
        changes = (("id", "pri_" + "c" * 26), ("product_id", "pro_" + "c" * 26),
                   ("type", "custom"), ("status", "archived"),
                   ("billing_cycle", {"interval": "year", "frequency": 1}),
                   ("billing_cycle", {"interval": "month", "frequency": True}),
                   ("trial_period", {"interval": "day", "frequency": 7}),
                   ("unit_price", {"amount": "14901", "currency_code": "USD"}),
                   ("unit_price", {"amount": "14900", "currency_code": "TRY"}),
                   ("unit_price_overrides", [{"unit_price": {"amount": "1"}}]),
                   ("quantity", {"minimum": 2, "maximum": 5}),
                   ("product", {"id": product_id, "type": "standard", "status": "archived", "tax_category": "saas"}),
                   ("product", {"id": product_id, "type": "standard", "status": "active", "tax_category": "digital-goods"}))
        for field, value in changes:
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                verify_agency_catalog_price(product_id=product_id, price_id=price_id,
                    response={"data": {**response["data"], field: value}})
        with self.assertRaises(ValidationError):
            verify_agency_catalog_price(product_id=product_id, price_id=price_id, response={"data": {}})
