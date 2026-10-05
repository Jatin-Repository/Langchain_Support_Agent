"""Gmail API requests are mocked; these tests do not send real email."""
import base64
from email import policy
from email.parser import BytesParser
import unittest
from unittest.mock import MagicMock, patch
from langchain_bot import gmail_tools as gmail


class NotificationTest(unittest.TestCase):
    def test_sends_expected_customer_recipient_subject_and_body(self):
        service = MagicMock()
        service.users.return_value.messages.return_value.send.return_value.execute.return_value = {'id': 'gmail-123'}
        with patch.object(gmail, 'initialize_gmail', return_value=True), patch.object(gmail, '_gmail_service', service):
            result = gmail.send_action_notification('customer@example.com', 'Return approved: order 10', 'Return committed.')
        self.assertTrue(result['sent'])
        params = service.users.return_value.messages.return_value.send.call_args.kwargs
        self.assertEqual(params['userId'], 'me')
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(params['body']['raw']))
        self.assertEqual(message['To'], 'customer@example.com')
        self.assertEqual(message['Subject'], 'Return approved: order 10')
        self.assertIn('Return committed.', message.get_content())

    def test_oauth_or_api_error_is_returned(self):
        service = MagicMock()
        service.users.return_value.messages.return_value.send.return_value.execute.side_effect = RuntimeError('insufficient permissions')
        with patch.object(gmail, 'initialize_gmail', return_value=True), patch.object(gmail, '_gmail_service', service):
            result = gmail.send_action_notification('customer@example.com', 'Approved', 'Done')
        self.assertFalse(result['sent'])
        self.assertIn('insufficient permissions', result['error'])

    def test_unconfigured_gmail_is_reported(self):
        with patch.object(gmail, 'initialize_gmail', return_value=False), patch.object(gmail, '_gmail_error', 'Missing credentials.json'):
            result = gmail.send_action_notification('customer@example.com', 'Approved', 'Done')
        self.assertFalse(result['sent'])
        self.assertEqual(result['error'], 'Missing credentials.json')

    def test_missing_message_id_does_not_claim_sent(self):
        service = MagicMock()
        service.users.return_value.messages.return_value.send.return_value.execute.return_value = {}
        with patch.object(gmail, 'initialize_gmail', return_value=True), patch.object(gmail, '_gmail_service', service):
            result = gmail.send_action_notification('customer@example.com', 'Approved', 'Done')
        self.assertFalse(result['sent'])


if __name__ == '__main__':
    unittest.main()
