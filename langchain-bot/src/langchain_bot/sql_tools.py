from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_database():
    """
    Return the e-commerce SQLite database.

    ecommerce.db is located at the project root.
    """

    project_root = Path(__file__).resolve().parents[2]

    db_path = project_root / "ecommerce.db"

    return SQLDatabase.from_uri(
        f"sqlite:///{db_path}"
    )


# ---------------------------------------------------------
# SQL TOOLS
# ---------------------------------------------------------

def get_sql_tools():
    """
    Create and return the LangChain SQL toolkit tools.
    """

    db = get_database()

    llm = ChatOpenAI(
        model="gpt-4.1-mini",
        temperature=0
    )

    toolkit = SQLDatabaseToolkit(
        db=db,
        llm=llm
    )

    return toolkit.get_tools()

# if __name__ == "__main__":
#     tools = get_sql_tools()
#     print(tools)
