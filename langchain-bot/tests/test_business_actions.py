"""Database regressions; no LLM calls or Gmail sends required."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from langchain_bot import action_tools as actions, hitl_utils as hitl
from langchain_bot.context import SessionContext

ROOT = Path(__file__).resolve().parents[1]
EMAIL = 'sivaprasad.valluru@gmail.com'
THREAD = f'{EMAIL}:test-conversation'


class BusinessActionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'ecommerce.db'
        with sqlite3.connect(self.db) as conn:
            conn.executescript((ROOT / 'ecommerce_setup.sql').read_text())
        for module in (actions, hitl):
            patcher = patch.object(module, 'DB_PATH', self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime = SimpleNamespace(context=SessionContext(EMAIL, 'test-conversation'))
        mail = patch.object(actions, 'send_action_notification', return_value={'sent': True, 'message_id': 'test-message', 'error': None})
        self.mail = mail.start()
        self.addCleanup(mail.stop)

    def scalar(self, query):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(query).fetchone()[0]

    def interrupted(self, name='cancel_order_action', **args):
        return {'__interrupt__': [SimpleNamespace(value={'action_requests': [{'name': name, 'args': args}]})]}

    def test_cancel_updates_order_payment_and_ticket(self):
        result = actions.cancel_order_action.func('13', self.runtime)
        self.assertIn('successfully cancelled', result)
        self.assertEqual(self.scalar('SELECT status FROM orders WHERE id=13'), 'CANCELLED')
        self.assertEqual(self.scalar('SELECT status FROM payments WHERE order_id=13'), 'REFUNDED')
        self.assertEqual(self.scalar("SELECT count(*) FROM tickets WHERE thread_id='" + THREAD + "'"), 1)

    def test_other_customer_and_shipped_order_cannot_be_cancelled(self):
        self.assertIn('could not find', actions.cancel_order_action.func('11', self.runtime))
        self.assertIn('cannot be cancelled', actions.cancel_order_action.func('10', self.runtime))
        self.assertEqual(self.scalar('SELECT status FROM orders WHERE id=11'), 'PLACED')

    def test_return_links_real_item_and_prevents_duplicate(self):
        with sqlite3.connect(self.db) as conn:
            product = conn.execute('SELECT p.name FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=10 LIMIT 1').fetchone()[0]
        result = actions.create_return_action.func('10', product, 'Damaged', self.runtime)
        self.assertIn('created successfully', result)
        self.assertEqual(self.scalar("SELECT count(*) FROM returns WHERE order_id=10 AND status='APPROVED'"), 1)
        self.assertIn('already has', actions.create_return_action.func('10', product, 'Damaged', self.runtime))
        self.mail.assert_called_once()
        self.assertEqual(self.mail.call_args.args[0], EMAIL)
        self.assertIn('Return approved', self.mail.call_args.args[1])

    def test_invalid_product_and_placed_return_do_not_write(self):
        self.assertIn('cannot be created', actions.create_return_action.func('10', 'invented product', 'Damaged', self.runtime))
        self.assertIn('cannot be created', actions.create_return_action.func('13', 'Wireless Mouse', 'Damaged', self.runtime))
        self.assertEqual(self.scalar('SELECT count(*) FROM returns WHERE order_id IN (10,13)'), 0)

    def test_interrupt_migrates_legacy_constraints_and_deduplicates(self):
        # Recreate the uploaded table's old status constraints.
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TABLE pending_actions')
            conn.execute("CREATE TABLE pending_actions (id INTEGER PRIMARY KEY, thread_id TEXT, user_email TEXT, action_type TEXT CHECK(action_type IN ('CANCEL_ORDER','CREATE_RETURN')), order_id INTEGER, product_name TEXT, reason TEXT, status TEXT CHECK(status IN ('PENDING','APPROVED','REJECTED')), created_at TEXT, updated_at TEXT)")
        result = self.interrupted(order_id='13')
        pending = hitl.handle_interrupt(result, THREAD, EMAIL)
        self.assertIsNotNone(pending['pending_id'])
        self.assertTrue(hitl.handle_interrupt(result, THREAD, EMAIL)['duplicate'])
        hitl.update_pending_status(pending['pending_id'], 'FAILED')
        self.assertEqual(self.scalar('SELECT status FROM pending_actions'), 'FAILED')

    def test_invalid_interrupt_is_rejected_without_pending_row(self):
        with patch.object(hitl, '_resume_invalid_interrupt') as resume:
            result = hitl.handle_interrupt(self.interrupted(order_id='11'), THREAD, EMAIL)
        self.assertTrue(result['invalid'])
        resume.assert_called_once()
        self.assertEqual(self.scalar('SELECT count(*) FROM pending_actions'), 0)

    def test_resume_preserves_dataclass_customer_context_and_ignores_old_success(self):
        pending = hitl.handle_interrupt(self.interrupted(order_id='13'), THREAD, EMAIL)
        old = SimpleNamespace(id='old', name='cancel_order_action', content='successfully cancelled')
        failure = SimpleNamespace(id='new', name='cancel_order_action', content='cannot be cancelled')
        agent = SimpleNamespace(
            get_state=lambda config: SimpleNamespace(values={'messages':[old]}, tasks=[SimpleNamespace(interrupts=self.interrupted(order_id='13')['__interrupt__'])]),
            invoke=lambda command, **kwargs: self.capture(kwargs, old, failure),
        )
        with patch.object(hitl, 'get_agent', return_value=agent):
            with self.assertRaises(RuntimeError):
                hitl.resume_with_decision(THREAD, 'approve', EMAIL, 'test-conversation', pending['pending_id'])
        self.assertIsInstance(self.invocation['context'], SessionContext)
        self.assertEqual(self.invocation['context'].user_email, EMAIL)
        self.assertEqual(self.scalar('SELECT status FROM pending_actions'), 'FAILED')

    def test_successful_approval_marks_pending_row_approved(self):
        pending = hitl.handle_interrupt(self.interrupted(order_id='13'), THREAD, EMAIL)
        def invoke(command, **kwargs):
            result = actions.cancel_order_action.func('13', SimpleNamespace(context=kwargs['context']))
            return {'messages': [SimpleNamespace(id='completed', name='cancel_order_action', content=result)]}
        agent = SimpleNamespace(
            get_state=lambda config: SimpleNamespace(values={'messages': []}, tasks=[SimpleNamespace(interrupts=self.interrupted(order_id='13')['__interrupt__'])]),
            invoke=invoke,
        )
        with patch.object(hitl, 'get_agent', return_value=agent):
            hitl.resume_with_decision(THREAD, 'approve', EMAIL, 'test-conversation', pending['pending_id'])
        self.assertEqual(self.scalar('SELECT status FROM pending_actions'), 'APPROVED')
        self.assertEqual(self.scalar('SELECT status FROM orders WHERE id=13'), 'CANCELLED')

    def test_rejection_leaves_business_order_unchanged(self):
        pending = hitl.handle_interrupt(self.interrupted(order_id='13'), THREAD, EMAIL)
        agent = SimpleNamespace(
            get_state=lambda config: SimpleNamespace(values={'messages': []}, tasks=[SimpleNamespace(interrupts=self.interrupted(order_id='13')['__interrupt__'])]),
            invoke=lambda *args, **kwargs: {'messages': []},
        )
        with patch.object(hitl, 'get_agent', return_value=agent):
            hitl.resume_with_decision(THREAD, 'reject', EMAIL, 'test-conversation', pending['pending_id'])
        self.assertEqual(self.scalar('SELECT status FROM pending_actions'), 'REJECTED')
        self.assertEqual(self.scalar('SELECT status FROM orders WHERE id=13'), 'PLACED')

    def test_notification_runs_after_database_commit_to_original_customer(self):
        def send(email, subject, body):
            self.assertEqual(email, EMAIL)
            self.assertEqual(self.scalar('SELECT status FROM orders WHERE id=13'), 'CANCELLED')
            return {'sent': True, 'message_id': 'confirmed', 'error': None}
        self.mail.side_effect = send
        result = actions.cancel_order_action.func('13', self.runtime)
        self.assertIn('Email status: SENT', result)
        self.mail.assert_called_once()

    def test_email_failure_does_not_reverse_or_misclassify_action(self):
        self.mail.return_value = {'sent': False, 'message_id': None, 'error': 'HttpError: insufficient scopes'}
        result = actions.cancel_order_action.func('13', self.runtime)
        self.assertEqual(self.scalar('SELECT status FROM orders WHERE id=13'), 'CANCELLED')
        self.assertIn('Email status: NOT_SENT', result)
        self.assertTrue(hitl._result_contains_success({'messages': [SimpleNamespace(name='cancel_order_action', content=result)]}))

    def test_invalid_request_does_not_send_email(self):
        actions.cancel_order_action.func('11', self.runtime)
        self.mail.assert_not_called()

    def capture(self, kwargs, *messages):
        self.invocation = kwargs
        return {'messages':list(messages)}

    def test_resume_rejects_mismatched_identity(self):
        pending = hitl.handle_interrupt(self.interrupted(order_id='13'), THREAD, EMAIL)
        with self.assertRaises(ValueError):
            hitl.resume_with_decision('someone:else', 'approve', EMAIL, 'test-conversation', pending['pending_id'])


if __name__ == '__main__':
    unittest.main()
