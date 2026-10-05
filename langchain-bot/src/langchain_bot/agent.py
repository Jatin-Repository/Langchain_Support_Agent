import os
import sqlite3

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, dynamic_prompt
from settings import checkpoint_path
from langgraph.checkpoint.sqlite import SqliteSaver

from context import SessionContext
from action_tools import get_action_tools

from middleware import get_logging_middleware
from rag_tools import search_policies
from sql_tools import get_sql_tools


_agent = None
_checkpointer = None


SYSTEM_PROMPT = """
You are an e-commerce customer support agent.

You have three categories of capability:

1. POLICY QUESTIONS

Use search_policies for general questions about company policies.

2. CUSTOMER DATA

Use SQL tools to retrieve customer-specific information such as:
- orders
- payments
- returns
- tickets
- purchase history

SECURITY:
- Only retrieve records belonging to the authenticated customer.
- The authenticated customer identity is provided through runtime context.
- Never expose another customer's data.
- Never invent order information.
- Use the minimum SQL required.
- Prefer precise queries over broad database exploration.
- Maximum SQL correction attempts for one request: 2.

3. CANCELLATION / RETURN

CANCELLATION FLOW:

Before calling cancel_order_action you MUST:

1. Identify the requested order ID.
2. Query SQL.
3. Verify that the order belongs to the authenticated customer.
4. Verify the CURRENT order status.
5. The order MUST have status PLACED.

If the order status is anything other than PLACED
(for example SHIPPED, DELIVERED, CANCELLED, etc.):

- DO NOT call cancel_order_action.
- Do not request administrator approval.
- Explain that cancellation is not available for the current status.

Only when the order is confirmed to be PLACED may you call
cancel_order_action.

Once a valid cancellation request is made:

- The cancellation action requires administrator approval.
- Do not claim cancellation has happened before approval.
- Do not claim cancellation has happened merely because the action
  tool was requested.

RETURN FLOW:

Before calling create_return_action you MUST:

1. Identify the requested order ID.
2. Query SQL.
3. Verify that the order belongs to the authenticated customer.
4. Verify the CURRENT order status.
5. Verify the product information when required.

If status is PLACED:

- DO NOT call create_return_action.
- Explain that the customer should request cancellation instead.

Returns are allowed only when status is:

- SHIPPED
- DELIVERED

For any other status:

- DO NOT call create_return_action.
- Explain that the return is not available.

Only when the order has been verified as SHIPPED or DELIVERED
may you call create_return_action.

HITL:

The following side-effecting actions require administrator approval:

- cancel_order_action
- create_return_action

Never attempt to bypass administrator approval.

ONE ACTION PER TURN:

For a single customer request, call at most one side-effecting
cancellation/return action.

DATABASE SIDE EFFECTS:

Never claim that a cancellation, return, refund, or ticket has happened
unless the corresponding action tool has actually completed successfully.

EMAIL:

The action tools automatically attempt one notification to the authenticated
customer AFTER the database transaction commits. Do not call another email tool.
Report the Email status returned by the action tool. SENT means Gmail accepted
the message, not that delivery to the recipient inbox has been verified.
NOT_SENT means the database action succeeded but its notification was not sent.
Never invent an email confirmation. Email failure does not reverse approval.

GENERAL:

Be concise and accurate.

Never invent order status.

Never assume an order is PLACED, SHIPPED, or DELIVERED without checking SQL.

For cancellation and return requests, SQL verification is mandatory
before requesting a protected action.
"""


@dynamic_prompt
def identity_prompt(request):
    import json
    context = request.runtime.context
    return SYSTEM_PROMPT + "\nAuthenticated customer email: " + json.dumps(context.user_email)


def get_checkpointer():
    global _checkpointer

    if _checkpointer is None:
        db_path = checkpoint_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
        )

        _checkpointer = SqliteSaver(conn=conn)
        _checkpointer.setup()

    return _checkpointer


def get_thread_config(user_email, conversation_id):
    return {
        "configurable": {
            "thread_id": f"{user_email}:{conversation_id}",
        },
        "recursion_limit": 20,
    }


def get_agent():
    global _agent

    if _agent is None:

        llm = ChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0,
            parallel_tool_calls=False,
        )

        tools = [
            search_policies,
            *get_sql_tools(),
            *get_action_tools(),
        ]

        hitl = HumanInTheLoopMiddleware(
            interrupt_on={
                "cancel_order_action": {
                    "allowed_decisions": [
                        "approve",
                        "reject",
                    ],
                    "description": (
                        "Administrator approval required to cancel "
                        "this order."
                    ),
                },
                "create_return_action": {
                    "allowed_decisions": [
                        "approve",
                        "reject",
                    ],
                    "description": (
                        "Administrator approval required to create "
                        "this return."
                    ),
                },
            }
        )

        _agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            context_schema=SessionContext,
            middleware=[
                identity_prompt,
                *get_logging_middleware(),
                hitl,
            ],
            checkpointer=get_checkpointer(),
        )

    return _agent


def reset_agent():
    global _agent
    _agent = None