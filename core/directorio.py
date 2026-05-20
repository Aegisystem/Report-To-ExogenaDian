"""Directorio de terceros (Postgres).

API pública compatible con la versión JSON:
  - lookup(nid) -> dict | None
  - upsert(nid, datos)
  - listar() -> dict[nid, dict]
  - contar() -> int
  - limpiar()
  - importar_xml_factura(path) -> list[dict]
  - importar_carpeta(carpeta) -> (archivos_leidos, terceros_actualizados)
  - consultar_remoto(nid, forzar=False) -> dict | None
  - enriquecer_lote(nids, forzar=False, delay=0.5)
  - nits_faltantes_del_df(df) -> list[str]
  - actualizar_manual(nid, datos)
  - eliminar(nid)

Cada usuario tiene su propio directorio (filtrado por usuario_id en sesión).
"""
from __future__ import annotations

from collections import Counter
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from flask import g, has_request_context
from sqlalchemy import select

from core import helpers
from db import NitNoEncontrado, Tercero, db, usuario_actual_id


# ---------------- API básica ----------------

def lookup(nid: str) -> dict[str, Any] | None:
    if not nid:
        return None
    try:
        uid = usuario_actual_id()
    except Exception:
        return None
    nid = str(nid).strip()
    if has_request_context():
        cache = getattr(g, "_directorio_lookup_cache", None)
        cache_uid = getattr(g, "_directorio_lookup_cache_uid", None)
        if cache is None or cache_uid != uid:
            rows = db.session.scalars(select(Tercero).where(Tercero.usuario_id == uid)).all()
            cache = {t.nid: t.to_dict() for t in rows}
            g._directorio_lookup_cache = cache
            g._directorio_lookup_cache_uid = uid
        return cache.get(nid)

    t = db.session.scalar(select(Tercero).where(Tercero.usuario_id == uid, Tercero.nid == nid))
    return t.to_dict() if t else None


def _aplicar_campos(t: Tercero, datos: dict[str, Any]) -> None:
    """Merge: solo sobreescribe campos vacíos del existente."""
    mapeo = {
        "tdoc": "tdoc",
        "dv": "dv",
        "raz": "raz",
        "apl1": "apl1",
        "apl2": "apl2",
        "nom1": "nom1",
        "nom2": "nom2",
        "dir": "direccion",
        "dpto": "dpto",
        "mun": "mun",
        "pais": "pais",
        "fuente": "fuente",
        "_fuente": "fuente",
    }
    for src, dst in mapeo.items():
        if src not in datos:
            continue
        v = datos[src]
        if src == "dpto":
            v = helpers.normalizar_departamento(v)
        elif src == "mun":
            v = helpers.normalizar_municipio(v)
        if v in (None, "", 0):
            existente = getattr(t, dst, None)
            if existente not in (None, "", 0):
                continue
        setattr(t, dst, v)


def upsert(nid: str, datos: dict[str, Any]) -> None:
    if not nid:
        return
    uid = usuario_actual_id()
    nid = str(nid).strip()
    if not nid:
        return
    t = db.session.scalar(select(Tercero).where(Tercero.usuario_id == uid, Tercero.nid == nid))
    if t is None:
        t = Tercero(usuario_id=uid, nid=nid)
        db.session.add(t)
    _aplicar_campos(t, datos)
    db.session.commit()


def listar() -> dict[str, dict[str, Any]]:
    try:
        uid = usuario_actual_id()
    except Exception:
        return {}
    rows = db.session.scalars(select(Tercero).where(Tercero.usuario_id == uid).order_by(Tercero.nid)).all()
    return {r.nid: r.to_dict() for r in rows}


def contar() -> int:
    try:
        uid = usuario_actual_id()
    except Exception:
        return 0
    return db.session.query(Tercero).filter_by(usuario_id=uid).count()


def limpiar() -> None:
    uid = usuario_actual_id()
    db.session.query(Tercero).filter_by(usuario_id=uid).delete()
    db.session.query(NitNoEncontrado).filter_by(usuario_id=uid).delete()
    db.session.commit()


def eliminar(nid: str) -> None:
    uid = usuario_actual_id()
    nid = str(nid).strip()
    db.session.query(Tercero).filter_by(usuario_id=uid, nid=nid).delete()
    db.session.commit()


def actualizar_manual(nid: str, datos: dict[str, Any]) -> None:
    upsert(nid, datos)
    # limpiar cache negativo si existía
    uid = usuario_actual_id()
    db.session.query(NitNoEncontrado).filter_by(usuario_id=uid, nid=str(nid).strip()).delete()
    db.session.commit()


def _nombre_origen(valor: Any) -> str:
    if valor is None:
        return ""
    nombre = " ".join(str(valor).strip().split())
    if nombre.lower() in ("", "nan", "none", "nat"):
        return ""
    return nombre


