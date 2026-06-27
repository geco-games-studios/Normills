from django.test import SimpleTestCase, override_settings

from .payment import (
    _format_zambian_phone,
    _lenco_authorization_header,
    best_lenco_data,
    normalize_lenco_response,
    process_lenco_payment,
)


class LencoPaymentHelperTests(SimpleTestCase):
    def test_best_lenco_data_prefers_final_status(self):
        response = {
            'status': True,
            'data': [
                {'status': 'pending', 'reference': 'pending-ref'},
                {'status': 'successful', 'reference': 'paid-ref'},
            ],
        }

        self.assertEqual(best_lenco_data(response)['reference'], 'paid-ref')

    def test_normalize_lenco_response_collapses_data_list_to_best_item(self):
        response = {
            'status': True,
            'data': [
                {'status': 'pending', 'reference': 'pending-ref'},
                {'status': 'failed', 'reference': 'failed-ref'},
            ],
        }

        normalized = normalize_lenco_response(response)

        self.assertEqual(normalized['data']['reference'], 'failed-ref')

    @override_settings(LENCO_API_KEY='secret-token')
    def test_lenco_authorization_header_adds_bearer_prefix(self):
        self.assertEqual(_lenco_authorization_header(), 'Bearer secret-token')

    @override_settings(LENCO_API_KEY='Bearer existing-token')
    def test_lenco_authorization_header_keeps_existing_bearer_prefix(self):
        self.assertEqual(_lenco_authorization_header(), 'Bearer existing-token')

    def test_format_zambian_phone_normalizes_local_numbers(self):
        self.assertEqual(_format_zambian_phone('0977 123 456'), '260977123456')
        self.assertEqual(_format_zambian_phone('977123456'), '260977123456')

    @override_settings(LENCO_API_KEY='')
    def test_process_lenco_payment_fails_cleanly_when_api_key_missing(self):
        response = process_lenco_payment('25.00', '0977123456', 'test-ref')

        self.assertFalse(response['status'])
        self.assertIn('not configured', response['message'])
