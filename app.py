from flask import Flask, request, jsonify
from config import Config
from agents.chat_agent import ChatAgent

app = Flask(__name__)
app.config.from_object(Config)

chat_agent = ChatAgent()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/chat", methods=["POST"])
def chat():
    """Main chat endpoint. Accepts a message and returns agent response.

    Request body:
        {
            "message": "user message",
            "conversation_id": "optional-conversation-id"
        }
    """
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "message is required"}), 400

    message = data["message"]
    conversation_id = data.get("conversation_id")

    result = chat_agent.run(message, conversation_id=conversation_id)
    return jsonify(result)


@app.route("/skills", methods=["GET"])
def list_skills():
    """List all available skills/tools the agent can use."""
    skills = chat_agent.list_skills()
    return jsonify({"skills": skills})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=Config.DEBUG)
