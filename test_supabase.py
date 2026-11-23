
from app.config.supabase import get_supabase

try:
    supabase = get_supabase()

    respuesta = (
        supabase.table("rol")
        .select("id_rol, nombre")
        .limit(5)
        .execute()
    )

    print("Conexión con Supabase exitosa")
    print("Roles encontrados:", respuesta.data)

except Exception as error:
    print("Error al consultar Supabase:", error)
