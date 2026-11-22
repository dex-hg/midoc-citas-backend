
import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "Faltan las credenciales de Supabase en .env"
        )

    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_supabase_admin() -> Client:
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not SUPABASE_URL or not service_key:
        raise ValueError(
            "Falta la configuración administrativa de Supabase"
        )

    return create_client(SUPABASE_URL, service_key)
