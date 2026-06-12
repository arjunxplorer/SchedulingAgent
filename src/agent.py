"""CLI entry point — thin wrapper around the graph runner."""

from src.graph_runner import (
    build_graph,
    create_default_model,
    default_session_state,
    get_current_time,
)


if __name__ == "__main__":
    model = create_default_model()
    graph = build_graph(model)
    session_state = default_session_state()

    print("Enter your tasks or events (type 'exit' to stop):")
    while True:
        user_input = input("\nTask/Event: ")
        if user_input.lower() == "exit":
            break

        try:
            session_state["user_input"] = user_input
            session_state["current_time"] = get_current_time.invoke({})
            session_state["intent"] = None
            session_state["schedule"] = ""
            session_state["feedback"] = ""
            session_state["rewrites"] = 0

            result = graph.invoke(session_state)

            # Persist state across turns
            session_state.update(result)

            # Track conversation history
            response_text = result.get("feedback", "")
            session_state["conversation_history"].append({
                "user": user_input,
                "response": response_text,
            })

            if response_text:
                print(f"\n{response_text}")
        except Exception as e:
            print(f"Error: {e}")
