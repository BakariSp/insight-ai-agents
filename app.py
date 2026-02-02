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
            "conversation_id": "optional-conversation-id",
            "model": "optional-model-override, e.g. openai/gpt-4o"
        }
    """
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "message is required"}), 400

    message = data["message"]
    conversation_id = data.get("conversation_id")
    model = data.get("model")

    try:
        result = chat_agent.run(message, conversation_id=conversation_id, model=model)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/models", methods=["GET"])
def list_models():
    """List supported model examples and the current default."""
    return jsonify({
        "default": Config.LLM_MODEL,
        "examples": [
            "dashscope/qwen-max",
            "dashscope/qwen-plus",
            "dashscope/qwen-turbo",
            "zai/glm-4.7",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-20250514",
        ],
    })


@app.route("/skills", methods=["GET"])
def list_skills():
    """List all available skills/tools the agent can use."""
    skills = chat_agent.list_skills()
    return jsonify({"skills": skills})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=Config.DEBUG)
