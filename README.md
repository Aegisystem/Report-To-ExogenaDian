# Exógena DIAN

App web que convierte exportaciones MUISCA de facturación electrónica a los formatos exógena DIAN 1001, 1005, 1006, 1007, 5247, 5248, 5249 y 5250.

## Funcionalidades

- Sube tu XLSX exportado del portal MUISCA.
- Detecta automáticamente el informante (Recibido → Receptor, Emitido → Emisor).
- Aplica reglas: notas crédito netean, doc. soporte recibido = ingreso/emitido = gasto, nómina electrónica se ignora.
- Genera los 8 formatos en un único XLSX (una hoja por formato + índice) y lo entrega como descarga inmediata sin guardar el archivo de salida en el servidor.
- Directorio de terceros: importa XMLs UBL o XMLs del Prevalidador para completar dirección/dpto/mun/DV.
- Web scraping de RUES como fallback (frágil, mejor esfuerzo).
- Multi-usuario con login (cada contador ve su propia info).

## Stack

- Flask 3 + Flask-SQLAlchemy 2.0 + Flask-Login
- PostgreSQL (Neon en producción, SQLite en local)
- pandas + openpyxl
- Gunicorn (producción)

---

## Desarrollo local

### Docker Compose

```bash
# Requerido: usa la URL de tu Postgres cloud (Neon, Supabase, etc.)
export DATABASE_URL="postgresql://usuario:password@host/db?sslmode=require"

# Opcional: carpeta del Mac que quieres leer desde /directorio/importar_ruta
export HOST_XMLS_DIR="/Users/tuusuario/ruta/a/xmls"

docker compose up --build
# Abre http://127.0.0.1:5050/ y registra tu cuenta
```

En Coolify, crea la variable `DATABASE_URL` con solo el valor de la URL. No incluyas
`DATABASE_URL=`, no uses comillas, y si el password tiene caracteres como `@`, `#`,
`/`, `%` o `&`, usa la version codificada para URL.

Si usas importación por ruta local dentro de Docker, escribe esta ruta en la app:

```text
/host-xmls
```

### Python local

```powershell
# Clonar
git clone <tu-repo>
cd exogena_dian

# Crear venv (opcional)
python -m venv .venv
.venv\Scripts\activate

# Instalar
pip install -r requirements.txt

# Configurar .env
copy .env.example .env
# Edita .env: SECRET_KEY largo, deja DATABASE_URL comentado para SQLite

# Correr
python app.py
# Abre http://127.0.0.1:5000/ y registra tu cuenta (primer usuario = admin)
```

Si ya tienes los JSON del directorio del año pasado, migralos así:

```powershell
python migrate_json.py --email tu@email.com --password TuPassword123 --crear-si-falta
```

---

## Despliegue en Render + Neon

### 1) Postgres en Neon (5 min, gratis)

1. Crea cuenta en https://neon.tech (login con GitHub).
2. **New project** → Postgres 16 → región **AWS US East (Ohio)** o **GCP us-east1** (cercanas a Render Oregon o Frankfurt).
3. Copia el `DATABASE_URL` que te muestra. Empieza con `postgresql://...` y termina con `?sslmode=require`.
4. En la pestaña **Connection pooling**, copia la URL "pooled" (la que tiene `-pooler` en el host). Esa es la que usarás en Render.

### 2) Repositorio GitHub

```powershell
cd C:\Users\dubyc\Projects\exogena_dian
git init
git add .
git commit -m "Initial commit"
# Crea un repo privado en GitHub y enlaza:
git remote add origin git@github.com:tu-usuario/exogena-dian.git
git branch -M main
git push -u origin main
```

### 3) Render (10 min)

1. Crea cuenta en https://render.com (login con GitHub).
2. **New +** → **Web Service** → conecta tu repo `exogena-dian`.
3. Render detecta `render.yaml` automáticamente. Confirma:
   - Region: **Oregon** (gratis) o **Frankfurt** (más cerca de Colombia, $7/mes)
   - Plan: **Free** (con sleep tras 15 min de inactividad) o **Starter** ($7/mes, sin sleep)
