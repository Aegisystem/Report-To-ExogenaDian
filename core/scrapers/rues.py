"""Consulta de terceros en fuentes públicas tipo RUES.

El portal RUES cambia con frecuencia y parte de su front es una SPA. En vez de
depender de un solo endpoint, se consultan varias fuentes livianas:

1. API WEB2 de RUES, resolviendo primero cámara/matrícula desde datos.gov.co.
2. Endpoints antiguos de RUES, por compatibilidad.
3. RegistroNIT como fallback HTML para razón social/DV cuando RUES no responde.

La consulta no levanta navegador ni Selenium para mantener bajo el consumo del
servidor. Si ninguna fuente trae dirección, se guarda lo que sí sea confiable
(razón social/DV) y los XML UBL siguen siendo la mejor fuente de dirección.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any

import requests

from core import helpers


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
}
_SOCRATA_RUES = "https://www.datos.gov.co/resource/c82u-588k.json"
_DETALLE_RUES = "https://ruesapi.rues.org.co/WEB2/api/Expediente/DetalleRM/{expediente}"
_REGISTRO_NIT = "https://www.registronit.com/{nid}"

ULTIMO_ERROR: str | None = None


def consultar(nid: str, timeout: float = 8.0) -> dict[str, Any] | None:
    """Consulta datos básicos del tercero.

    Devuelve campos compatibles con el directorio: raz, dir, dpto, mun, pais,
    tdoc y dv. Puede devolver razón social/DV aunque la dirección no esté
    publicada por la fuente consultada.
    """
    global ULTIMO_ERROR
    ULTIMO_ERROR = None

    nid = helpers.normalizar_nit(nid)
    if not nid:
        ULTIMO_ERROR = "NIT inválido"
        return None

    sess = requests.Session()
    sess.headers.update(_HEADERS)
    errores: list[str] = []
    resultado: dict[str, Any] = {}

    for nid_busqueda in _nits_candidatos(nid):
        for nombre, estrategia in (
            ("RUES-WEB2", _consultar_rues_web2),
            ("RUES-legado", _consultar_rues_legado),
            ("RegistroNIT", _consultar_registronit),
        ):
            try:
                data = estrategia(sess, nid_busqueda, timeout)
            except requests.RequestException as exc:
                errores.append(f"{nombre}: {type(exc).__name__}: {exc}")
                continue
            except Exception as exc:
                errores.append(f"{nombre}: {type(exc).__name__}: {exc}")
                continue

            if not data:
                continue
            _merge(resultado, data)
            if _tiene_direccion(resultado):
                return resultado

    if _tiene_datos_utiles(resultado):
        return resultado

    ULTIMO_ERROR = " | ".join(errores) if errores else "Sin coincidencias en fuentes disponibles"
    return None


def _nits_candidatos(nid: str) -> list[str]:
    candidatos = [nid]
    if len(nid) > 8:
        base, posible_dv = nid[:-1], nid[-1]
        dv = helpers.calcular_dv(base)
        if dv is not None and str(dv) == posible_dv:
            candidatos.append(base)
    return list(dict.fromkeys(candidatos))


def _consultar_rues_web2(sess: requests.Session, nid: str, timeout: float) -> dict[str, Any] | None:
    registros = _buscar_en_datos_gov(sess, nid, timeout)
    if not registros:
        return None

    base = _parsear_registro_general(registros[0], "RUES-datos.gov.co")
    for registro in registros[:3]:
        expediente = _expediente_id(registro)
        if not expediente:
            continue
        detalle = _get_json(sess, _DETALLE_RUES.format(expediente=expediente), timeout=timeout)
        parsed = _parsear_respuesta(detalle, fuente="RUES-WEB2")
        if parsed:
            _merge(base, parsed)
            if _tiene_direccion(base):
                return base
    return base if _tiene_datos_utiles(base) else None


def _buscar_en_datos_gov(sess: requests.Session, nid: str, timeout: float) -> list[dict[str, Any]]:
    data = _get_json(
        sess,
        _SOCRATA_RUES,
        timeout=timeout,
        params={
            "numero_identificacion": nid,
            "$limit": "10",
        },
    )
    if not isinstance(data, list):
        return []
    registros = [r for r in data if isinstance(r, dict)]
    registros.sort(key=_score_registro_rues, reverse=True)
    return registros


def _score_registro_rues(registro: dict[str, Any]) -> tuple[int, int, str]:
    estado = _normalizar(registro.get("estado_matricula"))
    activo = 1 if "ACTIVA" in estado or "ACTIVO" in estado else 0
    try:
        renovado = int(re.sub(r"\D", "", str(registro.get("ultimo_ano_renovado") or "0")) or 0)
    except ValueError:
        renovado = 0
    actualizado = str(registro.get("fecha_actualizacion") or "")
    return (activo, renovado, actualizado)


def _expediente_id(registro: dict[str, Any]) -> str:
    camara = re.sub(r"\D", "", str(registro.get("codigo_camara") or ""))
    matricula = re.sub(r"\D", "", str(registro.get("matricula") or ""))
    if not camara or not matricula:
        return ""
    return f"{camara.zfill(2)}{matricula.zfill(10)}"


def _consultar_rues_legado(sess: requests.Session, nid: str, timeout: float) -> dict[str, Any] | None:
    urls = [
        f"https://ruesapi.rues.org.co/api/Empresas/{nid}",
        f"https://ruesapi.rues.org.co/api/Search?nit={nid}",
    ]
    for url in urls:
        data = _get_json(sess, url, timeout=timeout)
        parsed = _parsear_respuesta(data, fuente="RUES-legado")
        if parsed:
            return parsed
    return None


def _consultar_registronit(sess: requests.Session, nid: str, timeout: float) -> dict[str, Any] | None:
    url = _REGISTRO_NIT.format(nid=nid)
    resp = sess.get(url, timeout=timeout, headers={**_HEADERS, "Accept": "text/html,*/*"})
    if resp.status_code != 200 or not resp.text:
        return None

    html = resp.text
    titulo = _extraer_html_tag(html, "title")
    descripcion = _extraer_meta_description(html)
    texto = f"{titulo} {descripcion}"

    tdoc = 13 if "PERSONA NATURAL" in _normalizar(texto) else 31
    out: dict[str, Any] = {"tdoc": tdoc, "pais": 169, "_fuente": "RegistroNIT"}
    razon = ""
    m = re.search(r"(.+?)\s+NIT\s+[\d.\-]+", titulo, flags=re.I)
    if m:
        razon = m.group(1)
    if not razon:
        m = re.search(r"(.+?)\s+con\s+NIT\s+[\d.\-]+", descripcion, flags=re.I)
        if m:
            razon = m.group(1)
    if razon:
        out["raz"] = helpers.limpiar_texto(unescape(razon), 450)

    dv = _extraer_dv(texto)
    if dv is not None and tdoc != 13:
        out["dv"] = dv

    return out if _tiene_datos_utiles(out) else None


def _get_json(
    sess: requests.Session,
    url: str,
    *,
    timeout: float,
    params: dict[str, str] | None = None,
) -> Any:
    resp = sess.get(url, timeout=timeout, params=params)
    if resp.status_code != 200:
        return None
    ctype = resp.headers.get("content-type", "").lower()
    if "json" not in ctype and not resp.text.lstrip().startswith(("{", "[")):
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _parsear_respuesta(data: Any, *, fuente: str) -> dict[str, Any] | None:
    if not data:
        return None
    if isinstance(data, list):
        for item in data:
            parsed = _parsear_respuesta(item, fuente=fuente)
            if parsed:
                return parsed
        return None
    if not isinstance(data, dict):
        return None

    registros = data.get("registros") or data.get("registro") or data.get("data") or data
    if isinstance(registros, list):
        registros = registros[0] if registros else None
    if not isinstance(registros, dict):
        return None
    return _parsear_registro_general(registros, fuente)


def _parsear_registro_general(data: dict[str, Any], fuente: str) -> dict[str, Any]:
    def get(*keys: str) -> str:
        for key in keys:
            value = data.get(key)
            if value not in (None, "", []):
                return str(value).strip()
        return ""

    clase = get("clase_identificacion", "codigo_clase_identificacion", "tipoIdentificacion")
    tdoc = _tdoc_desde_clase(clase)
    out: dict[str, Any] = {"tdoc": tdoc, "pais": 169, "_fuente": fuente}

    razon = get("razon_social", "razonSocial", "nombre", "name", "Empresa")
    if razon:
        out["raz"] = helpers.limpiar_texto(razon, 450)

    dv = get("dv", "digito_verificacion", "digitoVerificacion")
    if dv.isdigit() and tdoc != 13:
        out["dv"] = int(dv)

    direccion = get(
        "dir_comercial",
        "direccion_comercial",
        "direccionComercial",
        "direccion",
        "DirComercial",
        "dir_fiscal",
    )
    if direccion:
        out["dir"] = helpers.limpiar_texto(direccion, 200)

    municipio = get(
        "mun_comercial",
        "codigo_municipio_comercial",
        "mcpComercial",
        "CodMcp",
        "municipio",
        "mun_fiscal",
    )
    departamento = get(
        "codigo_departamento",
        "departamento",
        "dptoComercial",
        "CodDpto",
        "dpto",
    )
    _aplicar_codigos_territoriales(out, municipio, departamento)
    return out


def _tdoc_desde_clase(clase: str) -> int:
    txt = _normalizar(clase)
    if txt in {"01", "1"} or "CEDULA" in txt:
        return 13
    if txt in {"02", "2"} or "NIT" in txt:
        return 31
    return 31


def _aplicar_codigos_territoriales(out: dict[str, Any], municipio: str, departamento: str) -> None:
    mun_digits = re.sub(r"\D", "", municipio or "")
    dpto_digits = re.sub(r"\D", "", departamento or "")
    if mun_digits:
        if len(mun_digits) == 5:
            out["dpto"] = helpers.normalizar_departamento(mun_digits)
            out["mun"] = helpers.normalizar_municipio(mun_digits)
        elif len(mun_digits) <= 3:
            out["mun"] = helpers.normalizar_municipio(mun_digits)
    if dpto_digits and "dpto" not in out:
        out["dpto"] = helpers.normalizar_departamento(dpto_digits)


def _extraer_html_tag(html: str, tag: str) -> str:
    m = re.search(fr"<{tag}[^>]*>(.*?)</{tag}>", html, flags=re.I | re.S)
    if not m:
        return ""
    return _limpiar_html(m.group(1))


def _extraer_meta_description(html: str) -> str:
    m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.I | re.S,
    )
    if not m:
        return ""
    return _limpiar_html(m.group(1))


def _limpiar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return " ".join(unescape(texto).split())


def _extraer_dv(texto: str) -> int | None:
    m = re.search(r"NIT\s+[\d.]+-(\d)", texto or "", flags=re.I)
    if not m:
        return None
    return int(m.group(1))


def _normalizar(valor: Any) -> str:
    return helpers.quitar_acentos(str(valor or "")).upper().strip()


def _merge(base: dict[str, Any], nuevo: dict[str, Any]) -> None:
    for key, value in nuevo.items():
        if value in (None, "", []):
            continue
        if key not in base or base.get(key) in (None, "", [], 0):
            base[key] = value
    if base.get("_fuente") and nuevo.get("_fuente") and nuevo["_fuente"] not in str(base["_fuente"]):
        base["_fuente"] = f"{base['_fuente']}+{nuevo['_fuente']}"


def _tiene_direccion(data: dict[str, Any]) -> bool:
    return bool(data.get("dir") and data.get("dpto") and data.get("mun"))


def _tiene_datos_utiles(data: dict[str, Any]) -> bool:
    return bool(data.get("raz") or data.get("dir") or data.get("dv"))
