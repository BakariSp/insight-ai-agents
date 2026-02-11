"""Thin wrapper to run QA tests with correct sys.path."""
import sys
import os

# Ensure insight-ai-agent is on the path
agent_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
venv_pkgs = os.path.join(agent_root, "venv", "Lib", "site-packages")

sys.path.insert(0, agent_root)
sys.path.insert(0, venv_pkgs)

os.chdir(agent_root)

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main(sys.argv[1:]))
