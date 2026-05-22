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


_TIPOS_DOCUMENTO_VALIDOS = {11, 12, 13, 21, 22, 31, 41, 42, 43, 47, 48, 50, 91}

_MARCADORES_PERSONA_JURIDICA = {
    "sas", "sa", "s a", "s a s", "s en c", "ltda", "limitada", "e u", "eu",
    "empresa", "empresas", "fundacion", "corporacion", "cooperativa", "asociacion",
    "banco", "compania", "cia", "comercializadora", "constructora", "construcciones",
    "ingenieria", "inversiones", "servicios", "soluciones", "suministros",
    "distribuciones", "distribuidora", "transportes", "industrias", "grupo",
    "organizacion", "clinica", "hospital", "ips", "eps",
}


def tipo_documento_desde_valor(valor) -> Optional[int]:
    if valor is None:
        return None
    txt = quitar_acentos(str(valor)).lower().strip()
    if not txt:
        return None
    digits = re.sub(r"\D", "", txt)
    if digits:
        codigo = int(digits)
        if codigo in _TIPOS_DOCUMENTO_VALIDOS:
            return codigo
    compacto = re.sub(r"[^a-z0-9]+", " ", txt).strip()
    if compacto in {"cc", "c c"} or "cedula de ciudadania" in compacto:
        return 13
    if "nit" in compacto:
        return 31
    if "tarjeta de identidad" in compacto:
        return 12
    if "registro civil" in compacto:
        return 11
    if "cedula de extranjeria" in compacto:
        return 22
    if "pasaporte" in compacto:
        return 41
    if "pep" in compacto:
        return 47
    if "ppt" in compacto:
        return 48
    return None


def parece_persona_juridica(nombre: str) -> bool:
    clave = _clave_nombre(nombre)
    if not clave:
        return False
    tokens = set(clave.split())
    if tokens & _MARCADORES_PERSONA_JURIDICA:
        return True
    return any(marcador in clave for marcador in ("s a s", "s a", "s en c"))


def parece_persona_natural(nombre: str) -> bool:
    clave = _clave_nombre(nombre)
    if not clave or parece_persona_juridica(nombre):
        return False
    partes = clave.split()
    if not 2 <= len(partes) <= 6:
        return False
    return not any(char.isdigit() for char in clave)


def inferir_tipo_documento(nit: str, nombre: str | None = None) -> int:
    """Códigos DIAN: 11=Reg civil, 12=Tarjeta identidad, 13=Cedula, 21=Tarjeta extranj,
    22=Cedula extranj, 31=NIT, 41=Pasaporte, 42=Doc id extranjero, 43=Sin id exterior,
    47=PEP, 48=PPT, 50=NIT otro pais, 91=NUIP."""
    if nit is None:
        return 43
    s = normalizar_nit(nit)
    if not s:
        return 43
    # NIT empresarial colombiano: 9 dígitos y empieza por 8 o 9. Si llega
    # con DV pegado, suele quedar en 10 dígitos con el mismo prefijo.
    if es_nit_colombiano(s):
        return 31
    if nombre and parece_persona_juridica(nombre):
        return 31
    if nombre and parece_persona_natural(nombre):
        return 13
    # Cédulas: hasta 10 dígitos
    if len(s) <= 10:
        return 13
    return 31


def quitar_acentos(texto: str) -> str:
    if texto is None:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn")


_PARTICULAS = {"de", "del", "la", "las", "los", "san", "santa", "da", "do", "di", "van", "von"}

