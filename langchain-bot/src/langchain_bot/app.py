import json
import uuid
from pathlib import Path

import streamlit as st

from agent import get_agent, get_thread_config
from auth import authenticate_user
from context import SessionContext
from gmail_tools import initialize_gmail, is_gmail_available
from hitl_utils import handle_interrupt
from rag_tools import initialize_vector_store


# ============================================================
# Paths
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CHAT_THREADS_FILE = PROJECT_ROOT / "chat_threads.json"


# ============================================================
# Page configuration
# ============================================================

st.set_page_config(
    page_title="E-Commerce Support Agent",
    page_icon="🛒",
    layout="wide",
)


# ============================================================
# Session initialization
# ============================================================

def init_session():
    """
    Initialize Streamlit session state.

    LangGraph checkpointer remains the source of truth for
    conversation messages. Session state only stores UI state
    and conversation/thread identifiers.
    """

    st.session_state.setdefault("conversations", {})
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("user_email", None)
    st.session_state.setdefault("user_role", None)
    st.session_state.setdefault("conversation_id", None)

    st.session_state.setdefault(
        "pending_action_message",
        None,
    )

    st.session_state.setdefault(
        "logged_in",
        False,
    )


# ============================================================
# Conversation persistence
# ============================================================

def load_threads():
    """
    Load conversation metadata.

    The actual messages are NOT stored here.
    Messages come from the LangGraph checkpointer.
    """

    if not CHAT_THREADS_FILE.exists():
        return {}

    try:
        with open(
            CHAT_THREADS_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        cleaned = {}

        for email, threads in data.items():

            if not isinstance(threads, list):
                continue

            valid_threads = []

            for thread in threads:

                if not isinstance(thread, dict):
                    continue

                conversation_id = thread.get(
                    "conversation_id"
                )

                if not conversation_id:
                    continue

                valid_threads.append(
                    {
                        "conversation_id": conversation_id,
                        "title": thread.get(
                            "title",
                            "New Conversation",
                        ),
                    }
                )

            cleaned[email] = valid_threads

        return cleaned

    except Exception as exc:
        print(
            f"[CHAT] Failed to load conversations: {exc}"
        )
        return {}


def save_threads(threads):
    """
    Persist conversation metadata.
    """

    try:
        with open(
            CHAT_THREADS_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                threads,
                f,
                indent=2,
            )

    except Exception as exc:
        print(
            f"[CHAT] Failed to save conversations: {exc}"
        )


def add_thread(
    user_email,
    conversation_id,
    title="New Conversation",
):
    """
    Add a conversation to the user's conversation list.
    """

    conversations = load_threads()

    conversations.setdefault(
        user_email,
        [],
    )

    # Avoid duplicates.
    existing_ids = {
        thread.get("conversation_id")
        for thread in conversations[user_email]
        if isinstance(thread, dict)
    }

    if conversation_id not in existing_ids:

        conversations[user_email].insert(
            0,
            {
                "conversation_id": conversation_id,
                "title": title,
            },
        )

    save_threads(conversations)


def start_new_conversation():
    """
    Create a new conversation/thread.
    """

    user_email = st.session_state["user_email"]

    conversation_id = str(
        uuid.uuid4()
    )

    st.session_state["conversation_id"] = (
        conversation_id
    )

    st.session_state["messages"] = []

    st.session_state[
        "pending_action_message"
    ] = None

    add_thread(
        user_email=user_email,
        conversation_id=conversation_id,
        title="New Conversation",
    )

    return conversation_id


# ============================================================
# LangGraph state helpers
# ============================================================

def get_current_messages(config):
    """
    Read conversation messages from the LangGraph
    checkpointer.

    The checkpointer is the source of truth.
    """

    try:
        agent = get_agent()

        snapshot = agent.get_state(
            config
        )

        if not snapshot:
            return []

        values = getattr(
            snapshot,
            "values",
            None,
        )

        if not isinstance(values, dict):
            return []

        messages = values.get(
            "messages",
            [],
        )

        if not isinstance(messages, list):
            return []

        return messages

    except Exception as exc:

        print(
            f"[CHAT] Unable to read checkpoint state: {exc}"
        )

        return []


def has_pending_interrupt(config):
    """
    Check whether this LangGraph thread currently has
    an unresolved Human-In-The-Loop interrupt.

    This is critical because an interrupted tool call leaves
    an assistant tool-call message waiting for the corresponding
    tool response. Sending another user message on the same
    thread before resume can cause OpenAI to reject the message
    sequence.
    """

    try:

        agent = get_agent()

        snapshot = agent.get_state(
            config
        )

        if not snapshot:
            return False

        tasks = getattr(
            snapshot,
            "tasks",
            None,
        ) or []

        for task in tasks:

            interrupts = getattr(
                task,
                "interrupts",
                None,
            )

            if interrupts:
                return True

        return False

    except Exception as exc:

        print(
            f"[HITL] Unable to inspect interrupt state: {exc}"
        )

        return False


# ============================================================
# Message rendering
# ============================================================

def extract_message_content(message):
    """
    Extract displayable content from a LangChain message.
    """

    content = getattr(
        message,
        "content",
        "",
    )

    if isinstance(
        content,
        str,
    ):
        return content

    if isinstance(
        content,
        list,
    ):

        parts = []

        for item in content:

            if isinstance(
                item,
                dict,
            ):

                text_value = item.get(
                    "text"
                )

                if text_value:
                    parts.append(
                        str(text_value)
                    )

            elif isinstance(
                item,
                str,
            ):

                parts.append(item)

        return "\n".join(parts)

    return str(content)


def render_history():
    """
    Render conversation history from LangGraph checkpoint.
    """

    user_email = st.session_state[
        "user_email"
    ]

    conversation_id = st.session_state[
        "conversation_id"
    ]

    if not user_email or not conversation_id:
        return

    config = get_thread_config(
        user_email,
        conversation_id,
    )

    messages = get_current_messages(
        config
    )

    for message in messages:

        message_type = getattr(
            message,
            "type",
            "",
        )

        content = extract_message_content(
            message
        )

        if not content.strip():
            continue

        # Human/user messages
        if message_type == "human":

            with st.chat_message("user"):
                st.markdown(content)

        # AI messages
        elif message_type == "ai":

            # Avoid displaying empty tool-call-only AI messages.
            if content.strip():

                with st.chat_message("assistant"):
                    st.markdown(content)


# ============================================================
# Chat processing
# ============================================================

def chat_round(user_input):
    """
    Process one customer message.

    Customer messages are blocked when the thread is waiting
    for an administrator HITL decision.
    """

    agent = get_agent()

    user_email = st.session_state[
        "user_email"
    ]

    conversation_id = st.session_state[
        "conversation_id"
    ]

    user_role = st.session_state.get(
        "user_role",
        "customer",
    )

    config = get_thread_config(
        user_email,
        conversation_id,
    )

    thread_id = config[
        "configurable"
    ][
        "thread_id"
    ]

    # --------------------------------------------------------
    # CRITICAL HITL PROTECTION
    # --------------------------------------------------------

    if has_pending_interrupt(
        config
    ):

        message = (
            "⏳ Your cancellation/return request "
            "is already waiting for administrator "
            "approval."
        )

        st.session_state[
            "pending_action_message"
        ] = message

        st.warning(message)

        return

    # --------------------------------------------------------
    # Session context
    # --------------------------------------------------------

    context = SessionContext(
        user_email=user_email,
        conversation_id=conversation_id,
        role=user_role,
    )

    try:

        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": user_input,
                    }
                ]
            },
            config=config,
            context=context,
        )

        # ----------------------------------------------------
        # Check for HITL interruption
        # ----------------------------------------------------

        pending = handle_interrupt(
            result=result,
            thread_id=thread_id,
            user_email=user_email,
        )

        if pending:

            st.session_state[
                "pending_action_message"
            ] = pending.get(
                "message",
                "⏳ Your request is waiting "
                "for administrator approval.",
            )

        else:

            st.session_state[
                "pending_action_message"
            ] = None

    except Exception as exc:

        print(
            f"[CHAT] Agent invocation failed: {exc}"
        )

        st.error(
            "Something went wrong while processing "
            "your request."
        )

        st.session_state["pending_action_message"] = None
        return

    st.rerun()


