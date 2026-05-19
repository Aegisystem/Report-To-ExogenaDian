"""Directorio de terceros.

Cache local JSON con datos enriquecidos por NIT:
  raz, apl1, apl2, nom1, nom2, dv, dir, dpto, mun, pais, tdoc

Fuentes (en orden):
  1. Importación de XML UBL de facturas electrónicas (cliente o proveedor).
  2. Importación de archivos XLSX externos con columnas de directorio.
  3. (futuro) Web scraping a RUES / DIAN consulta NIT - stub.

Lookup más simple: directorio.lookup(nid) -> dict | None
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Iterable

from core import helpers


_BASE = Path(__file__).resolve().parent.parent
_RUTA = _BASE / "config" / "directorio.json"


# ---------------- persistencia ----------------

def _cargar() -> dict[str, dict[str, Any]]:
    if not _RUTA.exists():
        return {}
    try:
        with open(_RUTA, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _guardar(data: dict[str, dict[str, Any]]) -> None:
    _RUTA.parent.mkdir(parents=True, exist_ok=True)
    with open(_RUTA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def lookup(nid: str) -> dict[str, Any] | None:
    if not nid:
        return None
    return _cargar().get(str(nid).strip())


def upsert(nid: str, datos: dict[str, Any]) -> None:
    if not nid:
        return
    nid = str(nid).strip()
    data = _cargar()
    existente = data.get(nid, {})
    # Merge: solo sobrescribir si el nuevo dato es no vacío
    for k, v in datos.items():
        if v in (None, "", 0) and existente.get(k):
            continue
        existente[k] = v
    data[nid] = existente
    _guardar(data)


def listar() -> dict[str, dict[str, Any]]:
    return _cargar()


def contar() -> int:
    return len(_cargar())


def limpiar() -> None:
    _guardar({})


# ---------------- importador XML UBL ----------------

# UBL 2.1 namespaces de facturación electrónica DIAN
_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "sts": "dian:gov:co:facturaelectronica:Structures-2-1",
    "fe":  "http://www.dian.gov.co/contratos/facturaelectronica/v1",
}


def _texto(elem, xpath: str) -> str:
    if elem is None:
        return ""
    found = elem.find(xpath, _NS)
    return (found.text or "").strip() if found is not None else ""


def _parsear_party(party: ET.Element) -> dict[str, Any]:
    """Extrae datos de un <cac:Party> UBL."""
    if party is None:
        return {}
    out: dict[str, Any] = {}

    # NIT/DV/Tipo doc
    party_id = party.find(".//cac:PartyTaxScheme/cbc:CompanyID", _NS) or \
               party.find(".//cac:PartyIdentification/cbc:ID", _NS)
    if party_id is not None:
        nid = helpers.normalizar_nit(party_id.text or "")
        out["nid"] = nid
        dv_attr = party_id.attrib.get("schemeID") or party.find(
            ".//cac:PartyTaxScheme/cbc:CompanyID", _NS
        )
        if dv_attr and isinstance(dv_attr, str) and dv_attr.isdigit():
            out["dv"] = int(dv_attr)
        tdoc_attr = party_id.attrib.get("schemeName")
        if tdoc_attr and tdoc_attr.isdigit():
            out["tdoc"] = int(tdoc_attr)

    # Persona jurídica vs natural
    razon = _texto(party, ".//cac:PartyTaxScheme/cbc:RegistrationName") or \
            _texto(party, ".//cac:PartyLegalEntity/cbc:RegistrationName") or \
            _texto(party, ".//cac:PartyName/cbc:Name")
    out["raz"] = razon

    nombre_pers = party.find(".//cac:Person", _NS)
    if nombre_pers is not None:
        out["nom1"] = _texto(nombre_pers, "cbc:FirstName")
        out["nom2"] = _texto(nombre_pers, "cbc:MiddleName")
        out["apl1"] = _texto(nombre_pers, "cbc:FamilyName")
        out["apl2"] = _texto(nombre_pers, "cbc:OtherName")
        # Si no hay nada en raz pero hay persona, marcar tdoc persona natural
        if any(out.get(k) for k in ("nom1", "apl1")):
            out["raz"] = ""

    # Dirección
    direccion = party.find(".//cac:PhysicalLocation/cac:Address", _NS) or \
                party.find(".//cac:PartyTaxScheme/cac:RegistrationAddress", _NS) or \
                party.find(".//cac:RegistrationAddress", _NS) or \
                party.find(".//cac:PostalAddress", _NS)
    if direccion is not None:
        linea = _texto(direccion, "cac:AddressLine/cbc:Line") or \
                _texto(direccion, "cbc:StreetName")
        out["dir"] = linea[:200]
        dpto_id = _texto(direccion, "cbc:CountrySubentityCode")
        mun_id = _texto(direccion, "cbc:ID") or _texto(direccion, "cbc:CityName")
        if dpto_id.isdigit():
            out["dpto"] = int(dpto_id)
        if mun_id.isdigit():
            mun_str = mun_id
            # Códigos DANE: 5 dígitos (DDMMM). Tomar los últimos 3 como municipio.
            if len(mun_str) == 5:
                out["dpto"] = int(mun_str[:2])
                out["mun"] = int(mun_str[2:])
            elif len(mun_str) <= 3:
                out["mun"] = int(mun_str)

        pais_code = _texto(direccion, "cac:Country/cbc:IdentificationCode")
        if pais_code == "CO":
            out["pais"] = 169

    return out


def importar_xml_factura(path: Path) -> list[dict[str, Any]]:
    """Lee un XML y extrae terceros. Auto-detecta dos formatos:
       (1) UBL de facturación (Invoice/CreditNote/DebitNote/AttachedDocument)
       (2) XML del Prevalidador DIAN ya cargado (root='mas' con elementos por formato)
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    root = tree.getroot()

    # ---- Caso 2: XML del Prevalidador DIAN (root 'mas' sin namespace) ----
    if root.tag in ("mas", "{http://www.w3.org/2001/XMLSchema-instance}mas"):
        return _importar_formato_dian(root)

    # ---- Caso 1: UBL ----

    # Algunos AttachedDocument envuelven la factura real en CDATA. Manejarlo.
    cdata = root.findall(".//{*}CDATA")
    if cdata:
        for c in cdata:
            try:
                inner = ET.fromstring((c.text or "").strip())
                root = inner
                break
            except ET.ParseError:
                continue

    # Algunos AttachedDocument tienen la factura en <cac:Attachment><cac:ExternalReference>
    # o como child. Buscar el primer Invoice/CreditNote/DebitNote.
    candidatos = [root]
    candidatos += root.findall(".//{*}Invoice")
    candidatos += root.findall(".//{*}CreditNote")
    candidatos += root.findall(".//{*}DebitNote")

    encontrados: list[dict[str, Any]] = []
    for c in candidatos:
        sup = c.find(".//cac:AccountingSupplierParty/cac:Party", _NS)
        cli = c.find(".//cac:AccountingCustomerParty/cac:Party", _NS)
        for party in (sup, cli):
            if party is None:
                continue
            data = _parsear_party(party)
            if data.get("nid"):
                encontrados.append(data)
        if encontrados:
            break

    return encontrados


