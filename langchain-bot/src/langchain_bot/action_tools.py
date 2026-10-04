import sqlite3
from pathlib import Path

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from context import SessionContext


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "ecommerce.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def cancel_order_action(
    order_id: str,
    runtime: ToolRuntime[SessionContext],
) -> str:
    """
    Cancel a customer's PLACED order after administrator approval.

    This tool performs the actual database side effect only after HITL
    approval. It independently re-validates ownership and order status.
    """

    context = runtime.context
    user_email = context.user_email

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT order_id, user_email, status
            FROM orders
            WHERE order_id = ?
              AND user_email = ?
            """,
            (order_id, user_email),
        )

        order = cursor.fetchone()

        if not order:
            return "I could not find that order for your account."

        current_status = order["status"]

        if current_status != "PLACED":
            return (
                f"Order {order_id} cannot be cancelled because its "
                f"current status is {current_status}."
            )

        cursor.execute(
            """
            UPDATE orders
            SET status = 'CANCELLED'
            WHERE order_id = ?
              AND user_email = ?
              AND status = 'PLACED'
            """,
            (order_id, user_email),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            return "The order could not be cancelled."

        cursor.execute(
            """
            UPDATE payments
            SET status = 'REFUNDED'
            WHERE order_id = ?
            """,
            (order_id,),
        )

        cursor.execute(
            """
            INSERT INTO tickets (
                user_email,
                order_id,
                issue_type,
                status,
                description
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_email,
                order_id,
                "ORDER_CANCELLATION",
                "OPEN",
                "Order cancelled after administrator approval.",
            ),
        )

        conn.commit()

        return (
            f"Order {order_id} has been successfully cancelled and "
            f"the payment has been marked for refund."
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


@tool
def create_return_action(
    order_id: str,
    product_name: str,
    reason: str,
    runtime: ToolRuntime[SessionContext],
) -> str:
    """
    Create a return for a SHIPPED or DELIVERED order after administrator
    approval.

    This tool independently re-validates ownership and status before
    performing the database side effect.
    """

    context = runtime.context
    user_email = context.user_email

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT order_id, user_email, status
            FROM orders
            WHERE order_id = ?
              AND user_email = ?
            """,
            (order_id, user_email),
        )

        order = cursor.fetchone()

        if not order:
            return "I could not find that order for your account."

        order_status = order["status"]

        if order_status == "PLACED":
            return (
                f"Order {order_id} is still PLACED. "
                "A return cannot be created yet. "
                "Please request cancellation instead."
            )

        if order_status not in ("SHIPPED", "DELIVERED"):
            return (
                f"A return cannot be created for order {order_id} "
                f"because its current status is {order_status}."
            )

        cursor.execute(
            """
            INSERT INTO returns (
                order_id,
                user_email,
                product_name,
                reason,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_id,
                user_email,
                product_name,
                reason,
                "REQUESTED",
            ),
        )

        return_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO tickets (
                user_email,
                order_id,
                issue_type,
                status,
                description
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_email,
                order_id,
                "RETURN_REQUEST",
                "OPEN",
                f"Return requested for {product_name}. Reason: {reason}",
            ),
        )

        cursor.execute(
            """
            UPDATE payments
            SET status = 'REFUNDED'
            WHERE order_id = ?
            """,
            (order_id,),
        )

        conn.commit()

        return (
            f"Return request {return_id} for order {order_id} has been "
            f"created successfully and the payment has been marked for refund."
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_action_tools():
    return [
        cancel_order_action,
        create_return_action,
    ]