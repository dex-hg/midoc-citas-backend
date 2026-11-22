
import os
import re

from app.config.supabase import get_supabase
from app.repositories.usuario_repository import UsuarioRepository


class AuthService:

    @staticmethod
    def validar_dni(dni):
        if dni is None:
            return {
                "valido": False,
                "mensaje": "El DNI es obligatorio"
            }

        dni = str(dni).strip()

        if not re.fullmatch(r"[0-9]{8}", dni):
            return {
                "valido": False,
                "mensaje": "El DNI debe contener 8 dígitos"
            }

        return {
            "valido": True,
            "mensaje": "DNI válido"
        }

    @staticmethod
    def validar_correo(correo):
        if not isinstance(correo, str) or not correo.strip():
            return {
                "valido": False,
                "mensaje": "El correo es obligatorio"
            }

        correo = correo.strip().lower()

        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            correo
        ):
            return {
                "valido": False,
                "mensaje": "Correo electrónico inválido"
            }

        return {
            "valido": True,
            "mensaje": "Correo válido"
        }

    @staticmethod
    def validar_password(password):
        if not isinstance(password, str) or not password:
            return {
                "valido": False,
                "mensaje": "La contraseña es obligatoria"
            }

        if len(password) < 8:
            return {
                "valido": False,
                "mensaje": (
                    "La contraseña debe tener al menos 8 caracteres"
                )
            }

        return {
            "valido": True,
            "mensaje": "Contraseña válida"
        }

    @staticmethod
    def obtener_perfiles_por_rol(rol):
        perfiles = {
            "ADMINISTRADOR": [
                "ADMINISTRADOR",
                "RECEPCION",
                "CLIENTE"
            ],
            "DOCTOR": [
                "DOCTOR",
                "CLIENTE"
            ],
            "RECEPCION": [
                "RECEPCION",
                "CLIENTE"
            ],
            "PROMOTOR_BCP": [
                "PROMOTOR_BCP",
                "CLIENTE"
            ],
            "CLIENTE": [
                "CLIENTE"
            ]
        }

        return perfiles.get(rol, [])

    @staticmethod
    def obtener_estado_registro(dni):
        resultado = AuthService.validar_dni(dni)

        if not resultado["valido"]:
            return resultado

        usuario = UsuarioRepository.buscar_por_dni(
            str(dni).strip()
        )

        if usuario is None:
            estado = "CLIENTE_NUEVO"
        elif usuario.get("auth_user_id"):
            estado = "CUENTA_ACTIVA"
        else:
            estado = "CLIENTE_PREEXISTENTE"

        return {
            "valido": True,
            "estado": estado
        }

    @staticmethod
    def enviar_codigo_registro(correo, contrasena):
        resultado_correo = AuthService.validar_correo(correo)

        if not resultado_correo["valido"]:
            return resultado_correo

        resultado_password = AuthService.validar_password(
            contrasena
        )

        if not resultado_password["valido"]:
            return resultado_password

        correo = correo.strip().lower()

        frontend_url = os.getenv(
            "FRONTEND_URL",
            "http://localhost:5173"
        ).rstrip("/")

        supabase = get_supabase()

        supabase.auth.sign_up({
            "email": correo,
            "password": contrasena,
            "options": {
                "email_redirect_to": (
                    f"{frontend_url}/registro"
                )
            }
        })

        return {
            "valido": True,
            "mensaje": (
                "Revisa tu correo electrónico. "
                "Te enviamos un enlace para confirmar "
                "tu cuenta MiDoc."
            )
        }
