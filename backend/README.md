# GEX Terminal API

Backend FastAPI del GEX Quant Terminal (migración desde Streamlit). Ver el
plan completo del proyecto en `docs/` del repo raíz.

Desplegado en Koyeb, conectado directo a este repo de GitHub — cada push a
`main` que toque `backend/` dispara un redeploy automático (configurado en
el panel del servicio de Koyeb, sin workflow de CI adicional).

## Desarrollo local

```
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements-dev.txt
cp .env.example .env    # completar con tus claves de desarrollo
uvicorn app.main:app --reload --port 8000
```