def _importar_formato_dian(root: ET.Element) -> list[dict[str, Any]]:
    """Extrae terceros de XML del Prevalidador (1001, 1005, 1006, 1007, 5247-5250...).

    Estos XML traen los terceros como elementos hijos del root 'mas', con
    atributos que coinciden con los campos del XSD: nid, tdoc, dv, raz,
    apl1, apl2, nom1, nom2, dir, dpto, mun, pais.
    """
    out: list[dict[str, Any]] = []
    for child in root:
        if child.tag.lower() in ("cab", "cabecera"):
            continue
        attrs = child.attrib
        nid_raw = attrs.get("nid") or attrs.get("nit") or ""
        if not nid_raw:
            continue
        nid = helpers.normalizar_nit(nid_raw)
        if not nid:
            continue

        data: dict[str, Any] = {"nid": nid}
        if "tdoc" in attrs and attrs["tdoc"].isdigit():
            data["tdoc"] = int(attrs["tdoc"])
        if "dv" in attrs and attrs["dv"].isdigit():
            data["dv"] = int(attrs["dv"])
        for k in ("raz", "apl1", "apl2", "nom1", "nom2", "dir"):
            v = attrs.get(k, "").strip()
            if v:
                data[k] = v
        for k in ("dpto", "mun", "pais"):
            v = attrs.get(k, "")
            if v.isdigit():
                data[k] = int(v)
        if data.get("dv") is None:
            data["dv"] = helpers.calcular_dv(nid)
        out.append(data)
    return out


def _upsert_en_memoria(data: dict[str, dict[str, Any]], nid: str, nuevo: dict[str, Any]) -> None:
    if not nid:
        return
    nid = str(nid).strip()
    existente = data.get(nid, {})
    for k, v in nuevo.items():
        if v in (None, "", 0) and existente.get(k):
            continue
        existente[k] = v
    data[nid] = existente


