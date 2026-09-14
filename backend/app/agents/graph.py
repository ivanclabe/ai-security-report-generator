from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from app.agents.nodes.analyze_data import analyze_data
from app.agents.nodes.answer_question import answer_question
from app.agents.nodes.ask_user import ask_user
from app.agents.nodes.collect_data import collect_data
from app.agents.nodes.generate_document import generate_document
from app.agents.nodes.generate_report_spec import generate_report_specification
from app.agents.nodes.return_result import return_result
from app.agents.nodes.understand_request import understand_request
from app.agents.nodes.validate_document import validate_document
from app.agents.nodes.validate_report_spec import validate_report_specification
from app.agents.state import ReportState


def _route_after_understanding(state: ReportState) -> str:
    if state.get("status") == "awaiting_user_input":
        return "ask_user"
    # Ad-hoc questions only take this path once a report already exists for the
    # conversation -- "profundizar en una alerta" presupposes there's data to dig
    # into. Without collected_data yet, fall through to the normal report flow.
    if state.get("intent") == "question" and state.get("collected_data"):
        return "answer_question"
    if state.get("data_refresh_required"):
        return "collect_data"
    return "generate_report_specification"


def _route_after_collect(state: ReportState) -> str:
    if state.get("status") == "awaiting_user_input":
        return "ask_user"
    return "analyze_data"


def _route_after_validation(state: ReportState) -> str:
    if state.get("status") == "error":
        return "return_result"
    return "generate_document"


def _route_after_document_validation(state: ReportState) -> str:
    return "return_result"


def build_graph():
    graph = StateGraph(ReportState)

    graph.add_node("understand_request", understand_request)
    graph.add_node("ask_user", ask_user)
    graph.add_node("answer_question", answer_question)
    graph.add_node("collect_data", collect_data)
    graph.add_node("analyze_data", analyze_data)
    graph.add_node("generate_report_specification", generate_report_specification)
    graph.add_node("validate_report_specification", validate_report_specification)
    graph.add_node("generate_document", generate_document)
    graph.add_node("validate_document", validate_document)
    graph.add_node("return_result", return_result)

    graph.set_entry_point("understand_request")

    graph.add_conditional_edges(
        "understand_request",
        _route_after_understanding,
        {
            "ask_user": "ask_user",
            "answer_question": "answer_question",
            "collect_data": "collect_data",
            "generate_report_specification": "generate_report_specification",
        },
    )

    graph.add_conditional_edges(
        "collect_data", _route_after_collect, {"ask_user": "ask_user", "analyze_data": "analyze_data"}
    )
    graph.add_edge("analyze_data", "generate_report_specification")
    graph.add_edge("generate_report_specification", "validate_report_specification")
    graph.add_conditional_edges(
        "validate_report_specification",
        _route_after_validation,
        {"generate_document": "generate_document", "return_result": "return_result"},
    )
    graph.add_edge("generate_document", "validate_document")
    graph.add_conditional_edges(
        "validate_document", _route_after_document_validation, {"return_result": "return_result"}
    )

    graph.add_edge("ask_user", END)
    graph.add_edge("answer_question", END)
    graph.add_edge("return_result", END)

    return graph


async def get_compiled_graph(checkpoint_db_path: str):
    saver_ctx = AsyncSqliteSaver.from_conn_string(checkpoint_db_path)
    saver = await saver_ctx.__aenter__()
    graph = build_graph().compile(checkpointer=saver)
    return graph, saver_ctx
