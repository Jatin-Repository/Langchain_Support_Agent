import sqlite3
from datetime import datetime
from pathlib import Path

from langgraph.types import Command

from agent import get_agent
from context import SessionContext
from action_tools import owned_order, return_item

ACTION_TYPES = {"cancel_order_action": "CANCEL_ORDER", "create_return_action": "CREATE_RETURN"}


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "ecommerce.db"


ACTION_NAMES = {
    "cancel_order_action",
    "create_return_action",
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_pending_actions_table(conn):
    """
    Make sure the business-level HITL table exists in the same
    ecommerce.db used by the customer and admin applications.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            user_email TEXT NOT NULL,
            action_type TEXT NOT NULL CHECK(action_type IN ('CANCEL_ORDER','CREATE_RETURN')),
            order_id TEXT NOT NULL,
            product_name TEXT,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED','FAILED')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    schema = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'pending_actions'").fetchone()[0]
    if "CHECK" in schema.upper() and "FAILED" not in schema.upper():
        conn.execute("ALTER TABLE pending_actions RENAME TO pending_actions_legacy")
        conn.execute("""CREATE TABLE pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
            user_email TEXT NOT NULL, action_type TEXT NOT NULL CHECK(action_type IN ('CANCEL_ORDER','CREATE_RETURN')),
            order_id INTEGER NOT NULL, product_name TEXT, reason TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED','FAILED')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id))""")
        conn.execute("INSERT INTO pending_actions SELECT * FROM pending_actions_legacy")
        conn.execute("DROP TABLE pending_actions_legacy")

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_actions_status
        ON pending_actions(status)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_actions_thread
        ON pending_actions(thread_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_actions_user
        ON pending_actions(user_email)
        """
    )

    conn.commit()


def extract_interrupt(result):
    """
    Return the first LangGraph interrupt payload, if present.
    """

    if not isinstance(result, dict):
        return None

    interrupts = result.get("__interrupt__", [])

    if not interrupts:
        return None

    interrupt = interrupts[0]

    return getattr(interrupt, "value", interrupt)


def _extract_action(interrupt_value):
    """
    Extract the first HITL action request.
    """

    if not isinstance(interrupt_value, dict):
        return {}

    action_requests = interrupt_value.get("action_requests", [])

    if not action_requests:
        return {}

    return action_requests[0]


def _validate_action(
    action_type,
    order_id,
    product_name,
    reason,
    user_email,
):
    """
    Validate a proposed side-effecting action BEFORE creating a
    business-level pending request.

    This is intentionally independent from the action tool because
    HumanInTheLoopMiddleware interrupts before the protected tool
    executes.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()

        order = owned_order(conn, order_id, user_email)

        if not order:
            return {
                "valid": False,
                "reason": "I could not find that order for your account.",
            }

        status = order["status"]

        if action_type == "cancel_order_action":

            if status != "PLACED":
                return {
                    "valid": False,
                    "reason": (
                        f"Order {order_id} cannot be cancelled because "
                        f"its current status is {status}."
                    ),
                }

            return {
                "valid": True,
                "reason": None,
            }

        if action_type == "create_return_action":

            if status == "PLACED":
                return {
                    "valid": False,
                    "reason": (
                        f"Order {order_id} is still PLACED. "
                        "A return cannot be created yet. "
                        "Please request cancellation instead."
                    ),
                }

            if status not in {"SHIPPED", "DELIVERED"}:
                return {
                    "valid": False,
                    "reason": (
                        f"A return cannot be created for order {order_id} "
                        f"because its current status is {status}."
                    ),
                }

            if not product_name:
                return {
                    "valid": False,
                    "reason": (
                        "I need the product name before I can create "
                        "a return request."
                    ),
                }

            if not reason:
                return {
                    "valid": False,
                    "reason": (
                        "I need the return reason before I can create "
                        "a return request."
                    ),
                }

            item = return_item(conn, order_id, product_name)
            if not item:
                return {"valid": False, "reason": "The exact product was not uniquely found in this order."}
            if conn.execute("SELECT id FROM returns WHERE order_item_id = ? AND status != 'REJECTED'", (item["id"],)).fetchone():
                return {"valid": False, "reason": "This product already has an active return."}
            return {"valid": True, "reason": None}

        return {
            "valid": False,
            "reason": "Unsupported action.",
        }

    finally:
        conn.close()


def _resume_invalid_interrupt(
    thread_id,
    user_email,
    conversation_id,
):
    """
    Clear an invalid protected tool request by rejecting the HITL
    decision immediately.

    No pending admin row is created.
    No side effect is performed.
    """

    agent = get_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": 20,
    }

    command = Command(
        resume={
            "decisions": [
                {
                    "type": "reject",
                }
            ]
        }
    )

    return agent.invoke(
        command,
        config=config,
        context=SessionContext(user_email, conversation_id, "customer"),
    )


def handle_interrupt(
    result,
    thread_id,
    user_email,
):
    """
    Persist a business-level pending action only when the requested
    action is actually valid.

    IMPORTANT:
    HumanInTheLoopMiddleware interrupts BEFORE a protected tool runs.
    Therefore we must re-check order status here before inserting the
    PENDING row.
    """

    interrupt_value = extract_interrupt(result)

    if not interrupt_value:
        return None

    action = _extract_action(interrupt_value)

    action_type = action.get("name")

    if action_type not in ACTION_NAMES:
        return None

    args = action.get("args", {}) or {}

    order_id = args.get("order_id")
    product_name = args.get("product_name")
    reason = args.get("reason")

    validation = _validate_action(
        action_type=action_type,
        order_id=order_id,
        product_name=product_name,
        reason=reason,
        user_email=user_email,
    )

    # ---------------------------------------------------------
    # INVALID ACTION
    # ---------------------------------------------------------
    #
    # Do NOT create a PENDING row.
    #
    # We still have an interrupted LangGraph thread, so reject
    # the interrupt immediately to allow the graph to continue.
    #
    if not validation["valid"]:

        conversation_id = (
            thread_id.split(":", 1)[1]
            if ":" in thread_id
            else thread_id
        )

        try:
            _resume_invalid_interrupt(
                thread_id=thread_id,
                user_email=user_email,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            print(
                "[HITL] Failed to clear invalid interrupt: "
                f"{type(exc).__name__}: {exc}"
            )

        return {
            "pending_id": None,
            "duplicate": False,
            "invalid": True,
            "message": validation["reason"],
        }

    # ---------------------------------------------------------
    # VALID ACTION
    # ---------------------------------------------------------

    action_type = ACTION_TYPES[action_type]
    conn = get_connection()

    try:
        _ensure_pending_actions_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()

        # Prevent duplicate pending requests.
        cursor.execute(
            """
            SELECT id
            FROM pending_actions
            WHERE thread_id = ?
              AND order_id = ?
              AND action_type = ?
              AND status = 'PENDING'
            LIMIT 1
            """,
            (
                thread_id,
                order_id,
                action_type,
            ),
        )

        existing = cursor.fetchone()

        if existing:
            return {
                "pending_id": existing["id"],
                "duplicate": True,
                "message": (
                    "Your request is already pending administrator approval."
                ),
            }

        now = datetime.utcnow().isoformat()

        cursor.execute(
            """
            INSERT INTO pending_actions (
                thread_id,
                user_email,
                action_type,
                order_id,
                product_name,
                reason,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                thread_id,
                user_email,
                action_type,
                order_id,
                product_name,
                reason,
                now,
                now,
            ),
        )

        pending_id = cursor.lastrowid

        conn.commit()

        readable_action = (
            "cancellation"
            if action_type == "CANCEL_ORDER"
            else "return"
        )

        return {
            "pending_id": pending_id,
            "duplicate": False,
            "invalid": False,
            "message": (
                f"Your {readable_action} request for order "
                f"`{order_id}` is pending administrator approval."
            ),
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def list_pending_actions(
    status="PENDING",
    email=None,
):
    conn = get_connection()

    try:
        _ensure_pending_actions_table(conn)

        cursor = conn.cursor()

        query = """
            SELECT
                id,
                thread_id,
                user_email,
                action_type,
                order_id,
                product_name,
                reason,
                status,
                created_at,
                updated_at
            FROM pending_actions
            WHERE status = ?
        """

        params = [status]

        if email:
            query += " AND user_email = ?"
            params.append(email)

        query += " ORDER BY created_at ASC"

        cursor.execute(query, params)

        return [dict(row) for row in cursor.fetchall()]

    finally:
        conn.close()


def get_pending_action(pending_id):
    conn = get_connection()

    try:
        _ensure_pending_actions_table(conn)

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT *
            FROM pending_actions
            WHERE id = ?
            """,
            (pending_id,),
        )

        row = cursor.fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


def update_pending_status(
    pending_id,
    status,
):
    conn = get_connection()

    try:
        _ensure_pending_actions_table(conn)

        conn.execute(
            """
            UPDATE pending_actions
            SET status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                datetime.utcnow().isoformat(),
                pending_id,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def _result_contains_success(result):
    """
    Best-effort check that the resumed graph actually contains a
    successful action-tool result.

    We inspect messages for ToolMessage content because approval itself
    is not proof that the database action succeeded.
    """

    if not isinstance(result, dict):
        return False

    messages = result.get("messages", [])

    for message in messages:
        tool_name = getattr(message, "name", None)

        if tool_name not in ACTION_NAMES:
            continue

        content = getattr(message, "content", "")

        if not isinstance(content, str):
            content = str(content)

        lowered = content.split("\nEmail status:", 1)[0].lower()

        failure_phrases = [
            "could not be cancelled",
            "cannot be cancelled",
            "could not find",
            "cannot be created",
            "cannot create",
            "failed",
            "error",
        ]

        if any(phrase in lowered for phrase in failure_phrases):
            return False

        success_phrases = [
            "successfully cancelled",
            "has been successfully cancelled",
            "created successfully",
        ]

        if any(phrase in lowered for phrase in success_phrases):
            return True

    return False


def resume_with_decision(
    thread_id,
    decision,
    user_email,
    conversation_id,
    pending_id=None,
):
    """
    Resume the exact interrupted LangGraph thread.

    approve:
        Resume the protected action and mark APPROVED only when the
        action actually succeeds.

    reject:
        Resume the interrupted graph with a rejection and mark REJECTED.
    """

    if decision not in {"approve", "reject"}:
        raise ValueError(
            "decision must be either 'approve' or 'reject'"
        )

    if pending_id is not None:
        pending = get_pending_action(pending_id)

        if not pending:
            raise ValueError(
                f"Pending action {pending_id} does not exist."
            )

        if (pending["thread_id"], pending["user_email"]) != (thread_id, user_email):
            raise ValueError("Pending action identity does not match the requested thread.")
        if thread_id != f"{user_email}:{conversation_id}":
            raise ValueError("Conversation does not match the pending thread.")
        if pending["status"] != "PENDING":
            raise ValueError(
                f"Pending action {pending_id} is already "
                f"{pending['status']}."
            )

    agent = get_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": 20,
    }

    command = Command(
        resume={
            "decisions": [
                {
                    "type": decision,
                }
            ]
        }
    )

    snapshot = agent.get_state(config)
    requests = []
    for task in snapshot.tasks:
        for interrupt in task.interrupts:
            requests.extend(interrupt.value.get("action_requests", []))
    if len(requests) != 1:
        raise ValueError("Expected exactly one live action awaiting approval.")
    if pending_id is not None:
        action = requests[0]
        args = action.get("args", {})
        if (ACTION_TYPES.get(action.get("name")) != pending["action_type"]
                or str(args.get("order_id")) != str(pending["order_id"])
                or args.get("product_name") != pending["product_name"]
                or args.get("reason") != pending["reason"]):
            raise ValueError("Pending row does not match the live interrupted action.")
    previous_ids = {getattr(m, "id", None) for m in snapshot.values.get("messages", [])}
    result = agent.invoke(
        command,
        config=config,
        context=SessionContext(user_email, conversation_id, "customer"),
    )

    if pending_id is not None:

        if decision == "reject":
            update_pending_status(
                pending_id,
                "REJECTED",
            )

        else:
            action_succeeded = _result_contains_success({"messages": [m for m in result.get("messages", []) if getattr(m, "id", None) not in previous_ids]})

            if action_succeeded:
                update_pending_status(
                    pending_id,
                    "APPROVED",
                )
            else:
                update_pending_status(
                    pending_id,
                    "FAILED",
                )

                raise RuntimeError(
                    "Administrator approval was recorded, but the "
                    "action did not complete successfully."
                )

    return result