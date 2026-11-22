"""API del doctor; la identidad debe provenir de autenticación del servidor."""

from collections.abc import Mapping

from flask import Blueprint, abort, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from app.services.doctor_service import (
    AccesoDoctorDenegado,
    CambioEstadoDoctorNoPermitido,
    CitaDoctorNoEncontrada,
    ErrorValidacionDoctor,
    RepositorioDoctorNoDisponible,
    ServicioDoctor,
)

doctor_bp = Blueprint("doctor", __name__, url_prefix="/api/doctores")


@doctor_bp.get("/health")
def consultar_salud():
    return jsonify({"modulo": "doctores", "status": "ok"}), 200


@doctor_bp.after_request
def evitar_cache_clinica(respuesta):
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@doctor_bp.get("/perfil")
def consultar_perfil():
    referencia = _obtener_referencia_doctor()
    return jsonify(_obtener_perfil_autenticado(referencia)), 200


@doctor_bp.get("/agenda")
def consultar_agenda():
    id_doctor = _obtener_doctor_autenticado()
    filtros = _obtener_filtros()
    resultado = _obtener_servicio().consultar_agenda(id_doctor, **filtros)
    return jsonify(resultado), 200


@doctor_bp.get("/citas")
def consultar_citas():
    id_doctor = _obtener_doctor_autenticado()
    filtros = _obtener_filtros()
    resultado = _obtener_servicio().consultar_citas(id_doctor, **filtros)
    return jsonify(resultado), 200


@doctor_bp.post("/citas/<id_cita>/preparar-estado")
def preparar_estado_cita(id_cita: str):
    id_doctor = _obtener_doctor_autenticado()
    resultado = _obtener_servicio().preparar_estado_cita(
        id_doctor, id_cita, _leer_estado()
    )
    return jsonify(resultado), 200


@doctor_bp.patch("/citas/<id_cita>/estado")
def registrar_resultado(id_cita: str):
    id_doctor = _obtener_doctor_autenticado()
    resultado = _obtener_servicio().registrar_resultado(
        id_doctor, id_cita, _leer_estado()
    )
    return jsonify(resultado), 200


def _leer_estado():
    if request.args:
        raise ErrorValidacionDoctor("Esta operación no acepta parámetros en la URL.")
    if not request.is_json:
        abort(
            415,
            description="Envía un cuerpo JSON con Content-Type application/json.",
        )
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict) or set(datos) != {"estado"}:
        raise ErrorValidacionDoctor("El cuerpo JSON debe contener únicamente 'estado'.")
    return datos["estado"]


def _obtener_doctor_autenticado() -> str:
    referencia = _obtener_referencia_doctor()
    if "id_doctor" in referencia:
        return referencia["id_doctor"]
    return _obtener_perfil_autenticado(referencia)["id_doctor"]


def _obtener_perfil_autenticado(referencia: dict[str, str]) -> dict:
    perfil = _obtener_servicio().consultar_perfil(**referencia)
    if perfil is None:
        abort(403, description="La cuenta no tiene un doctor asociado.")
    return perfil


def _obtener_referencia_doctor() -> dict[str, str]:
    # La sesión compartida se establece en el servidor. Un Bearer se verifica con Auth.
    usuario = getattr(g, "usuario_autenticado", None)
    if usuario is None:
        autorizacion = request.authorization
        if autorizacion is not None and autorizacion.type == "bearer" and autorizacion.token:
            usuario = _obtener_servicio().verificar_token(autorizacion.token)
    if not isinstance(usuario, Mapping):
        abort(401, description="Se requiere una sesión autenticada de doctor.")
    if usuario.get("rol") != "DOCTOR" or usuario.get("activo") is not True:
        abort(403, description="Se requiere una cuenta activa con rol DOCTOR.")
    campo = "id_doctor" if usuario.get("id_doctor") is not None else "id_usuario"
    try:
        identificador = ServicioDoctor.validar_identificador(
            usuario.get(campo), "identificador de la sesión"
        )
    except ErrorValidacionDoctor:
        abort(403, description="La sesión no tiene un doctor válido asociado.")
    return {campo: identificador}


def _obtener_filtros() -> dict:
    if set(request.args) - {"fecha", "estado"}:
        raise ErrorValidacionDoctor("Solo se permiten los filtros 'fecha' y 'estado'.")
    if any(len(request.args.getlist(nombre)) != 1 for nombre in request.args):
        raise ErrorValidacionDoctor("Cada filtro debe enviarse una sola vez.")
    return {"fecha": request.args.get("fecha"), "estado": request.args.get("estado")}


def _obtener_servicio() -> ServicioDoctor:
    servicio = current_app.extensions.get("servicio_doctor")
    if servicio is None:
        return ServicioDoctor()
    if not isinstance(servicio, ServicioDoctor):
        raise RuntimeError("El servicio de doctor no está configurado correctamente.")
    return servicio


@doctor_bp.errorhandler(ErrorValidacionDoctor)
@doctor_bp.errorhandler(AccesoDoctorDenegado)
@doctor_bp.errorhandler(CitaDoctorNoEncontrada)
@doctor_bp.errorhandler(CambioEstadoDoctorNoPermitido)
@doctor_bp.errorhandler(RepositorioDoctorNoDisponible)
def manejar_error_doctor(error: Exception):
    errores = {
        ErrorValidacionDoctor: (400, "SOLICITUD_INVALIDA"),
        AccesoDoctorDenegado: (403, "ACCESO_DOCTOR_DENEGADO"),
        CitaDoctorNoEncontrada: (404, "CITA_NO_ENCONTRADA"),
        CambioEstadoDoctorNoPermitido: (409, "CAMBIO_ESTADO_NO_PERMITIDO"),
        RepositorioDoctorNoDisponible: (503, "ALMACENAMIENTO_NO_DISPONIBLE"),
    }
    estado_http, codigo = next(
        detalles
        for tipo_error, detalles in errores.items()
        if isinstance(error, tipo_error)
    )
    return jsonify({"error": str(error), "codigo": codigo}), estado_http


@doctor_bp.errorhandler(HTTPException)
def manejar_error_http(error: HTTPException):
    respuesta = {"error": error.description, "codigo": f"HTTP_{error.code}"}
    return jsonify(respuesta), error.code


@doctor_bp.errorhandler(Exception)
def manejar_error_inesperado(error: Exception):
    current_app.logger.exception("Error inesperado en el módulo de doctor.")
    return jsonify({
        "error": "No se pudo completar la operación del doctor.",
        "codigo": "ERROR_INTERNO",
    }), 500
