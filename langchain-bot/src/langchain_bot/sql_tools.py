"""SQL toolkit tools on an isolated, read-only customer snapshot.

The LLM cannot select the customer identity or query another customer's rows.
No password column or writable business connection is exposed.
"""
import sqlite3
from contextlib import contextmanager
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_openai import ChatOpenAI
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from context import SessionContext
from settings import PROJECT_ROOT


@contextmanager
def customer_database(email):
    source = sqlite3.connect(f"file:{PROJECT_ROOT / 'ecommerce.db'}?mode=ro", uri=True)
    target = sqlite3.connect(':memory:', check_same_thread=False)
    try:
        row = source.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if not row:
            raise ValueError('Authenticated customer not found.')
        uid = row[0]
        selections = {
            'users': ('SELECT id, email, full_name, role, created_at FROM users WHERE id = ?', (uid,)),
            'products': ('SELECT * FROM products', ()),
            'orders': ('SELECT * FROM orders WHERE user_id = ?', (uid,)),
            'order_items': ('SELECT * FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id = ?)', (uid,)),
            'payments': ('SELECT * FROM payments WHERE order_id IN (SELECT id FROM orders WHERE user_id = ?)', (uid,)),
            'returns': ('SELECT * FROM returns WHERE user_id = ?', (uid,)),
            'tickets': ('SELECT * FROM tickets WHERE user_id = ?', (uid,)),
            'pending_actions': ('SELECT * FROM pending_actions WHERE user_email = ?', (email,)),
        }
        for name, (query, params) in selections.items():
            cur = source.execute(query, params)
            columns = [d[0] for d in cur.description]
            types = {row[1]: row[2] or 'TEXT' for row in source.execute(f'PRAGMA table_info("{name}")')}
            target.execute(f'CREATE TABLE "{name}" (' + ', '.join(f'"{c}" {types[c]}' for c in columns) + ')')
            target.executemany(f'INSERT INTO "{name}" VALUES (' + ','.join('?' for _ in columns) + ')', cur.fetchall())
        target.commit()
        engine = create_engine('sqlite://', creator=lambda: target, poolclass=StaticPool)
        db = SQLDatabase(engine, sample_rows_in_table_info=2)
        # Deny all writes, attachments, pragmas and extension loading after reflection.
        def authorize(action, arg1, arg2, database, trigger):
            if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() != 'load_extension':
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_TRANSACTION:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        target.set_authorizer(authorize)
        try:
            yield db
        finally:
            engine.dispose()
    finally:
        source.close()
        target.close()


def get_sql_tools():
    @tool
    def sql_db_query(query: str, runtime: ToolRuntime[SessionContext]) -> str:
        """Execute read-only SQL on the authenticated customer's records. Use orders.id and users.id joins."""
        with customer_database(runtime.context.user_email) as db:
            return db.run_no_throw(query)

    @tool
    def sql_db_list_tables(runtime: ToolRuntime[SessionContext]) -> str:
        """List available customer-scoped tables."""
        with customer_database(runtime.context.user_email) as db:
            return ', '.join(db.get_usable_table_names())

    @tool
    def sql_db_schema(table_names: str, runtime: ToolRuntime[SessionContext]) -> str:
        """Inspect comma-separated table names and customer-scoped sample rows."""
        with customer_database(runtime.context.user_email) as db:
            return db.get_table_info_no_throw([n.strip() for n in table_names.split(',')])

    @tool
    def sql_db_query_checker(query: str, runtime: ToolRuntime[SessionContext]) -> str:
        """Check SQL syntax before executing a read-only query."""
        with customer_database(runtime.context.user_email) as db:
            toolkit = SQLDatabaseToolkit(db=db, llm=ChatOpenAI(model='gpt-4.1-mini', temperature=0))
            checker = next(t for t in toolkit.get_tools() if t.name == 'sql_db_query_checker')
            return checker.invoke({'query': query})

    return [sql_db_query, sql_db_list_tables, sql_db_schema, sql_db_query_checker]
