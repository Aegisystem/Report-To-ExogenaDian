"""Formato 5249 v1 - IVA descontable contratos colaboración."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato5249(BaseFormato):
    CODIGO = "5249"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        if not self.ctx.es_participante_colaboracion:
            return []
        df_g = self._filtrar_aplicables(df)
        filas = []
        for _nit, sub in self._agrupar_por_tercero(df_g).items():
            info = self._info_tercero(sub)
            ivad = self._suma_neta(sub, "iva")
            if ivad <= 0:
                continue
            filas.append({
                "tcon": self.ctx.tipo_contrato,
                "tdoc": info["tdoc"],
                "nid": info["nid"],
                "apl1": info["apl1"],
                "apl2": info["apl2"],
                "nom1": info["nom1"],
                "nom2": info["nom2"],
                "raz": info["raz"],
                "ivad": ivad,
                "ivar": 0,
                "tdopa": self.ctx.tdoc_participante,
                "nidpa": self.ctx.nit_participante,
            })
        return filas
