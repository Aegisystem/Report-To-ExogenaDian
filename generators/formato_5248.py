"""Formato 5248 v1 - Ingresos contratos colaboración empresarial."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato5248(BaseFormato):
    CODIGO = "5248"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        if not self.ctx.es_participante_colaboracion:
            return []
        df_g = self._filtrar_aplicables(df)
        filas = []
        for _nit, sub in self._agrupar_por_tercero(df_g).items():
            info = self._info_tercero(sub)
            ibure, dred = self._sumas_positivas_y_devoluciones(sub, "base")
            if ibure <= 0 and dred <= 0:
                continue
            filas.append({
                "tcon": self.ctx.tipo_contrato,
                "cpt": self.ctx.concepto_default_1007,
                "tdoc": info["tdoc"],
                "nid": info["nid"],
                "apl1": info["apl1"],
                "apl2": info["apl2"],
                "nom1": info["nom1"],
                "nom2": info["nom2"],
                "raz": info["raz"],
                "pais": info["pais"],
                "ibure": ibure,
                "dred": dred,
                "idfi": self.ctx.id_fideicomiso,
                "tdopa": self.ctx.tdoc_participante,
                "nidpa": self.ctx.nit_participante,
            })
        return filas
