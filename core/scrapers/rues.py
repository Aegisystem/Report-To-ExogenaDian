"""Scraper del RUES (Registro Único Empresarial y Social) de Confecámaras.

Estado actual: el portal www.rues.org.co es una SPA Angular y los endpoints
HTTP públicos están protegidos por CloudFront/firewalls. La consulta directa
sin un navegador real es frágil.

Esta implementación intenta varios endpoints conocidos. Si todos fallan,
retorna None y deja un mensaje en `ULTIMO_ERROR`. La aplicación seguirá
funcionando: el usuario puede importar XMLs UBL o editar manualmente.

Para una solución 100% confiable, considerar:
  - Migrar a Selenium + chromedriver (pesado, requiere browser)
  - Contratar API paga (Datalegal, TuEmpresa, etc.)
  - Mantener este código actualizado revisando periódicamente los endpoints
"""
from __future__ import annotations

import re
import time
from typing import Any

import requests

from core import helpers


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
}

ULTIMO_ERROR: str | None = None


def consultar(nid: str, timeout: float = 8.0) -> dict[str, Any] | None:
    """Intenta varios endpoints conocidos del RUES.
    Devuelve dict con campos del directorio si encontró, None si no."""
    global ULTIMO_ERROR
    ULTIMO_ERROR = None

    if not nid or not nid.isdigit():
        ULTIMO_ERROR = "NIT inválido"
        return None

    # Estrategia 1: endpoint REST oficial actual de Confecámaras
    # (puede cambiar; mantener la lista actualizada)
    candidatos = [
        f"https://ruesapi.rues.org.co/api/Empresas/{nid}",
        f"https://ruesapi.rues.org.co/api/Search?nit={nid}",
    ]

    sess = requests.Session()
    sess.headers.update(_HEADERS)

    for url in candidatos:
        try:
            r = sess.get(url, timeout=timeout)
        except requests.RequestException as exc:
            ULTIMO_ERROR = f"{type(exc).__name__}: {exc}"
            continue

        if r.status_code != 200:
            continue
        ctype = r.headers.get("content-type", "").lower()
        if "json" not in ctype:
            continue

        try:
            data = r.json()
        except ValueError:
            continue

        parsed = _parsear_respuesta(data)
        if parsed:
            return parsed

    ULTIMO_ERROR = ULTIMO_ERROR or "Sin coincidencias en endpoints disponibles"
    return None


def _parsear_respuesta(data: Any) -> dict[str, Any] | None:
    """Normaliza la respuesta al formato del directorio.
    El esquema exacto del RUES varía entre versiones; se intentan claves comunes."""
    if not data:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None

    def get(keys: list[str]) -> str:
        for k in keys:
            v = data.get(k)
            if v not in (None, "", []):
                return str(v)
        return ""

    razon = get(["razon_social", "razonSocial", "nombre", "name", "Empresa"])
    dir_ = get(["direccion_comercial", "direccion", "direccionComercial", "DirComercial"])
    dpto_str = get(["codigo_departamento", "departamento", "dptoComercial", "CodDpto"])
    mun_str = get(["codigo_municipio", "municipio", "mcpComercial", "CodMcp"])

    out: dict[str, Any] = {}
    if razon:
        out["raz"] = razon[:450]
    if dir_:
        out["dir"] = dir_[:200]
    # Códigos DANE pueden venir como 5 dígitos (DDMMM) o por separado
    if mun_str and mun_str.isdigit():
        if len(mun_str) == 5:
            out["dpto"] = helpers.normalizar_departamento(mun_str)
            out["mun"] = helpers.normalizar_municipio(mun_str)
        elif len(mun_str) <= 3:
            out["mun"] = helpers.normalizar_municipio(mun_str)
    if dpto_str and dpto_str.isdigit() and "dpto" not in out:
        out["dpto"] = helpers.normalizar_departamento(dpto_str)

    out["pais"] = 169
    out["_fuente"] = "RUES"
    return out if (out.get("raz") or out.get("dir")) else None
