import sys
from pathlib import Path

# Add the leica directory to sys.path so `import lasx` works unchanged.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
