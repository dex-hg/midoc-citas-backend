
from app.config.supabase import get_supabase_admin


class UsuarioRepository:

    @staticmethod
    def buscar_por_dni(dni):
        supabase = get_supabase_admin()

        respuesta = (
            supabase.table("usuario")
            .select("id_usuario, dni, correo, auth_user_id, id_rol")
            .eq("dni", dni)
            .limit(1)
            .execute()
        )

        return respuesta.data[0] if respuesta.data else None

    @staticmethod
    def buscar_por_correo(correo):
        supabase = get_supabase_admin()

        respuesta = (
            supabase.table("usuario")
            .select("id_usuario, correo")
            .eq("correo", correo)
            .limit(1)
            .execute()
        )

        return respuesta.data[0] if respuesta.data else None

    @staticmethod
    def buscar_por_auth_id(auth_user_id):
        supabase = get_supabase_admin()

        respuesta = (
            supabase.table("usuario")
            .select("id_usuario, id_rol, auth_user_id")
            .eq("auth_user_id", auth_user_id)
            .limit(1)
            .execute()
        )

        return respuesta.data[0] if respuesta.data else None
