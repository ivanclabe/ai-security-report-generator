from app.agents.state import ReportState


async def ask_user(state: ReportState) -> dict:
    return {
        "assistant_message": state["pending_question"],
        "status": "awaiting_user_input",
    }
