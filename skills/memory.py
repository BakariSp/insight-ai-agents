import json
import os
from skills.base import BaseSkill

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "memory.json")


class MemorySkill(BaseSkill):
    """Persistent key-value memory for the agent.

    Stores facts and user preferences in a local JSON file
    so the agent can recall them across conversations.
    """

    name = "memory"
    description = (
        "Store or retrieve information from persistent memory. "
        "Use action='store' to save a fact, action='retrieve' to look up a key, "
        "or action='list' to list all stored keys."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["store", "retrieve", "list"],
                "description": "The memory operation to perform.",
            },
            "key": {
                "type": "string",
                "description": "The key to store/retrieve (not needed for 'list').",
            },
            "value": {
                "type": "string",
                "description": "The value to store (only needed for 'store').",
            },
        },
        "required": ["action"],
    }

    def __init__(self):
        self._ensure_file()

    def _ensure_file(self):
        os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
        if not os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "w") as f:
                json.dump({}, f)

    def _load(self) -> dict:
        with open(MEMORY_FILE) as f:
            return json.load(f)

    def _save(self, data: dict):
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def execute(self, action: str, key: str = "", value: str = "") -> str:
        data = self._load()

        if action == "store":
            if not key:
                return "Error: 'key' is required for store action."
            data[key] = value
            self._save(data)
            return f"Stored: {key} = {value}"

        elif action == "retrieve":
            if not key:
                return "Error: 'key' is required for retrieve action."
            if key in data:
                return f"{key} = {data[key]}"
            return f"Key '{key}' not found in memory."

        elif action == "list":
            if not data:
                return "Memory is empty."
            return "Stored keys:\n" + "\n".join(f"  - {k}" for k in data)

        return f"Unknown action: {action}"
