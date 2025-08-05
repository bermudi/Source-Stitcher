---
trigger: always_on
---

# Install dependencies
uv sync
# Or 
uv add [OPTIONS] <PACKAGES>
# `uv run` does this by itself


# Run application (GUI mode)
uv run main.py
uv run python main.py

# Run in CLI mode
uv run main.py --cli /path/to/project --output result.md

# Type checking
uv run mypy src/


Using system python is STRICTLY FORBIDDEN.