"""V2.Ultra: V2 independiente, limitado a oportunidades de nivel Muy fuerte."""
from typing import Any, Dict, List

from .opportunity_engine_ultra_base import UltraMarketEvaluator


class LiveOpportunityEngineV2Ultra:
    """Copia experimental de V2 que inspecciona todos los mercados modelables."""

    MAX_STAKE = 20.0
    REQUIRED_LEVEL = 1

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        return UltraMarketEvaluator.evaluate(match, "V2U")
