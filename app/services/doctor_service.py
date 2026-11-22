"""Consultas y registro de resultados de atención del doctor."""

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol


ESTADOS_CITA = frozenset({"AGENDADA", "ATENDIDA", "CANCELADA", "NO_ASISTIO"})
ESTADOS_RESULTADO = frozenset({"ATENDIDA", "NO_ASISTIO"})
ZONA_HORARIA_LIMA = timezone(timedelta(hours=-5))


class ErrorValidacionDoctor(ValueError):
    """La solicitud contiene identificadores, fechas o estados inválidos."""


class CitaDoctorNoEncontrada(LookupError):
    """La cita no existe dentro de las citas del doctor solicitado."""


class CambioEstadoDoctorNoPermitido(ValueError):
    """La cita ya no permite registrar un resultado de atención."""


class RepositorioDoctorNoDisponible(RuntimeError):
    """El proveedor de citas no está configurado o no puede responder."""


class AccesoDoctorDenegado(PermissionError):
    """El usuario autenticado no tiene una cuenta de MiDoc habilitada."""


@dataclass(frozen=True)
class CitaDoctor:
    """Cita con fecha y hora locales de Lima, independiente del almacenamiento."""

    id_cita: str
    id_doctor: str
    paciente: str
    especialidad: str
    sede: str
    fecha: date
    hora: time
    duracion_minutos: int
    estado: str


@dataclass(frozen=True)
class PerfilDoctor:
    id_doctor: str
    id_usuario: str
    nombre: str
    especialidad: str
    sede: str


class RepositorioDoctor(Protocol):
    """Acceso al perfil, las citas y los resultados de atención."""

    def listar_citas(
        self, id_doctor: str, *, fecha: date | None, estado: str | None
    ) -> Sequence[CitaDoctor]:
        """Devuelve las citas del doctor o lanza RepositorioDoctorNoDisponible."""
        ...

    def obtener_cita(self, id_doctor: str, id_cita: str) -> CitaDoctor | None:
        """Busca una cita del doctor; devuelve None cuando no existe."""
        ...

    def obtener_perfil(
        self, *, id_doctor: str | None, id_usuario: str | None
    ) -> PerfilDoctor | None:
        ...

    def registrar_resultado(self, id_doctor: str, id_cita: str, estado: str) -> str:
        """Aplica la transición de estado y devuelve el resultado de la escritura."""
        ...

    def verificar_token(self, token: str) -> dict | None:
        ...


