"""App Flask - Exógena DIAN

Flujo:
1.  /              -> upload del XLSX MUISCA + datos del informante.
2.  /preview       -> muestra informantes detectados, periodo, tipos no mapeados.
3.  /conceptos     -> formulario para registrar tipos de documento nuevos.
4.  /generar       -> ejecuta los 8 generadores y muestra preview con conteos.
5.  /descargar/<f> -> descarga el XLSX de un formato individual.
6.  /descargar_todo-> descarga UN XLSX con 8 hojas (una por formato).
7.  /directorio    -> directorio de terceros (importar XMLs UBL, ver contenido).
"""
from __future__ import annotations

import io
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

import pandas as pd
from flask import (
    Flask, flash, redirect, render_template, request, send_file, session, url_for
)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from werkzeug.utils import secure_filename

from core import directorio, parser, registry
from generators import GENERADORES
from generators.base import ContextoInformante, _config


BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
OUTPUT = BASE / "output"
UPLOADS.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = "exogena-dian-local-dev"
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB para ZIPs grandes


# ---------------- helpers de sesión ----------------

def _session_path(filename: str) -> Path:
    sid = session.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["sid"] = sid
    d = UPLOADS / sid
    d.mkdir(exist_ok=True)
    return d / filename


def _output_path(filename: str) -> Path:
    sid = session.get("sid") or "anon"
    d = OUTPUT / sid
    d.mkdir(exist_ok=True)
    return d / filename


def _cargar_df():
    p = _session_path("data.parquet")
    if not p.exists():
        return None
    return pd.read_parquet(p)


def _guardar_df(df: pd.DataFrame):
    p = _session_path("data.parquet")
    df.to_parquet(p, index=False)


# ---------------- rutas ----------------

@app.get("/")
def index():
    return render_template("index.html", terceros_cache=directorio.contar())


@app.post("/cargar")
def cargar():
    archivo = request.files.get("archivo")
    if not archivo or archivo.filename == "":
        flash("Selecciona un archivo XLSX.", "error")
        return redirect(url_for("index"))

    nombre = secure_filename(archivo.filename)
    destino = _session_path(nombre)
    archivo.save(destino)

    try:
        df, informantes = parser.cargar_archivo(str(destino))
    except Exception as exc:
        flash(f"Error leyendo el archivo: {exc}", "error")
        return redirect(url_for("index"))

    _guardar_df(df)

    no_mapeados = parser.detectar_tipos_no_mapeados(df, registry.tipos_conocidos())
    session["no_mapeados"] = no_mapeados
    session["informantes"] = [{"nit": i.nit, "nombre": i.nombre} for i in informantes]
    session["archivo_nombre"] = nombre

    if no_mapeados:
        return redirect(url_for("conceptos"))
    return redirect(url_for("preview"))


@app.get("/conceptos")
def conceptos():
    no_mapeados = session.get("no_mapeados", [])
    if not no_mapeados:
        return redirect(url_for("preview"))
    return render_template(
        "conceptos.html",
        tipos=no_mapeados,
        categorias=registry.CATEGORIAS_VALIDAS,
    )


@app.post("/conceptos")
def conceptos_post():
    no_mapeados = session.get("no_mapeados", [])
    for tipo in no_mapeados:
        cat = request.form.get(f"cat_{tipo}", "ignorar")
        signo = int(request.form.get(f"signo_{tipo}", "1"))
        registry.registrar_tipo(tipo, cat, signo)
    session["no_mapeados"] = []
    return redirect(url_for("preview"))