# ============================================================
# Login
# ============================================================

def render_login():
    """
    Render login screen.
    """

    st.title(
        "🛒 E-Commerce Customer Support"
    )

    st.subheader(
        "Login"
    )

    with st.form(
        "login_form"
    ):

        email = st.text_input(
            "Email"
        )

        password = st.text_input(
            "Password",
            type="password",
        )

        submitted = st.form_submit_button(
            "Login",
            use_container_width=True,
        )

    if submitted:

        if not email or not password:

            st.error(
                "Please enter your email and password."
            )

            return

        try:

            user = authenticate_user(
                email,
                password,
            )

            if not user:

                st.error(
                    "Invalid email or password."
                )

                return

            st.session_state[
                "logged_in"
            ] = True

            st.session_state[
                "user_email"
            ] = user["email"]

            st.session_state[
                "user_role"
            ] = user.get(
                "role",
                "customer",
            )

            # ------------------------------------------------
            # Load user's existing conversations
            # ------------------------------------------------

            conversations = load_threads()

            user_threads = conversations.get(
                user["email"],
                [],
            )

            if user_threads:

                first_thread = user_threads[0]

                st.session_state[
                    "conversation_id"
                ] = first_thread[
                    "conversation_id"
                ]

            else:

                start_new_conversation()

            st.rerun()

        except Exception as exc:

            st.error(
                f"Login failed: {exc}"
            )


# ============================================================
# Sidebar
# ============================================================

