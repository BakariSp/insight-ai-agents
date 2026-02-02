# insight-ai-agents

AI Agent Service built with Flask + Anthropic Claude + MCP-style Skills.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Then edit .env with your API keys
```

## Run

```bash
python app.py
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/chat` | POST | Send message to agent |
| `/skills` | GET | List available skills |

### POST /chat

```json
{
  "message": "What is the weather today?",
  "conversation_id": "optional-id"
}
```

## Project Structure

```
├── app.py                 # Flask entry point
├── config.py              # Configuration
├── agents/
│   └── chat_agent.py      # Agent orchestration & tool-use loop
├── services/
│   └── anthropic_service.py  # Anthropic API wrapper
├── skills/
│   ├── base.py            # BaseSkill abstract class
│   ├── web_search.py      # Brave Search skill
│   └── memory.py          # Persistent memory skill
└── tests/
    └── test_app.py        # Basic tests
```

## Adding Skills

Create a new class extending `BaseSkill` in `skills/`, then register it in `agents/chat_agent.py`.
