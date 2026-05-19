"""Utilidades comunes: DV NIT, inferencia tipo doc, split de nombres."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


_DV_PRIMES = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]


def calcular_dv(nit: str) -> Optional[int]:
    """Algoritmo DIAN para dígito de verificación. Devuelve None si NIT inválido."""
    if nit is None:
        return None
    s = re.sub(r"\D", "", str(nit))
    if not s:
        return None
    digits = list(map(int, s))[::-1]
    total = sum(d * _DV_PRIMES[i] for i, d in enumerate(digits) if i < len(_DV_PRIMES))
    resto = total % 11
    if resto < 2:
        return resto
    return 11 - resto


def inferir_tipo_documento(nit: str) -> int:
    """Códigos DIAN: 11=Reg civil, 12=Tarjeta identidad, 13=Cedula, 21=Tarjeta extranj,
    22=Cedula extranj, 31=NIT, 41=Pasaporte, 42=Doc id extranjero, 43=Sin id exterior,
    47=PEP, 48=PPT, 50=NIT otro pais, 91=NUIP."""
    if nit is None:
        return 43
    s = re.sub(r"\D", "", str(nit))
    if not s:
        return 43
    # NITs empresariales colombianos: 8xx, 9xx con 9-10 dígitos
    if len(s) >= 9 and s[0] in ("8", "9"):
        return 31
    # Cédulas: hasta 10 dígitos
    if len(s) <= 10:
        return 13
    return 31


def quitar_acentos(texto: str) -> str:
    if texto is None:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn")


_PARTICULAS = {"de", "del", "la", "las", "los", "san", "santa", "da", "do", "di", "van", "von"}


def split_nombre_persona(nombre: str) -> tuple[str, str, str, str]:
    """Divide en (apl1, apl2, nom1, nom2) usando convención latina:
    el archivo MUISCA viene como NOMBRE [NOMBRE] APELLIDO [APELLIDO].

    Heurística:
      1 palabra  -> nom1 = palabra (sin apellido detectable)
      2 palabras -> NOMBRE APELLIDO -> apl1, nom1
      3 palabras -> NOMBRE APELLIDO APELLIDO -> apl1, apl2, nom1
      4 palabras -> NOMBRE NOMBRE APELLIDO APELLIDO -> apl1, apl2, nom1, nom2
      5+         -> últimas 2 apellidos, primera nom1, resto nom2 (concatenado)

    Partículas comunes (de, del, la, los, etc.) se pegan a la palabra siguiente.
    """
    if not nombre:
        return ("", "", "", "")
    raw = [p for p in re.split(r"\s+", str(nombre).strip()) if p]
    if not raw:
        return ("", "", "", "")

    # Pegar partículas a la siguiente palabra: "DE LA HOZ" -> "DE LA HOZ" como una unidad
    partes: list[str] = []
    buffer = ""
    for w in raw:
        if w.lower() in _PARTICULAS:
            buffer = f"{buffer} {w}".strip()
        else:
            if buffer:
                partes.append(f"{buffer} {w}".strip())
                buffer = ""
            else:
                partes.append(w)
    if buffer:
        if partes:
            partes[-1] = f"{partes[-1]} {buffer}".strip()
        else:
            partes.append(buffer)

    n = len(partes)
    if n == 1:
        return ("", "", partes[0], "")
    if n == 2:
        return (partes[1], "", partes[0], "")
    if n == 3:
        return (partes[1], partes[2], partes[0], "")
    if n == 4:
        return (partes[2], partes[3], partes[0], partes[1])
    # 5+: últimas 2 = apellidos; primera = nom1; resto = nom2
    return (partes[-2], partes[-1], partes[0], " ".join(partes[1:-2]))


def normalizar_nit(nit) -> str:
    if nit is None:
        return ""
    return re.sub(r"\D", "", str(nit))


def es_persona_natural(tdoc: int) -> bool:
    return tdoc in (11, 12, 13, 21, 22, 41, 42, 47, 48, 91)


def limpiar_texto(s, maxlen: int = None) -> str:
    if s is None:
        return ""
    txt = str(s).strip()
    # Reemplazar caracteres problemáticos pero preservar acentos
    txt = re.sub(r"[\x00-\x1f]", " ", txt)
    if maxlen:
        txt = txt[:maxlen]
    return txt
