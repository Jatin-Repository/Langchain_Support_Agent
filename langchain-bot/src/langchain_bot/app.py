import streamlit as st
from dotenv import load_dotenv
from uuid import uuid4

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from auth import authenticate_user


def get_llm():
    return ChatOpenAI(
        model="gpt-4.1-mini",
        temperature=0.3
    )


def build_chain(llm):
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a concise, helpful assistant. "
                "Use prior chat history to stay on context."
            ),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}")
        ]
    )

    return prompt | llm


def init_session():
    st.session_state.setdefault("conversations", {})
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("user_email", None)
    st.session_state.setdefault("user_role", None)
    st.session_state.setdefault("conversation_id", None)


def start_new_conversation():
    conversation_id = str(uuid4())

    messages = [
        AIMessage(content="Hi! Ask me anything.")
    ]

    st.session_state.conversations[conversation_id] = messages.copy()
    st.session_state.messages = messages.copy()
    st.session_state.conversation_id = conversation_id


def load_conversation(conv_id):
    if conv_id in st.session_state.conversations:
        st.session_state.conversation_id = conv_id

        st.session_state.messages = (
            st.session_state.conversations[conv_id].copy()
        )


def render_history():
    for msg in st.session_state.messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        else:
            role = "assistant"

        with st.chat_message(role):
            st.markdown(msg.content)


def chat_round(llm, user_input):
    # Add user message to current conversation
    st.session_state.messages.append(
        HumanMessage(content=user_input)
    )

    chain = build_chain(llm)

    # Generate response
    response = chain.invoke(
        {
            "input": user_input,
            "history": st.session_state.messages
        }
    )

    # Add assistant response
    st.session_state.messages.append(response)

    # Persist updated messages to the current conversation
    conversation_id = st.session_state.conversation_id

    if conversation_id:
        st.session_state.conversations[conversation_id] = (
            st.session_state.messages.copy()
        )

    return response.content


def main():
    st.set_page_config(
        page_title="LangChain Bot",
        page_icon="🤖"
    )

    st.title("LangChain Bot")

    st.caption(
        "A simple conversational assistant powered by LangChain and OpenAI."
    )

    load_dotenv()
    init_session()

    # ---------------------------------------------------------
    # LOGIN
    # ---------------------------------------------------------

    user_email = st.session_state.user_email

    if not user_email:
        st.subheader("Login")

        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input(
                "Password",
                type="password"
            )

            role = st.selectbox(
                "Role",
                ["customer", "admin"]
            )

            submitted = st.form_submit_button("Login")

            if submitted:
                user = authenticate_user(
                    email=email,
                    password=password,
                    role=role
                )

                if user:
                    st.session_state.user_email = user["email"]
                    st.session_state.user_role = user["role"]

                    st.success("Login successful!")

                    st.rerun()

                else:
                    st.error(
                        "Invalid email, password, or role."
                    )

        return

    # ---------------------------------------------------------
    # SIDEBAR
    # ---------------------------------------------------------

    with st.sidebar:
        st.header("Conversations")

        # Create a new conversation
        if st.button(
            "Start new conversation",
            use_container_width=True
        ):
            start_new_conversation()
            st.rerun()

        conversations = st.session_state.conversations

        if conversations:
            conversation_options = list(
                conversations.keys()
            )

            current_conversation = (
                st.session_state.conversation_id
            )

            # Determine currently selected thread
            if current_conversation in conversation_options:
                current_index = conversation_options.index(
                    current_conversation
                )
            else:
                current_index = 0

            selected_conversation = st.selectbox(
                "Select conversation",
                conversation_options,
                index=current_index
            )

            # Load selected thread
            if selected_conversation != current_conversation:
                load_conversation(
                    selected_conversation
                )

                st.rerun()

        else:
            st.selectbox(
                "Select conversation",
                ["(no threads yet)"]
            )

    # ---------------------------------------------------------
    # CURRENT CONVERSATION INFORMATION
    # ---------------------------------------------------------

    conversation_id = (
        st.session_state.conversation_id
        or "—"
    )

    st.info(
        f"Logged in as: {st.session_state.user_email}  \n"
        f"Role: {st.session_state.user_role}  \n"
        f"Conversation: {conversation_id}"
    )

    # ---------------------------------------------------------
    # CHAT HISTORY
    # ---------------------------------------------------------

    render_history()

    # ---------------------------------------------------------
    # CHAT INPUT
    # ---------------------------------------------------------

    prompt = st.chat_input(
        "Ask a question"
    )

    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)

        llm = get_llm()

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = chat_round(
                    llm,
                    prompt
                )

                st.markdown(response)

        st.rerun()


if __name__ == "__main__":
    main()