_NOMBRES_COMUNES = {
    "aaron", "abel", "abraham", "adriana", "adriano", "adrian", "alba", "alberto",
    "alejandro", "alejandra", "alex", "alexander", "alexandra", "alfonso", "alfredo",
    "alicia", "alvaro", "amanda", "ana", "andrea", "andres", "angel", "angela",
    "angelica",
    "antonio", "armando", "arturo", "aura", "beatriz", "benjamin", "blanca",
    "camila", "carlos", "carmen", "carolina", "catalina", "cecilia", "cesar",
    "claudia", "claudio", "consuelo", "cristian", "daniel", "daniela", "dario",
    "david", "diana", "diego", "edgar", "eduardo", "edward", "edwin", "elena", "eliana",
    "elizabeth", "elsa", "emilio", "enrique", "erika", "esteban", "fabian",
    "felipe", "fernanda", "fernando", "francisco", "gabriel", "gabriela", "german",
    "giovanni", "gloria", "gonzalo", "guillermo", "gustavo", "hector", "henry",
    "hernando", "humberto", "ines", "isabel", "ivan", "jaime", "javier", "jenny",
    "jesica", "jessica", "jesus", "jhon", "jhonatan", "john", "jonathan", "jorge",
    "jose", "juan", "julian", "juliana", "julio", "karen", "laura", "leidy",
    "liliana", "lina", "lorena", "lucia", "luis", "luz", "manuela", "manuel",
    "marcela", "marcelo", "maria", "marina", "mario", "martha", "marta", "mauricio",
    "miguel", "monica", "natalia", "nancy", "nelson", "nicolas", "nubia", "olga",
    "omar", "oscar", "pablo", "patricia", "paola", "paula", "pedro", "rafael", "ramiro", "raul",
    "ricardo", "roberto", "rocio", "rosa", "sandra", "santiago", "sara",
    "sebastian", "sergio", "silvia", "sofia", "sonia", "tatiana", "teresa",
    "valentina", "vanessa", "victor", "viviana", "william", "ximena", "yenny",
    "yesid", "yolanda", "dary", "jairo", "mary", "mery", "del carmen",
    "del pilar", "del rosario", "de jesus", "de los angeles",
}

_NOMBRES_COMPUESTOS = {
    "ana lucia", "ana maria", "ana sofia", "carlos alberto", "carlos andres",
    "jhon jairo", "jose antonio", "jose david", "jose de jesus", "jose luis", "jose manuel", "juan camilo",
    "juan carlos", "juan david", "juan jose", "juan pablo", "juan sebastian",
    "luis alberto", "luis eduardo", "luis fernando", "luz dary", "luz marina",
    "luz mary", "luz mery",
    "maria alejandra", "maria camila", "maria del carmen", "maria de jesus",
    "maria del pilar", "maria del rosario", "maria de los angeles", "maria fernanda",
    "maria isabel", "maria jose",
}

_APELLIDOS_COMUNES = {
    "agudelo", "alvarez", "arias", "avila", "barbosa", "barrera", "bernal",
    "betancur", "blanco", "bolivar", "botero", "caballero", "calderon", "cano",
    "cardenas", "cardona", "castano", "castillo", "castro", "contreras", "cordoba",
    "correa", "cortes", "cruz", "diaz", "duarte", "escobar", "espinosa", "florez",
    "franco", "gallego", "garcia", "gomez", "gonzalez", "gutierrez", "guzman",
    "hernandez", "herrera", "hoyos", "jimenez", "leon", "lopez", "marin",
    "martinez", "medina", "mejia", "mendoza", "molina", "montoya", "morales",
    "moreno", "munoz", "narvaez", "navarro", "nunez", "ortega", "ortiz", "osorio",
    "pardo", "paredes", "pena", "perez", "quintero", "ramirez", "ramos",
    "restrepo", "reyes", "rivera", "rodriguez", "rojas", "romero", "ruiz",
    "salazar", "sanchez", "sandoval", "silva", "solano", "soto", "suarez",
    "torres", "trujillo", "uribe", "valencia", "vallejo", "vargas", "vasquez",
    "vega", "velasquez", "vergara", "villa", "zapata",
}


