import streamlit as st

from auth import authenticate_user
from hitl_utils import (
    list_pending_actions,
    resume_with_decision,
)


st.set_page_config(
    page_title="Admin Approval",
    page_icon="🔐",
    layout="wide",
)


def admin_login():
    st.title("🔐 Admin Approval Console")

    with st.form("admin_login"):
        email = st.text_input("Admin Email")
        password = st.text_input(
            "Password",
            type="password",
        )

        submitted = st.form_submit_button("Login")

    if not submitted:
        return False

    user = authenticate_user(email, password)

    if not user:
        st.error("Invalid email or password")
        return False

    if user["role"] != "admin":
        st.error("Administrator access required.")
        return False

    st.session_state["admin_user"] = user

    return True


def main():
    if "admin_user" not in st.session_state:
        if not admin_login():
            return

    admin = st.session_state["admin_user"]

    st.sidebar.success(
        f"Logged in as {admin['full_name']}"
    )

    if st.sidebar.button("Logout"):
        del st.session_state["admin_user"]
        st.rerun()

    st.title("Pending Customer Actions")

    col1, col2 = st.columns(2)

    with col1:
        status = st.selectbox(
            "Status",
            [
                "PENDING",
                "APPROVED",
                "REJECTED",
            ],
        )

    with col2:
        email_filter = st.text_input(
            "Customer email",
            placeholder="Optional",
        )

    rows = list_pending_actions(
        status=status,
        email=email_filter.strip() or None,
    )

    st.write(f"**{len(rows)} request(s)**")

    if not rows:
        st.info("No matching requests.")
        return

    for row in rows:
        action_label = (
            "Cancellation"
            if row["action_type"] == "cancel_order_action"
            else "Return"
        )

        with st.container(border=True):
            st.subheader(
                f"{action_label} — Order {row['order_id']}"
            )

            c1, c2 = st.columns(2)

            with c1:
                st.write(
                    f"**Customer:** {row['user_email']}"
                )
                st.write(
                    f"**Order:** {row['order_id']}"
                )
                st.write(
                    f"**Action:** {action_label}"
                )

            with c2:
                st.write(
                    f"**Thread:** `{row['thread_id']}`"
                )
                st.write(
                    f"**Status:** {row['status']}"
                )
                st.write(
                    f"**Created:** {row['created_at']}"
                )

            if row["product_name"]:
                st.write(
                    f"**Product:** {row['product_name']}"
                )

            if row["reason"]:
                st.write(
                    f"**Reason:** {row['reason']}"
                )

            if row["status"] == "PENDING":

                approve_col, reject_col = st.columns(2)

                with approve_col:
                    if st.button(
                        "✅ Approve",
                        key=f"approve_{row['id']}",
                        use_container_width=True,
                    ):
                        try:
                            with st.spinner(
                                "Approving action..."
                            ):
                                result = resume_with_decision(
                                    thread_id=row["thread_id"],
                                    decision="approve",
                                    user_email=row["user_email"],
                                    conversation_id=(
                                        row["thread_id"].split(":", 1)[1]
                                        if ":" in row["thread_id"]
                                        else row["thread_id"]
                                    ),
                                    pending_id=row["id"],
                                )

                            st.success(
                                "Action approved and executed."
                            )

                            st.rerun()

                        except Exception as exc:
                            st.error(
                                f"Approval failed: {exc}"
                            )

                with reject_col:
                    if st.button(
                        "❌ Reject",
                        key=f"reject_{row['id']}",
                        use_container_width=True,
                    ):
                        try:
                            with st.spinner(
                                "Rejecting action..."
                            ):
                                resume_with_decision(
                                    thread_id=row["thread_id"],
                                    decision="reject",
                                    user_email=row["user_email"],
                                    conversation_id=(
                                        row["thread_id"].split(":", 1)[1]
                                        if ":" in row["thread_id"]
                                        else row["thread_id"]
                                    ),
                                    pending_id=row["id"],
                                )

                            st.warning(
                                "Action rejected."
                            )

                            st.rerun()

                        except Exception as exc:
                            st.error(
                                f"Rejection failed: {exc}"
                            )


if __name__ == "__main__":
    main()