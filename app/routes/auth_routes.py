
from flask import Blueprint, jsonify, request

from app.config.supabase import (
    get_supabase,
    get_supabase_admin
)
from app.repositories.usuario_repository import UsuarioRepository
from app.services.auth_service import AuthService
from app.services.registro_service import RegistroService


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/api/auth"
)


@auth_bp.get("/health")
def health():
    return jsonify({
        "modulo": "auth",
        "status": "ok"
    }), 200


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}

    dni = str(data.get("dni") or "").strip()
    password = data.get("password")

    resultado_dni = AuthService.validar_dni(dni)

    if not resultado_dni["valido"]:
        return jsonify({
            "error": resultado_dni["mensaje"]
        }), 400

    if not isinstance(password, str) or not password:
        return jsonify({
            "error": "Ingresa tu contraseña"
        }), 400

    try:
        usuario = UsuarioRepository.buscar_por_dni(dni)

        if not usuario or not usuario.get("auth_user_id"):
            return jsonify({
                "error": "DNI o contraseña incorrectos"
            }), 401

        correo = usuario.get("correo")

        if not correo:
            return jsonify({
                "error": "DNI o contraseña incorrectos"
            }), 401

        supabase = get_supabase()

        respuesta_auth = supabase.auth.sign_in_with_password({
            "email": correo.strip().lower(),
            "password": password
        })

        if not respuesta_auth.user or not respuesta_auth.session:
            return jsonify({
                "error": "DNI o contraseña incorrectos"
            }), 401

        auth_user = respuesta_auth.user

        if not auth_user.email_confirmed_at:
            return jsonify({
                "error": "Primero debes confirmar tu correo"
            }), 403

        if str(auth_user.id) != str(usuario["auth_user_id"]):
            return jsonify({
                "error": "DNI o contraseña incorrectos"
            }), 401

        admin = get_supabase_admin()

        respuesta_usuario = (
            admin.table("usuario")
            .select(
                "id_usuario, nombres, apellidos, "
                "id_rol, activo"
            )
            .eq("id_usuario", usuario["id_usuario"])
            .single()
            .execute()
        )

        datos_usuario = respuesta_usuario.data

        if not datos_usuario or not datos_usuario["activo"]:
            return jsonify({
                "error": "Esta cuenta está desactivada"
            }), 403

        respuesta_rol = (
            admin.table("rol")
            .select("nombre")
            .eq("id_rol", datos_usuario["id_rol"])
            .single()
            .execute()
        )

        rol = respuesta_rol.data["nombre"]

        perfiles = AuthService.obtener_perfiles_por_rol(rol)

        return jsonify({
            "mensaje": "Inicio de sesión exitoso",
            "accessToken": respuesta_auth.session.access_token,
            "refreshToken": respuesta_auth.session.refresh_token,
            "usuario": {
                "idUsuario": datos_usuario["id_usuario"],
                "dni": dni,
                "nombres": datos_usuario["nombres"],
                "apellidos": datos_usuario["apellidos"],
                "rol": rol,
                "perfiles": perfiles
            }
        }), 200

    except Exception as error:
        # Los errores de credenciales de Supabase no deben
        # convertirse en errores internos del servidor.
        nombre_error = type(error).__name__

        if nombre_error in (
            "AuthApiError",
            "AuthWeakPasswordError",
        ):
            return jsonify({
                "error": "DNI o contraseña incorrectos"
            }), 401

        return jsonify({
            "error": "No se pudo iniciar sesión. Inténtalo nuevamente."
        }), 500


@auth_bp.post("/registro/validar-dni")
def validar_dni():
    data = request.get_json(silent=True) or {}

    resultado = AuthService.validar_dni(
        data.get("dni")
    )

    if not resultado["valido"]:
        return jsonify({
            "error": resultado["mensaje"]
        }), 400

    return jsonify({
        "mensaje": "DNI con formato válido"
    }), 200


@auth_bp.post("/registro/enviar-codigo")
def enviar_codigo():
    data = request.get_json(silent=True) or {}

    correo = data.get("correo")
    contrasena = data.get("contrasena")

    resultado_correo = AuthService.validar_correo(correo)

    if not resultado_correo["valido"]:
        return jsonify({
            "error": resultado_correo["mensaje"]
        }), 400

    resultado_password = AuthService.validar_password(
        contrasena
    )

    if not resultado_password["valido"]:
        return jsonify({
            "error": resultado_password["mensaje"]
        }), 400

    try:
        resultado = AuthService.enviar_codigo_registro(
            correo,
            contrasena
        )

        if not resultado["valido"]:
            return jsonify({
                "error": resultado["mensaje"]
            }), 400

        return jsonify({
            "mensaje": resultado["mensaje"]
        }), 200

    except Exception:
        return jsonify({
            "error": "No se pudo enviar la confirmación."
        }), 502


@auth_bp.post("/registro/verificar-codigo")
def verificar_codigo():
    return jsonify({
        "verificado": False,
        "mensaje": (
            "La verificación se realiza mediante "
            "el enlace enviado por correo."
        )
    }), 501


@auth_bp.post("/registro/crear-cuenta")
def crear_cuenta():
    data = request.get_json(silent=True) or {}

    resultado, codigo_http = RegistroService.crear_cuenta(
        data.get("accessToken"),
        data.get("datosCliente")
    )

    return jsonify(resultado), codigo_http
