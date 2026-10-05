"""Approved business actions against the supplied e-commerce schema."""
import sqlite3
from pathlib import Path
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from context import SessionContext
from gmail_tools import send_action_notification, notification_status

DB_PATH = Path(__file__).resolve().parents[2] / "ecommerce.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def owned_order(conn, order_id, email):
    return conn.execute(
        "SELECT o.id, o.user_id, o.status FROM orders o "
        "JOIN users u ON u.id = o.user_id WHERE o.id = ? AND u.email = ?",
        (order_id, email),
    ).fetchone()


def return_item(conn, order_id, product_name):
    rows = conn.execute(
        "SELECT oi.id FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "WHERE oi.order_id = ? AND p.name = ?", (order_id, product_name),
    ).fetchall()
    return rows[0] if len(rows) == 1 else None


def add_ticket(conn, order, context, subject, return_id=None):
    conn.execute(
        "INSERT INTO tickets (user_id, return_id, subject, status, thread_id, "
        "user_email, created_at, updated_at) "
        "VALUES (?, ?, ?, 'OPEN', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        (order['user_id'], return_id, subject,
         f"{context.user_email}:{context.conversation_id}", context.user_email),
    )


@tool
def cancel_order_action(order_id: str, runtime: ToolRuntime[SessionContext]) -> str:
    """Cancel an owned PLACED order after administrator approval."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        context = runtime.context
        order = owned_order(conn, order_id, context.user_email)
        if not order:
            return "I could not find that order for your account."
        if order['status'] != 'PLACED':
            return f"Order {order_id} cannot be cancelled because its current status is {order['status']}."
        conn.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order['id'],))
        conn.execute("UPDATE payments SET status = 'REFUNDED' WHERE order_id = ?", (order['id'],))
        add_ticket(conn, order, context, f"Order {order_id} cancelled after administrator approval.")
        conn.commit()
        confirmation = f"Order {order_id} has been successfully cancelled and the payment has been marked for refund."
        notification = send_action_notification(context.user_email, f"Cancellation approved: order {order_id}", confirmation)
        return confirmation + "\n" + notification_status(notification)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@tool
def create_return_action(order_id: str, product_name: str, reason: str,
                         runtime: ToolRuntime[SessionContext]) -> str:
    """Return an exact product from an owned SHIPPED/DELIVERED order after approval."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        context = runtime.context
        order = owned_order(conn, order_id, context.user_email)
        if not order:
            return "I could not find that order for your account."
        if order['status'] not in {'SHIPPED', 'DELIVERED'}:
            return f"A return cannot be created for order {order_id} because its current status is {order['status']}. Please cancel PLACED orders instead."
        if not reason.strip():
            return "A return cannot be created without a reason."
        item = return_item(conn, order['id'], product_name)
        if not item:
            return "A return cannot be created: the exact product was not uniquely found in this order."
        if conn.execute("SELECT id FROM returns WHERE order_item_id = ? AND status != 'REJECTED'", (item['id'],)).fetchone():
            return "A return cannot be created: this product already has an active return."
        cursor = conn.execute(
            "INSERT INTO returns (order_id, order_item_id, user_id, reason, status, requested_at, resolved_at) "
            "VALUES (?, ?, ?, ?, 'APPROVED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (order['id'], item['id'], order['user_id'], reason),
        )
        add_ticket(conn, order, context, f"Return for {product_name}: {reason}", cursor.lastrowid)
        # Preserve the assignment's full-order refund behavior.
        conn.execute("UPDATE payments SET status = 'REFUNDED' WHERE order_id = ?", (order['id'],))
        conn.commit()
        confirmation = f"Return request {cursor.lastrowid} for order {order_id} has been created successfully and the payment has been marked for refund."
        body = confirmation + f"\nProduct: {product_name}\nReason: {reason}"
        notification = send_action_notification(context.user_email, f"Return approved: order {order_id}", body)
        return confirmation + "\n" + notification_status(notification)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_action_tools():
    return [cancel_order_action, create_return_action]
