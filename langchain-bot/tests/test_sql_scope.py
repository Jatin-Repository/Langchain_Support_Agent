"""Read isolation and write protection against real SQLite snapshots."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from langchain_bot import sql_tools

ROOT = Path(__file__).resolve().parents[1]


class SqlScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        with sqlite3.connect(root / 'ecommerce.db') as conn:
            conn.executescript((ROOT / 'ecommerce_setup.sql').read_text())
        patcher = patch.object(sql_tools, 'PROJECT_ROOT', root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_customer_cannot_read_another_customers_orders(self):
        with sql_tools.customer_database('sivaprasad.valluru@gmail.com') as db:
            self.assertIn('PLACED', db.run('SELECT status FROM orders WHERE id=13'))
            self.assertEqual(db.run('SELECT * FROM orders WHERE user_id=2'), '')
            self.assertEqual(db.run('SELECT * FROM users WHERE id=2'), '')
            self.assertNotIn('password', db.get_table_info(['users']))

    def test_writes_and_database_escape_are_denied(self):
        with sql_tools.customer_database('sivaprasad.valluru@gmail.com') as db:
            for query in ["UPDATE orders SET status='CANCELLED'", 'ATTACH DATABASE ":memory:" AS extra', 'PRAGMA database_list', "SELECT load_extension('a')"]:
                with self.subTest(query=query):
                    self.assertTrue(db.run_no_throw(query).startswith('Error:'))

    def test_unknown_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            with sql_tools.customer_database('unknown@example.com'):
                pass


if __name__ == '__main__':
    unittest.main()
