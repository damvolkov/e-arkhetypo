import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[3] / "stack" / "rag" / "docling-graph"
sys.path.insert(0, str(SERVICE))