def _tercero_desde_fila(row) -> tuple[str, str]:
    grupo = (row.get("grupo") or "").lower()
    if grupo == "recibido":
        return (
            helpers.normalizar_nit(row.get("nit_emisor", "")),
            _nombre_origen(row.get("nombre_emisor", "")),
        )
    if grupo == "emitido":
        return (
            helpers.normalizar_nit(row.get("nit_receptor", "")),
            _nombre_origen(row.get("nombre_receptor", "")),
        )
    return ("", "")


def _mejor_nombre(candidatos: Counter[str]) -> str:
    return max(candidatos, key=lambda nombre: (candidatos[nombre], len(nombre.split()), len(nombre)))


def recalcular_nombres_desde_df(df) -> int:
    """Repara nombres/apellidos de personas naturales ya guardadas usando el XLSX cargado."""
    if df is None or df.empty:
        return 0

    por_nit: dict[str, Counter[str]] = {}
    for _, row in df.iterrows():
        nid, nombre = _tercero_desde_fila(row)
        if nid and nombre:
            por_nit.setdefault(nid, Counter())[nombre] += 1
    if not por_nit:
        return 0

    uid = usuario_actual_id()
    terceros = db.session.scalars(
        select(Tercero).where(Tercero.usuario_id == uid, Tercero.nid.in_(list(por_nit)))
    ).all()

    actualizados = 0
    for t in terceros:
        tdoc = t.tdoc if t.tdoc is not None else helpers.inferir_tipo_documento(t.nid)
        if not helpers.es_persona_natural(tdoc):
            continue

        apl1, apl2, nom1, nom2 = helpers.split_nombre_persona(_mejor_nombre(por_nit[t.nid]))
        nuevos = {
            "tdoc": tdoc,
            "raz": "",
            "apl1": helpers.limpiar_texto(apl1, 60),
            "apl2": helpers.limpiar_texto(apl2, 60),
            "nom1": helpers.limpiar_texto(nom1, 60),
            "nom2": helpers.limpiar_texto(nom2, 60),
        }
        cambio = False
        for campo, valor in nuevos.items():
            if getattr(t, campo) != valor:
                setattr(t, campo, valor)
                cambio = True
        if cambio:
            actualizados += 1

    if actualizados:
        db.session.commit()
    return actualizados


# ---------------- importador XML ----------------

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
    if party is None:
        return {}
    out: dict[str, Any] = {}

    party_id = party.find(".//cac:PartyTaxScheme/cbc:CompanyID", _NS) or \
               party.find(".//cac:PartyIdentification/cbc:ID", _NS)
    if party_id is not None:
        nid = helpers.normalizar_nit(party_id.text or "")
        out["nid"] = nid

    razon = _texto(party, ".//cac:PartyTaxScheme/cbc:RegistrationName") or \
            _texto(party, ".//cac:PartyLegalEntity/cbc:RegistrationName") or \
            _texto(party, ".//cac:PartyName/cbc:Name")
    out["raz"] = razon

    persona = party.find(".//cac:Person", _NS)
    if persona is not None:
        out["nom1"] = _texto(persona, "cbc:FirstName")
        out["nom2"] = _texto(persona, "cbc:MiddleName")
        out["apl1"] = _texto(persona, "cbc:FamilyName")
        out["apl2"] = _texto(persona, "cbc:OtherName")
        if any(out.get(k) for k in ("nom1", "apl1")):
            out["raz"] = ""

    direccion = party.find(".//cac:PhysicalLocation/cac:Address", _NS) or \
                party.find(".//cac:PartyTaxScheme/cac:RegistrationAddress", _NS) or \
                party.find(".//cac:RegistrationAddress", _NS) or \
                party.find(".//cac:PostalAddress", _NS)
    if direccion is not None:
        linea = _texto(direccion, "cac:AddressLine/cbc:Line") or _texto(direccion, "cbc:StreetName")
        if linea:
            out["dir"] = linea[:200]
        mun_id = _texto(direccion, "cbc:ID") or _texto(direccion, "cbc:CityName")
        if mun_id and mun_id.isdigit():
            if len(mun_id) == 5:
                out["dpto"] = helpers.normalizar_departamento(mun_id)
                out["mun"] = helpers.normalizar_municipio(mun_id)
            elif len(mun_id) <= 3:
                out["mun"] = helpers.normalizar_municipio(mun_id)

        pais_code = _texto(direccion, "cac:Country/cbc:IdentificationCode")
        if pais_code == "CO":
            out["pais"] = 169

    out["fuente"] = "UBL"
    return out


def _importar_formato_dian(root: ET.Element) -> list[dict[str, Any]]:
    """XML 'mas' del Prevalidador DIAN."""
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
        data: dict[str, Any] = {"nid": nid, "fuente": "DIAN-Prevalidador"}
        if attrs.get("tdoc", "").isdigit():
            data["tdoc"] = int(attrs["tdoc"])
        if attrs.get("dv", "").isdigit():
            data["dv"] = int(attrs["dv"])
        for k in ("raz", "apl1", "apl2", "nom1", "nom2", "dir"):
            v = attrs.get(k, "").strip()
            if v:
                data[k] = v
        for k in ("dpto", "mun", "pais"):
            v = attrs.get(k, "")
            if v.isdigit():
                if k == "dpto":
                    data[k] = helpers.normalizar_departamento(v)
                elif k == "mun":
                    data[k] = helpers.normalizar_municipio(v)
                else:
                    data[k] = int(v)
        if "dv" not in data:
            dv = helpers.calcular_dv(nid)
            if dv is not None:
                data["dv"] = dv
        out.append(data)
    return out


