
from datetime import date
from supabase import AuthApiError

from app.config.supabase import (
    get_supabase,
    get_supabase_admin
)
from app.services.auth_service import AuthService


class RegistroService:

    @staticmethod
    def crear_cuenta(access_token, datos_cliente):

        if not isinstance(access_token, str) or not access_token.strip():
            return {
                "creado": False,
                "mensaje": "Debes confirmar tu correo primero"
            }, 401

        if not isinstance(datos_cliente, dict):
            return {
                "creado": False,
                "mensaje": "Faltan los datos del cliente"
            }, 400

        dni = str(datos_cliente.get("dni") or "").strip()
        correo = str(
            datos_cliente.get("correo") or ""
        ).strip().lower()

        resultado_dni = AuthService.validar_dni(dni)
        if not resultado_dni["valido"]:
            return {
                "creado": False,
                "mensaje": resultado_dni["mensaje"]
            }, 400

        resultado_correo = AuthService.validar_correo(correo)
        if not resultado_correo["valido"]:
            return {
                "creado": False,
                "mensaje": resultado_correo["mensaje"]
            }, 400

        campos = ["nombres", "apellidos", "telefono", "fechaNacimiento"]

        for campo in campos:
            valor = datos_cliente.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                return {
                    "creado": False,
                    "mensaje": f"El campo {campo} es obligatorio"
                }, 400

        try:
            fecha_nacimiento = date.fromisoformat(
                datos_cliente["fechaNacimiento"]
            )

            if fecha_nacimiento > date.today():
                raise ValueError("Fecha futura")

        except (ValueError, TypeError):
            return {
                "creado": False,
                "mensaje": "Fecha de nacimiento inválida"
            }, 400

        # Validar el token con Supabase Auth.
        try:
            respuesta_auth = get_supabase().auth.get_user(
                access_token.strip()
            )
            auth_user = respuesta_auth.user

        except Exception:
            return {
                "creado": False,
                "mensaje": "Sesión inválida o expirada"
            }, 401

        if auth_user is None:
            return {
                "creado": False,
                "mensaje": "Usuario no autenticado"
            }, 401

        # El correo debe estar confirmado.
        if not auth_user.email_confirmed_at:
            return {
                "creado": False,
                "mensaje": "Debes confirmar tu correo"
            }, 403

        correo_auth = (auth_user.email or "").strip().lower()

        # No confiar únicamente en el correo enviado por React.
        if correo_auth != correo:
            return {
                "creado": False,
                "mensaje": "El correo no coincide con la cuenta verificada"
            }, 403

        # El registro de usuario y cliente se realizará
        # mediante una función SQL transaccional.
        # No se aceptan roles enviados desde React.
        try:
            supabase = get_supabase_admin()

            respuesta = supabase.rpc(
                "registrar_cliente_verificado",
                {
                    "p_auth_user_id": str(auth_user.id),
                    "p_dni": dni,
                    "p_nombres": datos_cliente["nombres"].strip(),
                    "p_apellidos": datos_cliente["apellidos"].strip(),
                    "p_telefono": datos_cliente["telefono"].strip(),
                    "p_correo": correo,
                    "p_fecha_nacimiento": fecha_nacimiento.isoformat()
                }
            ).execute()

            if not respuesta.data:
                return {
                    "creado": False,
                    "mensaje": "No se pudo completar el registro"
                }, 500

            return {
                "creado": True,
                "mensaje": "Cuenta creada correctamente"
            }, 201

        except Exception:
            return {
                "creado": False,
                "mensaje": (
                    "No se pudo completar el registro. "
                    "Comprueba los datos o inténtalo nuevamente."
                )
            }, 409
