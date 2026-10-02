"""Sign in to Supabase Auth from a command-line script (seed/maintenance tools).

Scripts write to RLS-protected tables, so they act as a real admin member, the
same as the app: the password is asked interactively (never an argument or an
environment variable that would end up in shell history) and only the
resulting access token is kept in memory.
"""
import getpass

import httpx

from app.config.settings import get_settings
from app.security.context import set_access_token


async def sign_in_interactively(email: str | None = None) -> str:
    settings = get_settings()
    email = email or input("Correo de un administrador de la app: ").strip()
    password = getpass.getpass("Contraseña (Supabase Auth): ")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{settings.supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": settings.supabase_anon_key},
            json={"email": email, "password": password},
        )
    if response.status_code != 200:
        raise SystemExit("No se pudo iniciar sesión en Supabase Auth (credenciales incorrectas o usuario sin confirmar).")
    token = response.json()["access_token"]
    set_access_token(token)
    return email