def render_sidebar():
    """
    Render application sidebar.
    """

    with st.sidebar:

        st.title(
            "🛒 Support Agent"
        )

        st.divider()

        user_email = st.session_state[
            "user_email"
        ]

        user_role = st.session_state[
            "user_role"
        ]

        st.markdown(
            f"**User:** {user_email}"
        )

        st.markdown(
            f"**Role:** {user_role}"
        )

        st.divider()

        # ----------------------------------------------------
        # System status
        # ----------------------------------------------------

        st.subheader(
            "System Status"
        )

        try:

            st.success(
                "✓ LangGraph Agent"
            )

        except Exception:

            st.error(
                "✗ LangGraph Agent"
            )

        try:

            initialize_vector_store()

            st.success(
                "✓ Policy RAG"
            )

        except Exception as exc:

            st.warning(
                f"⚠ Policy RAG unavailable"
            )

            print(
                f"[RAG] {exc}"
            )

        if is_gmail_available():

            st.success(
                "✓ Gmail"
            )

        else:

            st.warning(
                "⚠ Gmail unavailable"
            )

        st.divider()

        # ----------------------------------------------------
        # New conversation
        # ----------------------------------------------------

        if st.button(
            "➕ New Conversation",
            use_container_width=True,
        ):

            start_new_conversation()

            st.rerun()

        st.subheader(
            "Conversations"
        )

        conversations = load_threads()

        threads = conversations.get(
            user_email,
            [],
        )

        current_id = st.session_state[
            "conversation_id"
        ]

        for thread in threads:

            if not isinstance(
                thread,
                dict,
            ):
                continue

            conversation_id = thread.get(
                "conversation_id"
            )

            if not conversation_id:
                continue

            title = thread.get(
                "title",
                "Conversation",
            )

            is_current = (
                conversation_id
                == current_id
            )

            label = (
                f"🟢 {title}"
                if is_current
                else title
            )

            if st.button(
                label,
                key=f"thread_{conversation_id}",
                use_container_width=True,
            ):

                st.session_state[
                    "conversation_id"
                ] = conversation_id

                st.session_state[
                    "pending_action_message"
                ] = None

                st.rerun()

        st.divider()

        # ----------------------------------------------------
        # Logout
        # ----------------------------------------------------

        if st.button(
            "Logout",
            use_container_width=True,
        ):

            st.session_state.clear()

            st.rerun()


# ============================================================
# Main application
# ============================================================

def main():

    init_session()

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    if not st.session_state.get(
        "logged_in",
        False,
    ):

        render_login()

        return

    # --------------------------------------------------------
    # Sidebar
    # --------------------------------------------------------

    render_sidebar()

    # --------------------------------------------------------
    # Main header
    # --------------------------------------------------------

    st.title(
        "🛒 E-Commerce Customer Support"
    )

    st.caption(
        "AI-powered customer support with policy search, "
        "order lookup, email assistance, and administrator "
        "approval for sensitive actions."
    )

    # --------------------------------------------------------
    # Initialize application services
    # --------------------------------------------------------

    try:

        initialize_vector_store()

    except Exception as exc:

        print(
            f"[RAG] Initialization failed: {exc}"
        )

    try:

        initialize_gmail()

    except Exception as exc:

        print(
            f"[GMAIL] Initialization failed: {exc}"
        )

    # --------------------------------------------------------
    # Conversation validation
    # --------------------------------------------------------

    if not st.session_state.get(
        "conversation_id"
    ):

        start_new_conversation()

    # --------------------------------------------------------
    # Render previous conversation
    # --------------------------------------------------------

    render_history()

    # --------------------------------------------------------
    # Pending action message
    # --------------------------------------------------------

    pending_message = st.session_state.get(
        "pending_action_message"
    )

    if pending_message and not has_pending_interrupt(get_thread_config(
        st.session_state["user_email"], st.session_state["conversation_id"]
    )) and "approval" in pending_message:
        pending_message = None
        st.session_state["pending_action_message"] = None

    if pending_message:

        st.info(
            pending_message
        )

    # --------------------------------------------------------
    # Check current HITL state
    # --------------------------------------------------------

    user_email = st.session_state[
        "user_email"
    ]

    conversation_id = st.session_state[
        "conversation_id"
    ]

    config = get_thread_config(
        user_email,
        conversation_id,
    )

    pending_interrupt = has_pending_interrupt(
        config
    )

    # --------------------------------------------------------
    # Customer input
    #
    # IMPORTANT:
    # Never accept another message while an action tool
    # is paused for administrator approval.
    # --------------------------------------------------------

    if pending_interrupt:

        st.warning(
            "⏳ Your cancellation/return request is "
            "waiting for administrator approval."
        )

        st.info(
            "You can continue chatting once the "
            "administrator has approved or rejected "
            "the request."
        )

        st.chat_input(
            "Waiting for administrator approval...",
            disabled=True,
        )

    else:
        st.session_state["pending_action_message"] = None
        user_input = st.chat_input(
            "How can I help you today?"
        )

        if user_input:

            # Display the user's new message immediately.
            with st.chat_message("user"):

                st.markdown(
                    user_input
                )

            chat_round(
                user_input
            )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()