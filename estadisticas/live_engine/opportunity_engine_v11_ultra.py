"""V1.1 Ultra: copia calibrada/temporal de V1.1 para nivel Fuerte."""
from typing import Any, Dict, List

from .opportunity_engine_ultra_base import UltraMarketEvaluator


class LiveOpportunityEngineV11Ultra:
    """Copia experimental de V1.1 que inspecciona todos los mercados modelables."""

    MAX_STAKE = 15.0
    REQUIRED_LEVEL = 2

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        return UltraMarketEvaluator.evaluate(match, "V11U")