def split_nombre_persona(nombre: str) -> tuple[str, str, str, str]:
    """Divide en (apl1, apl2, nom1, nom2) usando convención latina:
    el archivo MUISCA viene como NOMBRE [NOMBRE] APELLIDO [APELLIDO].

    Heurística:
      1 palabra  -> nom1 = palabra (sin apellido detectable)
      2+ palabras -> evalúa posibles cortes entre nombres y apellidos, priorizando
                     nombres propios conocidos, nombres compuestos y dos apellidos.

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

    mejor_corte = max(1, n - 2)
    mejor_score = float("-inf")
    for corte in range(1, n):
        score = _score_corte_nombre(partes[:corte], partes[corte:])
        if score > mejor_score:
            mejor_score = score
            mejor_corte = corte

    nombres = partes[:mejor_corte]
    apellidos = partes[mejor_corte:]
    nom1 = nombres[0] if nombres else ""
    nom2 = " ".join(nombres[1:])
    apl1 = apellidos[0] if apellidos else ""
    apl2 = " ".join(apellidos[1:])
    return (apl1, apl2, nom1, nom2)


def _clave_nombre(token: str) -> str:
    txt = quitar_acentos(token or "").lower().strip()
    return re.sub(r"[^a-z0-9 ]+", "", txt)


def _es_nombre_comun(token: str) -> bool:
    return _clave_nombre(token) in _NOMBRES_COMUNES


def _score_corte_nombre(nombres: list[str], apellidos: list[str]) -> float:
    score = 0.0
    for token in nombres:
        clave = _clave_nombre(token)
        es_nombre = clave in _NOMBRES_COMUNES
        score += 3.0 if es_nombre else -0.5
        if clave in _APELLIDOS_COMUNES and not es_nombre:
            score -= 1.0

    joined = [_clave_nombre(t) for t in nombres]
    for i in range(len(joined)):
        for largo in (2, 3):
            frase = " ".join(joined[i:i + largo])
            if frase in _NOMBRES_COMPUESTOS:
                score += 3.0

    if len(apellidos) == 2:
        score += 2.0
    elif len(apellidos) == 1:
        score += 0.5
    elif len(apellidos) > 2:
        score -= 0.2 * (len(apellidos) - 2)

    for token in apellidos:
        clave = _clave_nombre(token)
        if clave in _NOMBRES_COMUNES:
            score -= 1.5
        if clave in _APELLIDOS_COMUNES:
            score += 1.0
        if clave.startswith(("de ", "del ", "de la ", "de las ", "de los ")):
            score += 1.0

    if len(nombres) > 4:
        score -= 0.3 * (len(nombres) - 4)
    return score


def normalizar_nit(nit) -> str:
    if nit is None:
        return ""
    if isinstance(nit, float) and nit.is_integer():
        return str(int(nit))
    raw = str(nit).strip()
    raw = re.sub(r"([,.])0+$", "", raw)
    return re.sub(r"\D", "", raw)


def normalizar_nit_sin_dv(nit) -> str:
    s = normalizar_nit(nit)
    if len(s) == 10 and s[0] in ("8", "9"):
        base, posible_dv = s[:-1], s[-1]
        dv = calcular_dv(base)
        if dv is not None and str(dv) == posible_dv:
            return base
    return s


def es_nit_colombiano(nit) -> bool:
    s = normalizar_nit(nit)
    if len(s) == 9 and s[0] in ("8", "9"):
        return True
    return len(s) == 10 and s[0] in ("8", "9")


def _normalizar_codigo_dane(valor, ancho: int, tomar: str) -> str:
    if valor is None:
        return ""
    digits = re.sub(r"\D", "", str(valor).strip())
    if not digits or set(digits) == {"0"}:
        return ""
    if len(digits) <= ancho:
        return digits.zfill(ancho)
    if tomar == "inicio":
        return digits[:ancho]
    return digits[-ancho:]


def normalizar_departamento(valor) -> str:
    return _normalizar_codigo_dane(valor, 2, "inicio")


def normalizar_municipio(valor) -> str:
    return _normalizar_codigo_dane(valor, 3, "fin")


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
