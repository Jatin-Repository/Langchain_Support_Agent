 
 ## Changes
      1. Auto add email into the session.
 
 
 ## Project Contraol Flow Diagram
 
                     CUSTOMER
                        │
                        ▼
                Streamlit :8501
                        │
                        ▼
                 LangGraph Agent
                        │
              ┌─────────┴─────────┐
              │                   │
          SQL VERIFY          Normal query
              │
              ▼
       Valid cancellation/
           return?
              │
              ▼
      action_tool requested
              │
              ▼
   HumanInTheLoopMiddleware
              │
              │ INTERRUPT
              ▼
      checkpoints.sqlite
              │
              ├───────────────┐
              │               │
              ▼               ▼
      pending_actions      Customer
         SQLite           sees pending
              │
              │
              ▼
        Admin :8502
              │
       ┌──────┴──────┐
       │             │
    APPROVE        REJECT
       │             │
       ▼             ▼
 Command(resume)   Command(resume)
       │             │
       ▼             ▼
 action tool       action tool
 executes          is rejected
       │
       ▼
 SQL UPDATE
       │
       ├── orders
       ├── payments
       ├── returns
       └── tickets
       │
       ▼
 confirmation email
       │
       ▼
 customer thread resumes







## Project Structure


 langchain-bot/
│
├── .env
├── .gitignore
├── pyproject.toml
├── uv.lock
│
├── credentials.json              # Gmail OAuth client credentials
├── token.pickle                  # Generated after Gmail OAuth
│
├── ecommerce.db                  # Application database
├── checkpoints.sqlite            # LangGraph persistent checkpoints
├── chat_threads.json             # Conversation metadata
│
├── ecommerce_setup.sql           # DB schema / initialization
│
├── src/
│   └── langchain_bot/
│       │
│       ├── __init__.py
│       │
│       ├── app.py                # Customer Streamlit app :8501
│       ├── app_admin.py          # Admin HITL console :8502
│       │
│       ├── agent.py              # LangGraph agent
│       ├── context.py            # SessionContext / runtime identity
│       ├── middleware.py         # Model/tool logging middleware
│       │
│       ├── action_tools.py       # Cancel / return side-effect tools
│       ├── hitl_utils.py         # Interrupt + resume handling
│       │
│       ├── sql_tools.py          # SQLDatabase + SQL tools
│       ├── gmail_tools.py        # Gmail API + email tool
│       ├── ragg.py               # Policy RAG
│       ├── auth.py               # Login/authentication
│       │
│       └── data/
│           └── policies/
│               ├── returns.txt
│               ├── cancellation.txt
│               ├── refunds.txt
│               └── shipping.txt
│
└── README.md