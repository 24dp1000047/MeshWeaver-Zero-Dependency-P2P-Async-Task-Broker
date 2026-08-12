# meshweaver/monitoring.py
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class ResourceStatus:
    node_id: str
    cpu_percent: float
    ram_percent: float
    timestamp: float
  