4. En **Environment**, pega tu `DATABASE_URL` (la pooled de Neon).
5. `SECRET_KEY` se autogenera. `PERMITIR_REGISTRO_PUBLICO=false` queda por defecto en producción.
6. **Create Web Service**. El primer deploy tarda ~3-4 min.

### 4) Crear tu cuenta admin

Como `PERMITIR_REGISTRO_PUBLICO=false` en producción, no puedes registrarte desde la web. La primera cuenta la creas por shell:

1. En Render, abre tu servicio → **Shell** (pestaña).
2. Corre:
   ```bash
   python migrate_json.py --email tu@email.com --password TuPasswordSeguro --crear-si-falta
   ```
   Esto crea tu usuario (el primero queda como admin). Si quieres también migrar el JSON local del directorio, primero sube los archivos a `config/` o usa el endpoint de importación de XMLs en la UI.

### 5) Custom domain (opcional)

En Render → **Settings** → **Custom domain**. Apuntas un CNAME `exogena.tudominio.com` al hostname que te da Render. SSL automático (Let's Encrypt).

---

## Variables de entorno

| Variable | Producción | Local | Notas |
|---|---|---|---|
| `DATABASE_URL` | URL pooled de Neon | (vacío → SQLite) | Empieza con `postgresql://` |
| `SECRET_KEY` | autogenerada | string aleatorio largo | Sesiones / cookies |
| `PERMITIR_REGISTRO_PUBLICO` | `false` | `true` | Si `false`, solo admin crea cuentas |
| `PERMITIR_RUTA_LOCAL` | `false` | `true` | Botón "importar desde ruta" solo en local |

---

## Backups

Neon hace backups automáticos diarios (free tier: retención 24h, plan Launch: 7 días).

Para backup manual:
```bash
pg_dump $DATABASE_URL > backup_$(date +%F).sql
```

Para restaurar:
```bash
psql $DATABASE_URL < backup_2026-01-15.sql
```

---

## Estructura

```
exogena_dian/
├── app.py                  # Flask + rutas
├── auth.py                 # Login / registro
├── db.py                   # Modelos SQLAlchemy
├── migrate_json.py         # Migración one-shot de JSONs antiguos
├── render.yaml             # Config Render
├── Procfile                # Comando gunicorn
├── runtime.txt             # Versión Python
├── requirements.txt
├── .env.example            # Plantilla; copia a .env
├── config/
│   └── formatos.yaml       # Estructura de los 8 formatos (XSD compacto)
├── core/
│   ├── parser.py           # Lee XLSX MUISCA
│   ├── registry.py         # Catálogo tipos doc + reglas → formatos
│   ├── directorio.py       # Directorio de terceros (BD)
│   ├── helpers.py          # DV, split nombres, etc.
│   └── scrapers/
│       └── rues.py         # Scraper RUES (frágil)
├── generators/             # Un módulo por formato
│   ├── base.py
│   ├── formato_1001.py
│   ├── formato_1005.py
│   ├── formato_1006.py
│   ├── formato_1007.py
│   └── formato_5247-5250.py
├── templates/              # Jinja2
│   ├── base.html
│   ├── index.html
│   ├── conceptos.html
│   ├── preview.html
│   ├── directorio.html
│   └── auth/
│       ├── login.html
│       └── registro.html
├── static/
│   └── styles.css
└── uploads/                # Subidas por usuario (gitignored)
```

---

## Costo estimado

| Servicio | Plan | Costo/mes | Notas |
|---|---|---|---|
| Neon | Free | $0 | 0.5 GB, suficiente para >50K terceros |
| Render | Free | $0 | App duerme tras 15 min sin uso |
| Render | Starter | $7 | Sin sleep, 512 MB RAM |
| Dominio propio | — | ~$1/mes | Opcional |
| **Total** | | **$0 – $8/mes** | |

Si esperas mucho tráfico o más de un usuario activo, sube a Render Standard ($25) y Neon Launch ($19).