def importar_carpeta(carpeta: Path) -> tuple[int, int]:
    """Importa todos los XML de una carpeta (recursivo, ZIPs incluidos).
    Carga el JSON una sola vez al inicio, acumula en memoria y guarda al final.
    """
    if not carpeta.exists():
        return (0, 0)

    data = _cargar()
    archivos_leidos = 0
    terceros_actualizados = 0

    # XMLs sueltos
    for path in carpeta.rglob("*"):
        if not path.is_file():
            continue
        suf = path.suffix.lower()
        if suf == ".xml":
            archivos_leidos += 1
            try:
                for t in importar_xml_factura(path):
                    _upsert_en_memoria(data, t["nid"], t)
                    terceros_actualizados += 1
            except Exception:
                pass
        elif suf == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    for name in zf.namelist():
                        if not name.lower().endswith(".xml"):
                            continue
                        archivos_leidos += 1
                        try:
                            with zf.open(name) as f:
                                tree = ET.parse(f)
                            root = tree.getroot()
                            if root.tag == "mas":
                                for t in _importar_formato_dian(root):
                                    _upsert_en_memoria(data, t["nid"], t)
                                    terceros_actualizados += 1
                            else:
                                for _, party in _iter_parties(root):
                                    t = _parsear_party(party)
                                    if t.get("nid"):
                                        _upsert_en_memoria(data, t["nid"], t)
                                        terceros_actualizados += 1
                        except Exception:
                            continue
            except (zipfile.BadZipFile, OSError):
                continue

    _guardar(data)
    return archivos_leidos, terceros_actualizados


def _iter_parties(root) -> Iterable[tuple[str, ET.Element]]:
    """Itera sobre emisor y receptor de un documento UBL."""
    for xpath in (".//cac:AccountingSupplierParty/cac:Party",
                  ".//cac:AccountingCustomerParty/cac:Party"):
        for p in root.findall(xpath, _NS):
            yield xpath, p


# ---------------- web scraping ----------------

_NEG_CACHE_PATH = _BASE / "config" / "directorio_no_encontrados.json"


def _cargar_negativos() -> dict[str, str]:
    if not _NEG_CACHE_PATH.exists():
        return {}
    try:
        with open(_NEG_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _guardar_negativos(data: dict[str, str]) -> None:
    with open(_NEG_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def consultar_remoto(nid: str, forzar: bool = False) -> dict[str, Any] | None:
    """Consulta RUES si el NIT no está en cache local ni en cache de negativos.
    `forzar=True` ignora el cache de negativos."""
    from core.scrapers import rues

    if not nid:
        return None
    nid = str(nid).strip()
    if not nid:
        return None

    # Cache de positivos
    pos = lookup(nid)
    if pos:
        return pos

    # Cache de negativos
    neg = _cargar_negativos()
    if not forzar and nid in neg:
        return None

    data = rues.consultar(nid)
    if data:
        upsert(nid, data)
        if nid in neg:
            del neg[nid]
            _guardar_negativos(neg)
        return data

    # Guardar negativo
    import datetime as _dt
    neg[nid] = _dt.datetime.now().isoformat(timespec="seconds")
    _guardar_negativos(neg)
    return None


def enriquecer_lote(nids: list[str], forzar: bool = False, delay: float = 0.5) -> tuple[int, int, list[str]]:
    """Consulta una lista de NITs. Devuelve (encontrados, no_encontrados, errores)."""
    import time as _time
    enc = 0
    noenc = 0
    errores: list[str] = []
    for nid in nids:
        try:
            res = consultar_remoto(nid, forzar=forzar)
            if res:
                enc += 1
            else:
                noenc += 1
        except Exception as exc:
            errores.append(f"{nid}: {exc}")
        _time.sleep(delay)
    return enc, noenc, errores


def nits_faltantes_del_df(df) -> list[str]:
    """De un DataFrame normalizado, devuelve los NITs (emisor o receptor según grupo)
    que NO están aún en el directorio local."""
    if df is None or df.empty:
        return []
    nids = set()
    for _, row in df.iterrows():
        g = (row.get("grupo") or "").lower()
        nit = ""
        if g == "recibido":
            nit = str(row.get("nit_emisor", "") or "").strip()
        elif g == "emitido":
            nit = str(row.get("nit_receptor", "") or "").strip()
        nit = helpers.normalizar_nit(nit)
        if nit:
            nids.add(nit)
    existentes = set(_cargar().keys())
    return sorted(nids - existentes)


# ---------------- edición manual ----------------

def actualizar_manual(nid: str, datos: dict[str, Any]) -> None:
    """Inserta/actualiza un tercero manualmente. Limpia el negativo cache si aplica."""
    nid = str(nid).strip()
    if not nid:
        return
    upsert(nid, datos)
    neg = _cargar_negativos()
    if nid in neg:
        del neg[nid]
        _guardar_negativos(neg)


def eliminar(nid: str) -> None:
    nid = str(nid).strip()
    data = _cargar()
    if nid in data:
        del data[nid]
        _guardar(data)