class ServicioDoctor:
    """Reglas independientes de Flask, Supabase y del motor de base de datos."""

    def __init__(self, repositorio: RepositorioDoctor | None = None):
        self._repositorio = repositorio

    def verificar_token(self, token: str) -> dict | None:
        if len(token) > 8192 or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", token):
            return None
        return self._obtener_repositorio().verificar_token(token)

    @staticmethod
    def validar_identificador(valor: object, nombre: str) -> str:
        if isinstance(valor, bool) or not isinstance(valor, (str, int)):
            raise ErrorValidacionDoctor(f"El {nombre} no es válido.")
        identificador = str(valor).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", identificador):
            raise ErrorValidacionDoctor(f"El {nombre} no es válido.")
        if identificador.isdecimal() and int(identificador) <= 0:
            raise ErrorValidacionDoctor(f"El {nombre} debe ser positivo.")
        return identificador

    @staticmethod
    def validar_fecha(valor: object) -> date:
        if not isinstance(valor, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valor
        ):
            raise ErrorValidacionDoctor("La fecha debe tener formato AAAA-MM-DD.")
        try:
            return date.fromisoformat(valor)
        except ValueError as error:
            raise ErrorValidacionDoctor("La fecha indicada no existe.") from error

    @staticmethod
    def validar_estado(valor: object) -> str:
        if not isinstance(valor, str) or valor.strip().upper() not in ESTADOS_CITA:
            raise ErrorValidacionDoctor(
                "El estado debe ser AGENDADA, ATENDIDA, CANCELADA o NO_ASISTIO."
            )
        return valor.strip().upper()

    def consultar_citas(
        self, id_doctor: object, fecha: object = None, estado: object = None
    ) -> dict:
        identificador = self.validar_identificador(
            id_doctor, "identificador del doctor"
        )
        fecha_filtro = self.validar_fecha(fecha) if fecha is not None else None
        estado_filtro = self.validar_estado(estado) if estado is not None else None
        repositorio = self._obtener_repositorio()
        try:
            citas = repositorio.listar_citas(
                identificador, fecha=fecha_filtro, estado=estado_filtro
            )
        except OSError as error:
            raise RepositorioDoctorNoDisponible(
                "No se pudieron consultar las citas. Inténtalo nuevamente."
            ) from error
        if not isinstance(citas, Sequence) or isinstance(citas, (str, bytes)):
            raise RepositorioDoctorNoDisponible(
                "El proveedor devolvió citas inválidas."
            )

        citas_filtradas = []
        for registro in citas:
            cita = self._validar_cita(registro)
            if cita.id_doctor != identificador:
                continue
            if fecha_filtro is not None and cita.fecha != fecha_filtro:
                continue
            if estado_filtro is not None and cita.estado != estado_filtro:
                continue
            citas_filtradas.append(cita)
        citas_filtradas.sort(key=lambda cita: (cita.fecha, cita.hora, cita.id_cita))
        return {
            "id_doctor": identificador,
            "filtros": {
                "fecha": fecha_filtro.isoformat() if fecha_filtro else None,
                "estado": estado_filtro,
            },
            "total": len(citas_filtradas),
            "citas": [self._serializar_cita(cita) for cita in citas_filtradas],
        }

    def consultar_agenda(
        self, id_doctor: object, fecha: object = None, estado: object = None
    ) -> dict:
        fecha_agenda = fecha
        if fecha_agenda is None:
            fecha_agenda = datetime.now(ZONA_HORARIA_LIMA).date().isoformat()
        resultado = self.consultar_citas(id_doctor, fecha_agenda, estado)
        return {**resultado, "fecha": resultado["filtros"]["fecha"]}

    def preparar_estado_cita(
        self, id_doctor: object, id_cita: object, estado: object
    ) -> dict:
        identificador = self.validar_identificador(
            id_doctor, "identificador del doctor"
        )
        identificador_cita = self.validar_identificador(
            id_cita, "identificador de la cita"
        )
        estado_solicitado = self._validar_estado_resultado(estado)
        repositorio = self._obtener_repositorio()
        try:
            registro = repositorio.obtener_cita(identificador, identificador_cita)
        except OSError as error:
            raise RepositorioDoctorNoDisponible(
                "No se pudo consultar la cita. Inténtalo nuevamente."
            ) from error
        if registro is None:
            raise CitaDoctorNoEncontrada("No se encontró la cita del doctor.")
        cita = self._validar_cita(registro)
        if cita.id_doctor != identificador or cita.id_cita != identificador_cita:
            raise CitaDoctorNoEncontrada("No se encontró la cita del doctor.")
        if cita.estado != "AGENDADA":
            raise CambioEstadoDoctorNoPermitido(
                "Solo una cita AGENDADA puede pasar a ATENDIDA o NO_ASISTIO."
            )
        return {
            "id_doctor": identificador,
            "id_cita": identificador_cita,
            "estado_actual": cita.estado,
            "estado_solicitado": estado_solicitado,
            "preparado": True,
            "persistido": False,
            "mensaje": (
                "Cambio validado. Su registro en la base de datos está pendiente."
            ),
        }

    def consultar_perfil(
        self, *, id_doctor: str | None = None, id_usuario: str | None = None
    ) -> dict | None:
        repositorio = self._obtener_repositorio()
        perfil = repositorio.obtener_perfil(id_doctor=id_doctor, id_usuario=id_usuario)
        if perfil is None:
            return None
        if (
            (id_doctor is not None and perfil.id_doctor != id_doctor)
            or (id_usuario is not None and perfil.id_usuario != id_usuario)
        ):
            return None
        return {
            "id_doctor": perfil.id_doctor,
            "nombre": perfil.nombre,
            "especialidad": perfil.especialidad,
            "sede": perfil.sede,
        }

    def registrar_resultado(
        self, id_doctor: object, id_cita: object, estado: object
    ) -> dict:
        identificador = self.validar_identificador(
            id_doctor, "identificador del doctor"
        )
        identificador_cita = self.validar_identificador(
            id_cita, "identificador de la cita"
        )
        estado_solicitado = self._validar_estado_resultado(estado)
        repositorio = self._obtener_repositorio()
        resultado = repositorio.registrar_resultado(
            identificador, identificador_cita, estado_solicitado
        )
        if resultado == "NO_ENCONTRADA":
            raise CitaDoctorNoEncontrada("No se encontró la cita del doctor.")
        if resultado == "NO_INICIADA":
            raise CambioEstadoDoctorNoPermitido(
                "Podrás registrar el resultado desde el inicio de la cita."
            )
        if resultado == "NO_PERMITIDA":
            raise CambioEstadoDoctorNoPermitido(
                "Solo puedes registrar el resultado de una cita agendada."
            )
        if resultado != "REGISTRADA":
            raise RepositorioDoctorNoDisponible(
                "No se pudo confirmar el registro del resultado."
            )
        return {
            "id_cita": identificador_cita,
            "estado": estado_solicitado,
            "persistido": True,
        }

    @classmethod
    def _validar_estado_resultado(cls, estado: object) -> str:
        estado_solicitado = cls.validar_estado(estado)
        if estado_solicitado not in ESTADOS_RESULTADO:
            raise ErrorValidacionDoctor(
                "El resultado debe ser ATENDIDA o NO_ASISTIO."
            )
        return estado_solicitado

    def _obtener_repositorio(self) -> RepositorioDoctor:
        if self._repositorio is None:
            raise RepositorioDoctorNoDisponible(
                "El almacenamiento del módulo de doctor aún no está configurado."
            )
        return self._repositorio

    @classmethod
    def _validar_cita(cls, registro: object) -> CitaDoctor:
        mensaje = "El proveedor devolvió datos de cita inválidos."
        if not isinstance(registro, CitaDoctor):
            raise RepositorioDoctorNoDisponible(mensaje)
        if (
            type(registro.fecha) is not date
            or not isinstance(registro.hora, time)
            or registro.hora.tzinfo is not None
            or type(registro.duracion_minutos) is not int
            or registro.duracion_minutos <= 0
            or any(
                not isinstance(valor, str) or not valor.strip()
                for valor in (registro.paciente, registro.especialidad, registro.sede)
            )
        ):
            raise RepositorioDoctorNoDisponible(mensaje)
        try:
            return replace(
                registro,
                id_cita=cls.validar_identificador(
                    registro.id_cita, "identificador de la cita"
                ),
                id_doctor=cls.validar_identificador(
                    registro.id_doctor, "identificador del doctor"
                ),
                estado=cls.validar_estado(registro.estado),
            )
        except ErrorValidacionDoctor as error:
            raise RepositorioDoctorNoDisponible(mensaje) from error

    @staticmethod
    def _serializar_cita(cita: CitaDoctor) -> dict:
        datos = asdict(cita)
        datos["fecha"] = cita.fecha.isoformat()
        datos["hora"] = cita.hora.isoformat(timespec="seconds")
        return datos