@app.get("/preview")
def preview():
    df = _cargar_df()
    if df is None:
        return redirect(url_for("index"))

    resumen = {
        "filas_totales": len(df),
        "por_tipo": df["tipo_documento"].value_counts().to_dict() if "tipo_documento" in df.columns else {},
        "por_grupo": df["grupo"].value_counts().to_dict() if "grupo" in df.columns else {},
        "rango_fechas": (
            (df["fecha_emision"].min().strftime("%Y-%m-%d") if df["fecha_emision"].notna().any() else "—"),
            (df["fecha_emision"].max().strftime("%Y-%m-%d") if df["fecha_emision"].notna().any() else "—"),
        ) if "fecha_emision" in df.columns else ("—", "—"),
    }

    return render_template(
        "preview.html",
        informantes=session.get("informantes", []),
        archivo=session.get("archivo_nombre", ""),
        resumen=resumen,
    )


@app.post("/generar")
def generar():
    df = _cargar_df()
    if df is None:
        return redirect(url_for("index"))

    nit_inf = request.form.get("nit_informante", "").strip()
    nombre_inf = request.form.get("nombre_informante", "").strip()
    ano = int(request.form.get("ano_gravable", "2025"))
    mes_ini = int(request.form.get("mes_inicio", "1"))
    mes_fin = int(request.form.get("mes_fin", "12"))
    cpt_1001 = int(request.form.get("cpt_1001", str(registry.concepto_default("1001") or 5001)))
    cpt_1007 = int(request.form.get("cpt_1007", str(registry.concepto_default("1007") or 4001)))
    es_part = request.form.get("es_participante") == "on"
    tcon = int(request.form.get("tipo_contrato", "1") or 1)
    nit_part = request.form.get("nit_participante", "").strip()
    tdoc_part = int(request.form.get("tdoc_participante", "31") or 31)
    idfi = request.form.get("id_fideicomiso", "").strip()

    ctx = ContextoInformante(
        nit=nit_inf,
        razon_social=nombre_inf,
        ano_gravable=ano,
        mes_inicio=mes_ini,
        mes_fin=mes_fin,
        concepto_default_1001=cpt_1001,
        concepto_default_1007=cpt_1007,
        es_participante_colaboracion=es_part,
        tipo_contrato=tcon,
        nit_participante=nit_part,
        tdoc_participante=tdoc_part,
        id_fideicomiso=idfi,
    )

    df_filtrado = parser.filtrar_por_periodo(df, ano, mes_ini, mes_fin)

    resultados = {}
    dataframes = {}
    for codigo, GenClass in GENERADORES.items():
        gen = GenClass(ctx)
        salida = gen.generar(df_filtrado)
        path = _output_path(f"F{codigo}_AG{ano}_{nit_inf or 'INFORMANTE'}.xlsx")
        _exportar_xlsx_individual(salida, path, codigo, ctx)
        resultados[codigo] = {
            "filas": len(salida),
            "ruta": path.name,
            "nombre": gen.cfg["nombre"],
        }
        dataframes[codigo] = salida

    # Consolidado: un solo XLSX con 8 hojas
    consolidado_path = _output_path(f"Exogena_AG{ano}_{nit_inf or 'INFORMANTE'}.xlsx")
    _exportar_xlsx_consolidado(dataframes, consolidado_path, ctx)

    session["resultados"] = resultados
    session["consolidado"] = consolidado_path.name
    session["ctx_resumen"] = {
        "nit": nit_inf, "nombre": nombre_inf, "ano": ano,
        "mes_ini": mes_ini, "mes_fin": mes_fin,
    }
    return redirect(url_for("resultado"))


@app.get("/resultado")
def resultado():
    return render_template(
        "resultado.html",
        resultados=session.get("resultados", {}),
        consolidado=session.get("consolidado", ""),
        ctx=session.get("ctx_resumen", {}),
    )


@app.get("/descargar/<codigo>")
def descargar(codigo):
    resultados = session.get("resultados", {})
    info = resultados.get(codigo)
    if not info:
        return redirect(url_for("index"))
    path = _output_path(info["ruta"])
    return send_file(path, as_attachment=True, download_name=info["ruta"])


@app.get("/descargar_todo")
def descargar_todo():
    nombre = session.get("consolidado")
    if not nombre:
        return redirect(url_for("index"))
    path = _output_path(nombre)
    return send_file(path, as_attachment=True, download_name=nombre)


