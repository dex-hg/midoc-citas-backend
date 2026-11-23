"""Adaptador de citas de Doctor para la API de datos de Supabase."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID

from app.services.doctor_service import (
    AccesoDoctorDenegado,
    CitaDoctor,
    ErrorValidacionDoctor,
    PerfilDoctor,
    RepositorioDoctorNoDisponible,
    ZONA_HORARIA_LIMA,
)

if TYPE_CHECKING:
    from supabase import Client


CAMPOS_CITA = (
    "id_cita,id_doctor,fecha_inicio,estado,duracion_minutos,"
    "doctor!cita_id_doctor_fkey(especialidad!doctor_id_especialidad_fkey(nombre)),"
    "sede!cita_id_sede_fkey(nombre),"
    "consulta!cita_id_consulta_fkey(compra!consulta_id_compra_fkey("
    "cliente!compra_id_cliente_fkey(usuario!cliente_id_usuario_fkey(nombres,apellidos))))"
)
CAMPOS_PERFIL = (
    "id_doctor,id_usuario,usuario!doctor_id_usuario_fkey(nombres,apellidos),"
    "especialidad!doctor_id_especialidad_fkey(nombre),sede!doctor_id_sede_fkey(nombre)"
)
TAMANO_PAGINA = 200
MAXIMO_BIGINT = 2**63 - 1
ERROR_DATOS = "Supabase devolvió datos incompletos para el módulo Doctor."


def _cliente_configurado() -> Client:
    from app.config.supabase import get_supabase

    return get_supabase()


class RepositorioDoctorSupabase:
    def __init__(
        self, obtener_cliente: Callable[[], Client] = _cliente_configurado
    ):
        self._obtener_cliente = obtener_cliente

    def listar_citas(
        self, id_doctor: str, *, fecha: date | None = None, estado: str | None = None
    ) -> list[CitaDoctor]:
        identificador = _identificador_bd(id_doctor, "doctor")
        cliente = self._cliente()
        citas: list[CitaDoctor] = []
        while True:
            consulta = self._citas_del_doctor(cliente, identificador)
            if fecha is not None:
                inicio = datetime.combine(fecha, time.min, ZONA_HORARIA_LIMA)
                fin = datetime.combine(fecha, time.max, ZONA_HORARIA_LIMA)
                consulta = consulta.gte("fecha_inicio", inicio.isoformat()).lte(
                    "fecha_inicio", fin.isoformat()
                )
            if estado is not None:
                consulta = consulta.eq("estado", estado)
            desplazamiento = len(citas)
            pagina = self._filas(
                consulta.order("fecha_inicio").order("id_cita").range(
                    desplazamiento, desplazamiento + TAMANO_PAGINA - 1
                )
            )
            citas.extend(self._convertir_cita(fila) for fila in pagina)
            if len(pagina) < TAMANO_PAGINA:
                return citas

    def obtener_cita(self, id_doctor: str, id_cita: str) -> CitaDoctor | None:
        identificador = _identificador_bd(id_doctor, "doctor")
        identificador_cita = _identificador_bd(id_cita, "cita")
        filas = self._filas(
            self._citas_del_doctor(self._cliente(), identificador)
            .eq("id_cita", identificador_cita)
            .limit(1)
        )
        return self._convertir_cita(filas[0]) if filas else None

    def obtener_perfil(
        self, *, id_doctor: str | None = None, id_usuario: str | None = None
    ) -> PerfilDoctor | None:
        if (id_doctor is None) == (id_usuario is None):
            raise ErrorValidacionDoctor("Se requiere un identificador de perfil.")
        columna = "id_doctor" if id_doctor is not None else "id_usuario"
        identificador = _identificador_bd(id_doctor or id_usuario, "perfil")
        filas = self._filas(
            self._cliente().table("doctor").select(CAMPOS_PERFIL)
            .eq(columna, identificador).limit(2)
        )
        if not filas:
            return None
        if len(filas) != 1:
            raise RepositorioDoctorNoDisponible(ERROR_DATOS)
        fila = filas[0]
        try:
            return PerfilDoctor(
                id_doctor=str(_identificador_bd(fila["id_doctor"], "doctor")),
                id_usuario=str(_identificador_bd(fila["id_usuario"], "usuario")),
                nombre=_nombre_usuario(fila["usuario"]),
                especialidad=_texto(fila["especialidad"]["nombre"]),
                sede=_texto(fila["sede"]["nombre"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RepositorioDoctorNoDisponible(ERROR_DATOS) from error

    def registrar_resultado(self, id_doctor: str, id_cita: str, estado: str) -> str:
        parametros = {
            "p_id_doctor": _identificador_bd(id_doctor, "doctor"),
            "p_id_cita": _identificador_bd(id_cita, "cita"),
            "p_estado": estado,
        }
        resultado = self._ejecutar(
            self._cliente().rpc("registrar_resultado_cita_doctor", parametros)
        )
        if not isinstance(resultado, str):
            raise RepositorioDoctorNoDisponible(ERROR_DATOS)
        return resultado

    def verificar_token(self, token: str) -> dict | None:
        from supabase_auth.errors import AuthApiError

        cliente = self._cliente()
        try:
            respuesta = cliente.auth.get_user(token)
        except AuthApiError as error:
            if error.status in (400, 401, 403, 422):
                return None
            raise RepositorioDoctorNoDisponible(
                "No se pudo verificar la sesión con Supabase."
            ) from error
        except Exception as error:
            raise RepositorioDoctorNoDisponible(
                "No se pudo verificar la sesión con Supabase."
            ) from error

        if respuesta is None or respuesta.user is None:
            return None
        try:
            id_auth = str(UUID(respuesta.user.id))
        except (TypeError, ValueError) as error:
            raise RepositorioDoctorNoDisponible(ERROR_DATOS) from error

        filas = self._filas(
            cliente.table("usuario").select("id_usuario,activo,rol!usuario_id_rol_fkey(nombre)")
            .eq("auth_user_id", id_auth).limit(2)
        )
        if not filas:
            raise AccesoDoctorDenegado("La cuenta de Supabase no está vinculada con MiDoc.")
        if len(filas) != 1:
            raise RepositorioDoctorNoDisponible(ERROR_DATOS)
        fila = filas[0]
        try:
            return {
                "id_usuario": str(_identificador_bd(fila["id_usuario"], "usuario")),
                "rol": _texto(fila["rol"]["nombre"]),
                "activo": fila["activo"] is True,
            }
        except (KeyError, TypeError, ValueError) as error:
            raise RepositorioDoctorNoDisponible(ERROR_DATOS) from error

    def _cliente(self) -> Client:
        try:
            return self._obtener_cliente()
        except (ImportError, ValueError, OSError) as error:
            raise RepositorioDoctorNoDisponible(
                "La conexión de Doctor con Supabase no está disponible."
            ) from error

    @staticmethod
    def _citas_del_doctor(cliente: Client, id_doctor: int):
        return cliente.table("cita").select(CAMPOS_CITA).eq("id_doctor", id_doctor)

    @staticmethod
    def _ejecutar(consulta):
        try:
            return consulta.execute().data
        except Exception as error:
            raise RepositorioDoctorNoDisponible(
                "Supabase no pudo completar la operación de Doctor."
            ) from error

    @classmethod
    def _filas(cls, consulta) -> list[Mapping]:
        datos = cls._ejecutar(consulta)
        if not isinstance(datos, list) or not all(
            isinstance(fila, Mapping) for fila in datos
        ):
            raise RepositorioDoctorNoDisponible(ERROR_DATOS)
        return datos

    @staticmethod
    def _convertir_cita(fila: Mapping) -> CitaDoctor:
        try:
            fecha_inicio = datetime.fromisoformat(fila["fecha_inicio"])
            if fecha_inicio.utcoffset() is None:
                raise ValueError("Se esperaba fecha de inicio con zona horaria.")
            cita_lima = fecha_inicio.astimezone(ZONA_HORARIA_LIMA)
            paciente = fila["consulta"]["compra"]["cliente"]["usuario"]
            return CitaDoctor(
                id_cita=str(_identificador_bd(fila["id_cita"], "cita")),
                id_doctor=str(_identificador_bd(fila["id_doctor"], "doctor")),
                paciente=_nombre_usuario(paciente),
                especialidad=_texto(fila["doctor"]["especialidad"]["nombre"]),
                sede=_texto(fila["sede"]["nombre"]),
                fecha=cita_lima.date(),
                hora=cita_lima.time(),
                duracion_minutos=fila["duracion_minutos"],
                estado=_texto(fila["estado"]),
            )
        except (KeyError, OverflowError, TypeError, ValueError) as error:
            raise RepositorioDoctorNoDisponible(ERROR_DATOS) from error


def _identificador_bd(valor: object, entidad: str) -> int:
    if isinstance(valor, (str, int)) and re.fullmatch(r"[1-9][0-9]{0,18}", str(valor)):
        numero = int(valor)
        if numero <= MAXIMO_BIGINT:
            return numero
    raise ErrorValidacionDoctor(f"El identificador de {entidad} no es válido.")


def _texto(valor: object) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError("Se esperaba texto sin vacíos.")
    return valor.strip()


def _nombre_usuario(usuario: Mapping) -> str:
    return f"{_texto(usuario['nombres'])} {_texto(usuario['apellidos'])}"
