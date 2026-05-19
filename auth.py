"""Flask-Login + rutas de auth (login / logout / registro)."""
from __future__ import annotations

from functools import wraps

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for,
)
from flask_login import (
    LoginManager, current_user, login_required, login_user, logout_user,
)

from db import Usuario, db


login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para acceder."
login_manager.login_message_category = "error"


@login_manager.user_loader
def cargar_usuario(user_id: str):
    return db.session.get(Usuario, int(user_id))


bp = Blueprint("auth", __name__, url_prefix="/auth")


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            flash("Acceso restringido a administradores.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("auth/login.html")


@bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    remember = bool(request.form.get("remember"))

    user = db.session.query(Usuario).filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Credenciales inválidas.", "error")
        return redirect(url_for("auth.login"))

    login_user(user, remember=remember)
    return redirect(url_for("index"))


@bp.get("/registro")
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    permitir = current_app.config.get("PERMITIR_REGISTRO_PUBLICO", True)
    if not permitir:
        flash("El registro está deshabilitado. Pídele a un administrador que te cree la cuenta.", "error")
        return redirect(url_for("auth.login"))
    return render_template("auth/registro.html")


@bp.post("/registro")
def registro_post():
    permitir = current_app.config.get("PERMITIR_REGISTRO_PUBLICO", True)
    if not permitir:
        return redirect(url_for("auth.login"))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    nombre = (request.form.get("nombre") or "").strip()

    if not email or "@" not in email:
        flash("Email inválido.", "error")
        return redirect(url_for("auth.registro"))
    if len(password) < 8:
        flash("La contraseña debe tener al menos 8 caracteres.", "error")
        return redirect(url_for("auth.registro"))
    if db.session.query(Usuario).filter_by(email=email).first():
        flash("Ya existe una cuenta con ese email.", "error")
        return redirect(url_for("auth.registro"))

    # El primer usuario que se registra es admin automáticamente
    es_primer_usuario = db.session.query(Usuario).count() == 0

    user = Usuario(email=email, nombre=nombre, es_admin=es_primer_usuario)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    flash(f"Cuenta creada{'.' if not es_primer_usuario else ' (eres admin del sistema).'}", "ok")
    return redirect(url_for("index"))


@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
