"""App Flask - Exógena DIAN (Postgres + Auth)."""
from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from flask import (
    Flask, flash, redirect, render_template, request, send_file, session, url_for,
)
from flask_login import login_required
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from werkzeug.utils import secure_filename

from auth import bp as auth_bp, login_manager
from core import directorio, helpers, parser, registry
from db import db, migrar_codigos_territoriales, usuario_actual_id
from generators import GENERADORES
from generators.base import ContextoInformante, _config


load_dotenv()

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)


def _normalizar_database_url(raw: str | None) -> str:
    db_url = (raw or "").strip().strip('"').strip("'")
    if not db_url:
        return "sqlite:///dev.db"

    # Render/Heroku usan postgres:// pero SQLAlchemy 2.0 quiere postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        make_url(db_url)
    except ArgumentError as exc:
        raise RuntimeError(
            "DATABASE_URL invalida. En Coolify pon solo el valor de la URL, sin "
            "'DATABASE_URL=', sin comillas, y con caracteres especiales del password "
            "codificados para URL."
        ) from exc
    return db_url


def crear_app() -> Flask:
    app = Flask(__name__)

    db_url = _normalizar_database_url(os.environ.get("DATABASE_URL"))

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 300}
    app.secret_key = os.environ.get("SECRET_KEY", "dev-not-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024
    app.config["PERMITIR_REGISTRO_PUBLICO"] = (
        os.environ.get("PERMITIR_REGISTRO_PUBLICO", "true").lower() != "false"
    )

    db.init_app(app)
    login_manager.init_app(app)
    app.register_blueprint(auth_bp)

    with app.app_context():
        db.create_all()
        migrar_codigos_territoriales()
        registry.sembrar_catalogo_global()

    _registrar_rutas(app)
    return app


# ---------------- helpers de sesión web ----------------

def _user_dir(sub: str) -> Path:
    uid = usuario_actual_id()
    d = UPLOADS / f"u{uid}"
    d.mkdir(exist_ok=True)
    if sub:
        d = d / sub
        d.mkdir(exist_ok=True, parents=True)
    return d


def _cargar_df():
    p = _user_dir("") / "data.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p)


def _guardar_df(df: pd.DataFrame):
    p = _user_dir("") / "data.parquet"
    df.to_parquet(p, index=False)


def _informante_actual() -> dict[str, str] | None:
    informantes = session.get("informantes", [])
    if not informantes:
        return None
    primero = informantes[0] or {}
    nit = str(primero.get("nit", "")).strip()
    nombre = str(primero.get("nombre", "")).strip()
    if not nit:
        return None
    return {"nit": nit, "nombre": nombre, "tdoc": str(helpers.inferir_tipo_documento(nit))}


def _entero_form(valor, default: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return default


# ---------------- rutas ----------------

def _registrar_rutas(app: Flask) -> None:

    @app.get("/")
    @login_required
    def index():
        return render_template("index.html", terceros_cache=directorio.contar())


    @app.post("/cargar")
    @login_required
    def cargar():
        archivo = request.files.get("archivo")
        if not archivo or archivo.filename == "":
            flash("Selecciona un archivo XLSX.", "error")
            return redirect(url_for("index"))

        nombre = secure_filename(archivo.filename)
        destino = _user_dir("") / nombre
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
    @login_required
    def conceptos():
        no_mapeados = session.get("no_mapeados", [])
        if not no_mapeados:
            return redirect(url_for("preview"))
        return render_template("conceptos.html", tipos=no_mapeados, categorias=registry.CATEGORIAS_VALIDAS)


    @app.post("/conceptos")
    @login_required
    def conceptos_post():
        no_mapeados = session.get("no_mapeados", [])
        for tipo in no_mapeados:
            cat = request.form.get(f"cat_{tipo}", "ignorar")
            signo = int(request.form.get(f"signo_{tipo}", "1"))
            registry.registrar_tipo(tipo, cat, signo)
        session["no_mapeados"] = []
        return redirect(url_for("preview"))


    @app.get("/preview")
    @login_required
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
            informante=_informante_actual(),
            archivo=session.get("archivo_nombre", ""),
            resumen=resumen,
            concepto_1001=registry.concepto_default("1001") or 5016,
            concepto_1007=registry.concepto_default("1007") or 4001,
            concepto_5248=4010,
        )


    @app.post("/generar")
    @login_required
    def generar():
        df = _cargar_df()
        if df is None:
            return redirect(url_for("index"))

        informante = _informante_actual()
        if not informante:
            flash("No se detectó el NIT del informante en el XLSX. Revisa el archivo cargado.", "error")
            return redirect(url_for("preview"))

        modo_colaboracion = request.form.get("modo_colaboracion", "")
        if modo_colaboracion not in ("si", "no"):
            flash("Indica obligatoriamente si es consorcio / contrato de colaboración.", "error")
            return redirect(url_for("preview"))

        nit_inf = informante["nit"]
        nombre_inf = informante["nombre"]
        ano = _entero_form(request.form.get("ano_gravable"), 2025)
        mes_ini = _entero_form(request.form.get("mes_inicio"), 1)
        mes_fin = _entero_form(request.form.get("mes_fin"), 12)
        cpt_1001 = _entero_form(request.form.get("cpt_1001"), registry.concepto_default("1001") or 5016)
        es_part = modo_colaboracion == "si"
        if es_part:
            cpt_1007 = _entero_form(request.form.get("cpt_5248"), 4010)
            tcon = _entero_form(request.form.get("tipo_contrato"), 2)
            nit_part = nit_inf
            tdoc_part = helpers.inferir_tipo_documento(nit_inf)
        else:
            cpt_1007 = _entero_form(request.form.get("cpt_1007"), registry.concepto_default("1007") or 4001)
            tcon = 2
            nit_part = ""
            tdoc_part = 31
        idfi = request.form.get("id_fideicomiso", "").strip()

        ctx = ContextoInformante(
            nit=nit_inf, razon_social=nombre_inf, ano_gravable=ano,
            mes_inicio=mes_ini, mes_fin=mes_fin,
            concepto_default_1001=cpt_1001, concepto_default_1007=cpt_1007,
            es_participante_colaboracion=es_part, tipo_contrato=tcon,
            nit_participante=nit_part, tdoc_participante=tdoc_part,
            id_fideicomiso=idfi,
        )

        df_filtrado = parser.filtrar_por_periodo(df, ano, mes_ini, mes_fin)

        dataframes = {}
        formatos_objetivo = (
            ("5247", "5248", "5249", "5250") if es_part
            else ("1001", "1005", "1006", "1007")
        )
        for codigo in formatos_objetivo:
            GenClass = GENERADORES[codigo]
            gen = GenClass(ctx)
            dataframes[codigo] = gen.generar(df_filtrado)

        nit_archivo = secure_filename(nit_inf) or "INFORMANTE"
        nombre_archivo = f"Exogena_AG{ano}_{nit_archivo}.xlsx"
        archivo = _crear_xlsx_consolidado(dataframes, ctx, df_filtrado)
        return send_file(
            archivo,
            as_attachment=True,
            download_name=nombre_archivo,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


    @app.get("/directorio")
    @login_required
    def ver_directorio():
        data = directorio.listar()
        df = _cargar_df()
        faltantes = directorio.nits_faltantes_del_df(df) if df is not None else []
        return render_template("directorio.html", terceros=data, total=len(data),
                               faltantes=faltantes, tiene_df=df is not None)


    @app.post("/directorio/importar")
    @login_required
    def importar_directorio():
        archivos = request.files.getlist("xmls")
        if not archivos:
            flash("Selecciona uno o más XML / ZIP.", "error")
            return redirect(url_for("ver_directorio"))
        tmp = Path(tempfile.mkdtemp(prefix="ubl_"))
        try:
            for f in archivos:
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
    @login_required
    def importar_ruta_local():
        # Solo permitir esta función si estás en localhost (no en Render)
        if os.environ.get("PERMITIR_RUTA_LOCAL", "false").lower() != "true":
            flash("Importación por ruta local deshabilitada en este entorno. Usa subida de archivos.", "error")
            return redirect(url_for("ver_directorio"))
        ruta = (request.form.get("ruta") or "").strip().strip('"')
        if not ruta:
            flash("Indica la ruta de la carpeta.", "error")
            return redirect(url_for("ver_directorio"))
        carpeta = Path(ruta)
        if not carpeta.exists() or not carpeta.is_dir():
            flash(f"La ruta no existe: {ruta}", "error")
            return redirect(url_for("ver_directorio"))
        leidos, actualizados = directorio.importar_carpeta(carpeta)
        flash(f"Importados {actualizados} registros desde {leidos} XML en {ruta}", "ok")
        return redirect(url_for("ver_directorio"))


    @app.post("/directorio/limpiar")
    @login_required
    def limpiar_directorio():
        directorio.limpiar()
        flash("Directorio vacío.", "ok")
        return redirect(url_for("ver_directorio"))


    @app.post("/directorio/enriquecer")
    @login_required
    def enriquecer_directorio():
        df = _cargar_df()
        if df is None:
            flash("Sube primero el XLSX MUISCA.", "error")
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


    @app.post("/directorio/recalcular_nombres")
    @login_required
    def recalcular_nombres_directorio():
        df = _cargar_df()
        if df is None:
            flash("Sube primero el XLSX MUISCA.", "error")
            return redirect(url_for("ver_directorio"))
        actualizados = directorio.recalcular_nombres_desde_df(df)
        flash(f"Nombres recalculados para {actualizados} personas naturales.", "ok")
        return redirect(url_for("ver_directorio"))


    @app.post("/directorio/editar")
    @login_required
    def editar_tercero():
        nid = request.form.get("nid", "").strip()
        if not nid:
            flash("NIT requerido.", "error")
            return redirect(url_for("ver_directorio"))
        datos = {
            "raz": request.form.get("raz", "").strip(),
            "apl1": request.form.get("apl1", "").strip(),
            "apl2": request.form.get("apl2", "").strip(),
            "nom1": request.form.get("nom1", "").strip(),
            "nom2": request.form.get("nom2", "").strip(),
            "dir": request.form.get("dir", "").strip(),
            "dpto": request.form.get("dpto", "").strip(),
            "mun": request.form.get("mun", "").strip(),
            "pais": int(request.form.get("pais") or 169),
        }
        dv_str = request.form.get("dv", "").strip()
        if dv_str.isdigit():
            datos["dv"] = int(dv_str)
        datos = {k: v for k, v in datos.items() if v not in ("", None)}
        directorio.actualizar_manual(nid, datos)
        flash(f"Tercero {nid} actualizado.", "ok")
        return redirect(url_for("ver_directorio"))


    @app.post("/directorio/eliminar")
    @login_required
    def eliminar_tercero():
        nid = request.form.get("nid", "").strip()
        if nid:
            directorio.eliminar(nid)
            flash(f"Tercero {nid} eliminado.", "ok")
        return redirect(url_for("ver_directorio"))


# ---------------- exportación XLSX en memoria ----------------


def _crear_xlsx_consolidado(dataframes: dict[str, pd.DataFrame], ctx: ContextoInformante, df_origen: pd.DataFrame) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    _llenar_resumen(ws, df_origen, ctx)
    ws = wb.create_sheet(title="Informe")
    _llenar_informe_referencia(ws, df_origen, ctx)
    ws = wb.create_sheet(title="Índice")
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
    archivo = io.BytesIO()
    wb.save(archivo)
    archivo.seek(0)
    return archivo


def _resumen_empresa(df: pd.DataFrame, ctx: ContextoInformante) -> dict[str, float]:
    catalogo = registry.catalogo_tipos()
    formato_ingresos = "5248" if ctx.es_participante_colaboracion else "1007"
    formato_gastos = "5247" if ctx.es_participante_colaboracion else "1001"
    reglas_ingresos = registry.regla_para_formato(formato_ingresos)
    reglas_gastos = registry.regla_para_formato(formato_gastos)
    out = {
        "ingresos_brutos": 0.0,
        "devoluciones_ingresos": 0.0,
        "iva_generado": 0.0,
        "total_ingresos": 0.0,
        "gastos_brutos": 0.0,
        "devoluciones_gastos": 0.0,
        "iva_descontable": 0.0,
        "total_gastos": 0.0,
        "nomina": 0.0,
    }

    for _, row in df.iterrows():
        tipo = str(row.get("tipo_documento", "") or "").strip()
        grupo = str(row.get("grupo", "") or "").strip()
        if registry.es_tipo_nomina(tipo):
            cat, signo = "nomina", 1
        else:
            info = catalogo.get(tipo, {})
            cat = str(info.get("categoria", "") or "")
            signo = int(info.get("signo", 1) or 1)
        if not cat or cat in ("ignorar",):
            continue

        base = float(row.get("base", 0) or 0)
        iva = float(row.get("iva", 0) or 0)
        total = float(row.get("total", 0) or 0)
        base_firmada = base * signo
        iva_firmado = iva * signo
        total_firmado = total * signo
        regla = (cat, grupo)

        if cat == "nomina":
            out["nomina"] += max(base_firmada, 0)
        elif regla in reglas_ingresos:
            if base_firmada >= 0:
                out["ingresos_brutos"] += base_firmada
            else:
                out["devoluciones_ingresos"] += abs(base_firmada)
            out["iva_generado"] += iva_firmado
            out["total_ingresos"] += total_firmado
        elif regla in reglas_gastos:
            if base_firmada >= 0:
                out["gastos_brutos"] += base_firmada
            else:
                out["devoluciones_gastos"] += abs(base_firmada)
            out["iva_descontable"] += iva_firmado
            out["total_gastos"] += total_firmado

    out["ingresos_netos"] = out["ingresos_brutos"] - out["devoluciones_ingresos"]
    out["gastos_netos"] = out["gastos_brutos"] - out["devoluciones_gastos"]
    out["utilidad_estimada"] = out["ingresos_netos"] - out["gastos_netos"] - out["nomina"]
    return out


def _valor_resumen(ws, fila: int, etiqueta: str, valor: float | None, *, fuerte: bool = False) -> None:
    ws.cell(fila, 1, value=etiqueta)
    ws.cell(fila, 2, value="$" if valor is not None else "")
    ws.cell(fila, 3, value="-" if valor in (None, 0) else round(valor))
    for col in range(1, 4):
        celda = ws.cell(fila, col)
        celda.border = Border(bottom=Side(style="thin", color="D1D5DB"))
        celda.alignment = Alignment(vertical="center")
        if fuerte:
            celda.font = Font(bold=True)
            celda.fill = PatternFill("solid", fgColor="F3F4F6")
    ws.cell(fila, 2).alignment = Alignment(horizontal="center", vertical="center")
    ws.cell(fila, 3).alignment = Alignment(horizontal="right", vertical="center")
    if valor not in (None, 0):
        ws.cell(fila, 3).number_format = '#,##0;[Red]-#,##0;"-"'


def _seccion_resumen(ws, fila: int, titulo: str) -> None:
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=3)
    celda = ws.cell(fila, 1, value=titulo)
    celda.font = Font(bold=True, color="FFFFFF")
    celda.fill = PatternFill("solid", fgColor="1E3A8A")
    celda.alignment = Alignment(horizontal="left", vertical="center")


def _llenar_resumen(ws, df: pd.DataFrame, ctx: ContextoInformante) -> None:
    resumen = _resumen_empresa(df, ctx)
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:C1")
    ws.cell(1, 1, value="Resumen financiero").font = Font(bold=True, size=18, color="1E3A8A")
    ws.cell(2, 1, value=f"{ctx.razon_social} · NIT {ctx.nit}")
    ws.cell(3, 1, value=f"Año gravable {ctx.ano_gravable} · Meses {ctx.mes_inicio:02d} a {ctx.mes_fin:02d}")
    ws.cell(4, 1, value="Valores estimados desde el XLSX MUISCA cargado. Utilidad calculada sobre bases sin IVA.")
    ws.cell(4, 1).font = Font(italic=True, color="6B7280")

    fila = 6
    _seccion_resumen(ws, fila, "Ingresos")
    fila += 1
    _valor_resumen(ws, fila, "Ingresos brutos", resumen["ingresos_brutos"])
    fila += 1
    _valor_resumen(ws, fila, "Devoluciones, rebajas y descuentos", resumen["devoluciones_ingresos"])
    fila += 1
    _valor_resumen(ws, fila, "Ingresos netos", resumen["ingresos_netos"], fuerte=True)
    fila += 1
    _valor_resumen(ws, fila, "IVA generado neto", resumen["iva_generado"])
    fila += 1
    _valor_resumen(ws, fila, "Total ingresos con IVA", resumen["total_ingresos"], fuerte=True)

    fila += 2
    _seccion_resumen(ws, fila, "Gastos y costos")
    fila += 1
    _valor_resumen(ws, fila, "Gastos / costos brutos", resumen["gastos_brutos"])
    fila += 1
    _valor_resumen(ws, fila, "Devoluciones en gastos", resumen["devoluciones_gastos"])
    fila += 1
    _valor_resumen(ws, fila, "Gastos / costos netos", resumen["gastos_netos"], fuerte=True)
    fila += 1
    _valor_resumen(ws, fila, "IVA descontable / mayor valor neto", resumen["iva_descontable"])
    fila += 1
    _valor_resumen(ws, fila, "Total gastos con IVA", resumen["total_gastos"], fuerte=True)

    fila += 2
    _seccion_resumen(ws, fila, "Nómina")
    fila += 1
    _valor_resumen(ws, fila, "Nómina identificada", resumen["nomina"], fuerte=True)

    fila += 2
    _seccion_resumen(ws, fila, "Resultado estimado")
    fila += 1
    _valor_resumen(ws, fila, "Utilidad estimada sin IVA", resumen["utilidad_estimada"], fuerte=True)

    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 5
    ws.column_dimensions["C"].width = 18
    for row in range(1, fila + 1):
        ws.row_dimensions[row].height = 24


def _bordes_informe(row_inicio: int, row_fin: int, row: int, col: int) -> Border:
    return Border(
        left=Side(style="thick" if col == 1 else "thin", color="000000"),
        right=Side(style="thick" if col == 3 else "thin", color="000000"),
        top=Side(style="thick" if row == row_inicio else "thin", color="000000"),
        bottom=Side(style="thick" if row == row_fin else "thin", color="000000"),
    )


def _fila_informe(ws, fila: int, etiqueta: str, valor: float | None, row_inicio: int, row_fin: int) -> None:
    ws.cell(fila, 1, value=etiqueta)
    ws.cell(fila, 2, value="$")
    ws.cell(fila, 3, value="-" if valor in (None, 0) else round(valor))
    for col in range(1, 4):
        celda = ws.cell(fila, col)
        celda.border = _bordes_informe(row_inicio, row_fin, fila, col)
        celda.font = Font(size=20)
        celda.alignment = Alignment(vertical="center")
    ws.cell(fila, 2).alignment = Alignment(horizontal="center", vertical="center")
    ws.cell(fila, 3).alignment = Alignment(horizontal="right", vertical="center")
    if valor not in (None, 0):
        ws.cell(fila, 3).number_format = '#,##0;[Red]-#,##0;"-"'


def _bloque_informe(ws, fila: int, filas: list[tuple[str, float | None]]) -> int:
    row_inicio = fila
    row_fin = fila + len(filas) - 1
    for etiqueta, valor in filas:
        _fila_informe(ws, fila, etiqueta, valor, row_inicio, row_fin)
        fila += 1
    return fila + 2


def _llenar_informe_referencia(ws, df: pd.DataFrame, ctx: ContextoInformante) -> None:
    resumen = _resumen_empresa(df, ctx)
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 5
    ws.column_dimensions["C"].width = 20

    fila = 2
    fila = _bloque_informe(ws, fila, [
        ("TOTAL FACTURADO", resumen["ingresos_netos"]),
        ("IVA GENERADO", resumen["iva_generado"]),
        ("TOTAL", resumen["total_ingresos"]),
    ])
    fila = _bloque_informe(ws, fila, [
        ("TOTAL GASTOS", resumen["gastos_netos"]),
        ("IVA DESCONTABLE/MAYOR VALOR", resumen["iva_descontable"]),
        ("TOTAL GASTOS IVA INCLUÍDO", resumen["total_gastos"]),
    ])
    fila = _bloque_informe(ws, fila, [
        ("NOMINA", resumen["nomina"]),
    ])
    _bloque_informe(ws, fila, [
        ("UTILIDAD", resumen["utilidad_estimada"]),
    ])

    for row in range(1, fila + 3):
        ws.row_dimensions[row].height = 36


def _llenar_hoja(ws, df: pd.DataFrame, codigo: str, ctx: ContextoInformante, with_meta: bool):
    cfg = _config()["formatos"][codigo]
    columnas = cfg["columnas"]
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


app = crear_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
