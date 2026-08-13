import sys
from pathlib import Path

# Корень репозитория в путях импорта, чтобы работал "from ai_assistant..."
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