# ---------------- directorio de terceros ----------------

@app.get("/directorio")
def ver_directorio():
    data = directorio.listar()
    df = _cargar_df()
    faltantes = directorio.nits_faltantes_del_df(df) if df is not None else []
    return render_template(
        "directorio.html",
        terceros=data,
        total=len(data),
        faltantes=faltantes,
        tiene_df=df is not None,
    )


@app.post("/directorio/importar")
def importar_directorio():
    archivos = request.files.getlist("xmls")
    if not archivos:
        flash("Selecciona uno o más XML / ZIP.", "error")
        return redirect(url_for("ver_directorio"))

    tmp = Path(tempfile.mkdtemp(prefix="ubl_"))
    try:
        for f in archivos:
            # Conservar estructura de subcarpetas (webkitdirectory envía el path en filename)
            raw = f.filename or ""
            partes = [secure_filename(p) for p in raw.replace("\\", "/").split("/") if p]
            if not partes:
                continue
            destino = tmp.joinpath(*partes)
            destino.parent.mkdir(parents=True, exist_ok=True)
            f.save(destino)
        leidos, actualizados = directorio.importar_carpeta(tmp)
        flash(f"Importados {actualizados} registros de tercero desde {leidos} XML.", "ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return redirect(url_for("ver_directorio"))


@app.post("/directorio/importar_ruta")
def importar_ruta_local():
    ruta = (request.form.get("ruta") or "").strip().strip('"')
    if not ruta:
        flash("Indica la ruta de la carpeta.", "error")
        return redirect(url_for("ver_directorio"))
    carpeta = Path(ruta)
    if not carpeta.exists() or not carpeta.is_dir():
        flash(f"La ruta no existe o no es una carpeta: {ruta}", "error")
        return redirect(url_for("ver_directorio"))
    leidos, actualizados = directorio.importar_carpeta(carpeta)
    flash(f"Importados {actualizados} registros de tercero desde {leidos} XML en {ruta}", "ok")
    return redirect(url_for("ver_directorio"))


@app.post("/directorio/limpiar")
def limpiar_directorio():
    directorio.limpiar()
    flash("Directorio vacío.", "ok")
    return redirect(url_for("ver_directorio"))


@app.post("/directorio/enriquecer")
def enriquecer_directorio():
    df = _cargar_df()
    if df is None:
        flash("No hay archivo cargado. Sube primero el XLSX MUISCA.", "error")
        return redirect(url_for("ver_directorio"))
    faltantes = directorio.nits_faltantes_del_df(df)
    if not faltantes:
        flash("No hay NITs faltantes.", "ok")
        return redirect(url_for("ver_directorio"))
    forzar = request.form.get("forzar") == "on"
    enc, noenc, errores = directorio.enriquecer_lote(faltantes, forzar=forzar, delay=0.3)
    msg = f"RUES: {enc} encontrados, {noenc} no encontrados"
    if errores:
        msg += f", {len(errores)} con error"
    flash(msg, "ok" if enc else "error")
    return redirect(url_for("ver_directorio"))


@app.post("/directorio/editar")
def editar_tercero():
    nid = request.form.get("nid", "").strip()
    if not nid:
        flash("NIT requerido.", "error")
        return redirect(url_for("ver_directorio"))

    datos = {
        "raz":  request.form.get("raz", "").strip(),
        "apl1": request.form.get("apl1", "").strip(),
        "apl2": request.form.get("apl2", "").strip(),
        "nom1": request.form.get("nom1", "").strip(),
        "nom2": request.form.get("nom2", "").strip(),
        "dir":  request.form.get("dir", "").strip(),
        "dpto": int(request.form.get("dpto") or 0),
        "mun":  int(request.form.get("mun") or 0),
        "pais": int(request.form.get("pais") or 169),
    }
    dv_str = request.form.get("dv", "").strip()
    if dv_str.isdigit():
        datos["dv"] = int(dv_str)
    # No persistir valores vacíos
    datos = {k: v for k, v in datos.items() if v not in ("", None)}
    directorio.actualizar_manual(nid, datos)
    flash(f"Tercero {nid} actualizado.", "ok")
    return redirect(url_for("ver_directorio"))


@app.post("/directorio/eliminar")
def eliminar_tercero():
    nid = request.form.get("nid", "").strip()
    if nid:
        directorio.eliminar(nid)
        flash(f"Tercero {nid} eliminado.", "ok")
    return redirect(url_for("ver_directorio"))


# ---------------- exportación XLSX ----------------

def _exportar_xlsx_individual(df: pd.DataFrame, path: Path, codigo: str, ctx: ContextoInformante):
    """XLSX por formato con encabezado meta + datos."""
    wb = Workbook()
    _llenar_hoja(wb.active, df, codigo, ctx, with_meta=True)
    wb.save(path)


def _exportar_xlsx_consolidado(dataframes: dict[str, pd.DataFrame], path: Path, ctx: ContextoInformante):
    """Un XLSX con una hoja por formato + hoja índice."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Índice"
    ws.cell(1, 1, value=f"Exógena DIAN AG{ctx.ano_gravable}").font = Font(bold=True, size=14)
    ws.cell(2, 1, value=f"Informante: {ctx.nit} - {ctx.razon_social}")
    ws.cell(3, 1, value=f"Periodo: meses {ctx.mes_inicio:02d} a {ctx.mes_fin:02d}")
    ws.cell(5, 1, value="Formato").font = Font(bold=True)
    ws.cell(5, 2, value="Descripción").font = Font(bold=True)
    ws.cell(5, 3, value="Registros").font = Font(bold=True)

    cfg = _config()["formatos"]
    fila = 6
    for codigo, df in dataframes.items():
        ws.cell(fila, 1, value=codigo)
        ws.cell(fila, 2, value=cfg[codigo]["nombre"])
        ws.cell(fila, 3, value=len(df))
        fila += 1
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 12

    for codigo, df in dataframes.items():
        hoja = wb.create_sheet(title=f"F{codigo}")
        _llenar_hoja(hoja, df, codigo, ctx, with_meta=False)

    wb.save(path)


def _llenar_hoja(ws, df: pd.DataFrame, codigo: str, ctx: ContextoInformante, with_meta: bool):
    cfg = _config()["formatos"][codigo]
    columnas = cfg["columnas"]
    ws.title = ws.title or f"F{codigo}"

    fila_header = 1
    if with_meta:
        ws.cell(1, 1, value=f"Formato {codigo} v{cfg['version']} - {cfg['nombre']}").font = Font(bold=True, size=12)
        ws.cell(2, 1, value=f"Informante: {ctx.nit} - {ctx.razon_social}")
        ws.cell(3, 1, value=f"Periodo: {ctx.ano_gravable} ({ctx.mes_inicio:02d} a {ctx.mes_fin:02d})")
        ws.cell(4, 1, value=f"Registros: {len(df)}")
        fila_header = 6

    fill = PatternFill("solid", fgColor="FFE4B5")
    bold = Font(bold=True)
    italic = Font(italic=True, color="808080")
    for j, c in enumerate(columnas, 1):
        cel = ws.cell(fila_header, j, value=c["nombre"])
        cel.font = bold
        cel.fill = fill
        ws.cell(fila_header + 1, j, value=c["campo"]).font = italic

    fila_dato = fila_header + 2
    for i, row in df.iterrows():
        for j, c in enumerate(columnas, 1):
            ws.cell(fila_dato + i, j, value=row[c["campo"]])

    for j, c in enumerate(columnas, 1):
        ws.column_dimensions[ws.cell(1, j).column_letter].width = max(12, min(40, len(c["nombre"]) + 2))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
