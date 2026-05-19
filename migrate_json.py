"""Script one-shot: migra los JSON de la versión anterior a Postgres.

Uso:
  # Local: usa SQLite por defecto (dev.db) si no hay DATABASE_URL
  python migrate_json.py --email tu@email.com

  # Con Postgres real (Neon, etc.) export DATABASE_URL antes
  $env:DATABASE_URL="postgresql://..."
  python migrate_json.py --email tu@email.com

Idempotente: re-correrlo no duplica (upsert por NIT).
Requiere que el usuario destino ya exista (o lo crea con --crear-si-falta).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import crear_app
from core import directorio
from db import (
    ConceptoDefault, NitNoEncontrado, Tercero, TipoDocumento, Usuario, db,
)


BASE = Path(__file__).resolve().parent
F_DIRECTORIO = BASE / "config" / "directorio.json"
F_NEGATIVOS = BASE / "config" / "directorio_no_encontrados.json"
F_CONCEPTOS = BASE / "config" / "conceptos.json"


def cargar_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [WARN] no se pudo leer {p}: {exc}")
        return None


def migrar(email: str, password: str | None, crear: bool) -> None:
    app = crear_app()
    with app.app_context():
        user = db.session.query(Usuario).filter_by(email=email).first()
        if not user:
            if not crear:
                print(f"[ERROR] No existe usuario {email}. Usa --crear-si-falta o registralo en /auth/registro.")
                sys.exit(1)
            if not password:
                print("[ERROR] Para crear el usuario debes pasar --password.")
                sys.exit(1)
            user = Usuario(email=email, nombre=email.split("@")[0], es_admin=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            print(f"[OK] Usuario {email} creado (admin).")
        uid = user.id

        # --- Directorio ---
        data = cargar_json(F_DIRECTORIO) or {}
        if data:
            existentes = {
                t.nid: t for t in db.session.query(Tercero).filter_by(usuario_id=uid)
            }
            nuevos = 0
            actualizados = 0
            for nid, datos in data.items():
                if not nid:
                    continue
                t = existentes.get(nid)
                if t is None:
                    t = Tercero(usuario_id=uid, nid=nid)
                    db.session.add(t)
                    nuevos += 1
                else:
                    actualizados += 1
                directorio._aplicar_campos(t, datos)
            db.session.commit()
            print(f"[OK] Directorio: {nuevos} nuevos, {actualizados} actualizados ({len(data)} en JSON).")
        else:
            print("-- Directorio JSON vacío o ausente.")

        # --- Negativos ---
        neg = cargar_json(F_NEGATIVOS) or {}
        if neg:
            existentes_neg = {
                row[0] for row in db.session.query(NitNoEncontrado.nid).filter_by(usuario_id=uid)
            }
            nuevos = 0
            for nid in neg.keys():
                if nid in existentes_neg:
                    continue
                db.session.add(NitNoEncontrado(usuario_id=uid, nid=nid, fuente="RUES"))
                nuevos += 1
            db.session.commit()
            print(f"[OK] NITs no encontrados: {nuevos} nuevos.")

        # --- Conceptos del JSON (tipos custom del usuario) ---
        cfg = cargar_json(F_CONCEPTOS) or {}
        tipos_json = cfg.get("tipos_documento", {})
        # Ya hay defaults globales sembrados; aquí solo migramos custom del usuario
        # si difieren del global (en la versión JSON antigua todo era global)
        conceptos = cfg.get("conceptos_por_defecto", {})
        for fmt, c in conceptos.items():
            existente = db.session.query(ConceptoDefault).filter_by(usuario_id=uid, formato=fmt).first()
            if existente:
                existente.concepto = int(c)
            else:
                db.session.add(ConceptoDefault(usuario_id=uid, formato=fmt, concepto=int(c)))
        db.session.commit()
        print(f"[OK] Conceptos por defecto: {len(conceptos)} formatos configurados.")

        print(f"\nMigración completa para {email} (uid={uid}).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", help="Solo si --crear-si-falta")
    ap.add_argument("--crear-si-falta", action="store_true",
                    help="Crea el usuario si no existe (requiere --password)")
    args = ap.parse_args()
    migrar(args.email, args.password, args.crear_si_falta)