def importar_xml_factura(path: Path) -> list[dict[str, Any]]:
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    root = tree.getroot()

    if root.tag == "mas":
        return _importar_formato_dian(root)

    cdata = root.findall(".//{*}CDATA")
    if cdata:
        for c in cdata:
            try:
                inner = ET.fromstring((c.text or "").strip())
                root = inner
                break
            except ET.ParseError:
                continue

    encontrados: list[dict[str, Any]] = []
    candidatos = [root] + root.findall(".//{*}Invoice") + \
                 root.findall(".//{*}CreditNote") + root.findall(".//{*}DebitNote")
    for c in candidatos:
        for xpath in (".//cac:AccountingSupplierParty/cac:Party",
                      ".//cac:AccountingCustomerParty/cac:Party"):
            for party in c.findall(xpath, _NS):
                data = _parsear_party(party)
                if data.get("nid"):
                    encontrados.append(data)
        if encontrados:
            break
    return encontrados


def importar_carpeta(carpeta: Path) -> tuple[int, int]:
    """Recorre carpeta (recursivo) y ZIPs internos. Bulk insert eficiente."""
    if not carpeta.exists():
        return (0, 0)

    uid = usuario_actual_id()
    archivos_leidos = 0
    procesados = 0

    # Pre-cargar terceros existentes del usuario en memoria
    existentes = {
        t.nid: t for t in db.session.scalars(
            select(Tercero).where(Tercero.usuario_id == uid)
        )
    }

    def upsert_local(data: dict[str, Any]) -> None:
        nonlocal procesados
        nid = data.get("nid")
        if not nid:
            return
        t = existentes.get(nid)
        if t is None:
            t = Tercero(usuario_id=uid, nid=nid)
            db.session.add(t)
            existentes[nid] = t
        _aplicar_campos(t, data)
        procesados += 1

    for path in carpeta.rglob("*"):
        if not path.is_file():
            continue
        suf = path.suffix.lower()
        if suf == ".xml":
            archivos_leidos += 1
            try:
                for d in importar_xml_factura(path):
                    upsert_local(d)
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
                                for d in _importar_formato_dian(root):
                                    upsert_local(d)
                            else:
                                for xpath in (".//cac:AccountingSupplierParty/cac:Party",
                                              ".//cac:AccountingCustomerParty/cac:Party"):
                                    for party in root.findall(xpath, _NS):
                                        d = _parsear_party(party)
                                        if d.get("nid"):
                                            upsert_local(d)
                        except Exception:
                            continue
            except (zipfile.BadZipFile, OSError):
                continue

    db.session.commit()
    return archivos_leidos, procesados


# ---------------- web scraping ----------------

def consultar_remoto(nid: str, forzar: bool = False) -> dict[str, Any] | None:
    from core.scrapers import rues
    import datetime as _dt

    if not nid:
        return None
    nid = str(nid).strip()
    uid = usuario_actual_id()

    pos = lookup(nid)
    if pos:
        return pos

    if not forzar:
        neg = db.session.query(NitNoEncontrado).filter_by(usuario_id=uid, nid=nid, fuente="RUES").first()
        if neg:
            return None

    data = rues.consultar(nid)
    if data:
        upsert(nid, data)
        db.session.query(NitNoEncontrado).filter_by(usuario_id=uid, nid=nid, fuente="RUES").delete()
        db.session.commit()
        return data

    # Cache negativo
    neg = db.session.query(NitNoEncontrado).filter_by(usuario_id=uid, nid=nid, fuente="RUES").first()
    if neg:
        neg.fecha = _dt.datetime.utcnow()
    else:
        db.session.add(NitNoEncontrado(usuario_id=uid, nid=nid, fuente="RUES"))
    db.session.commit()
    return None


def enriquecer_lote(nids: list[str], forzar: bool = False, delay: float = 0.5) -> tuple[int, int, list[str]]:
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
    if df is None or df.empty:
        return []
    nids = set()
    for _, row in df.iterrows():
        g = (row.get("grupo") or "").lower()
        if g == "recibido":
            nit = str(row.get("nit_emisor", "") or "").strip()
        elif g == "emitido":
            nit = str(row.get("nit_receptor", "") or "").strip()
        else:
            continue
        nit = helpers.normalizar_nit(nit)
        if nit:
            nids.add(nit)
    try:
        uid = usuario_actual_id()
    except Exception:
        return sorted(nids)
    existentes = {
        row[0] for row in db.session.query(Tercero.nid).filter_by(usuario_id=uid)
    }
    return sorted(nids - existentes)
