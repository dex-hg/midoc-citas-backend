"""Contrato HTTP de Flask con el SDK de Supabase usando respuestas sintéticas."""

import json
import unittest

import httpx
from supabase import ClientOptions, create_client

from app import create_app
from app.repositories.doctor_repository import RepositorioDoctorSupabase
from app.services.doctor_service import ServicioDoctor


class PruebasDoctorSupabase(unittest.TestCase):
    def setUp(self):
        self.solicitudes = []
        self.activo = True
        self.rol = "DOCTOR"
        self.token_valido = True
        self.usuario_vinculado = True
        self.resultado_supabase = "REGISTRADA"

        transporte = httpx.MockTransport(self.responder_supabase)
        cliente_http = httpx.Client(transport=transporte)
        self.addCleanup(cliente_http.close)
        supabase = create_client(
            "https://midoc.example.invalid",
            "clave-sintetica",
            ClientOptions(
                httpx_client=cliente_http,
                auto_refresh_token=False,
                persist_session=False,
            ),
        )
        aplicacion = create_app()
        aplicacion.config["TESTING"] = True
        aplicacion.extensions["servicio_doctor"] = ServicioDoctor(
            RepositorioDoctorSupabase(lambda: supabase)
        )
        self.cliente = aplicacion.test_client()
        self.cabeceras = {"Authorization": "Bearer cabecera.contenido.firma"}

    def responder_supabase(self, solicitud):
        ruta = solicitud.url.path
        self.solicitudes.append(solicitud)
        if ruta == "/auth/v1/user":
            if not self.token_valido:
                return httpx.Response(401, json={"message": "JWT expirado"})
            return httpx.Response(200, json={
                "id": "3b23b540-5578-404e-8619-bf733e2b6e2e",
                "aud": "authenticated",
                "app_metadata": {"rol": "CLIENTE"},
                "user_metadata": {"rol": "ADMINISTRADOR"},
                "created_at": "2026-01-01T00:00:00Z",
            })
        if ruta == "/rest/v1/usuario":
            cuentas = [{
                "id_usuario": 21,
                "activo": self.activo,
                "rol": {"nombre": self.rol},
            }]
            return httpx.Response(200, json=cuentas if self.usuario_vinculado else [])
        if ruta == "/rest/v1/doctor":
            return httpx.Response(200, json=[{
                "id_usuario": 21,
                "id_doctor": 42,
                "usuario": {"nombres": "Médico", "apellidos": "Sintético"},
                "especialidad": {"nombre": "Especialidad de prueba"},
                "sede": {"nombre": "Sede de prueba"},
            }])
        if ruta == "/rest/v1/cita":
            return httpx.Response(200, json=[{
                "id_cita": 31,
                "id_doctor": 42,
                "fecha_inicio": "2026-11-23T01:30:00+00:00",
                "duracion_minutos": 30,
                "estado": "AGENDADA",
                "doctor": {"especialidad": {"nombre": "Especialidad de prueba"}},
                "sede": {"nombre": "Sede de prueba"},
                "consulta": {"compra": {"cliente": {
                    "usuario": {"nombres": "Paciente", "apellidos": "Sintético"}
                }}},
            }])
        if ruta == "/rest/v1/rpc/registrar_resultado_cita_doctor":
            return httpx.Response(200, json=self.resultado_supabase)
        self.fail(f"Ruta inesperada del SDK: {ruta}")

    def test_agenda_usa_doctor_validado_y_dia_de_lima(self):
        respuesta = self.cliente.get(
            "/api/doctores/agenda?fecha=2026-11-22&estado=AGENDADA",
            headers=self.cabeceras,
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.json)
        self.assertEqual(respuesta.headers["Cache-Control"], "no-store")
        self.assertEqual(respuesta.json["id_doctor"], "42")
        cita = respuesta.json["citas"][0]
        self.assertEqual((cita["fecha"], cita["hora"]), ("2026-11-22", "20:30:00"))
        self.assertEqual(cita["paciente"], "Paciente Sintético")
        parametros = self.solicitudes[-1].url.params
        self.assertEqual(parametros["id_doctor"], "eq.42")
        self.assertEqual(parametros["estado"], "eq.AGENDADA")
        self.assertEqual(parametros.get_list("fecha_inicio"), [
            "gte.2026-11-22T00:00:00-05:00",
            "lte.2026-11-22T23:59:59.999999-05:00",
        ])

    def test_perfil_se_resuelve_por_auth_y_no_expone_id_usuario(self):
        respuesta = self.cliente.get("/api/doctores/perfil", headers=self.cabeceras)
        self.assertEqual(respuesta.status_code, 200, respuesta.json)
        self.assertEqual(respuesta.json["nombre"], "Médico Sintético")
        self.assertNotIn("id_usuario", respuesta.json)
        self.assertEqual(self.solicitudes[2].url.params["id_usuario"], "eq.21")

    def test_registrar_llama_rpc_con_la_identidad_del_servidor(self):
        respuesta = self.cliente.patch(
            "/api/doctores/citas/31/estado",
            json={"estado": "ATENDIDA"},
            headers=self.cabeceras,
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.json)
        self.assertEqual(respuesta.json, {
            "id_cita": "31", "estado": "ATENDIDA", "persistido": True,
        })
        solicitud = self.solicitudes[-1]
        self.assertEqual(json.loads(solicitud.content), {
            "p_id_cita": 31, "p_id_doctor": 42, "p_estado": "ATENDIDA",
        })
        self.assertNotEqual(solicitud.headers["Authorization"], self.cabeceras["Authorization"])

    def test_rechazar_cuenta_inactiva_ajena_o_sin_vinculo(self):
        for activo, rol, vinculada in [
            (False, "DOCTOR", True),
            (True, "CLIENTE", True),
            (True, "DOCTOR", False),
        ]:
            with self.subTest(activo=activo, rol=rol, vinculada=vinculada):
                self.solicitudes.clear()
                self.activo, self.rol, self.usuario_vinculado = activo, rol, vinculada
                respuesta = self.cliente.get("/api/doctores/agenda", headers=self.cabeceras)
                self.assertEqual(respuesta.status_code, 403)
                self.assertEqual(len(self.solicitudes), 2)

    def test_token_expirado_y_sesion_ausente_reciben_401(self):
        self.token_valido = False
        self.assertEqual(self.cliente.get("/api/doctores/perfil").status_code, 401)
        respuesta = self.cliente.get("/api/doctores/perfil", headers=self.cabeceras)
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(len(self.solicitudes), 1)

    def test_resultado_ajeno_conflicto_o_indeterminado(self):
        casos = [
            ("NO_ENCONTRADA", 404),
            ("NO_INICIADA", 409),
            ("NO_PERMITIDA", 409),
            ("DESCONOCIDA", 503),
        ]
        for resultado, esperado in casos:
            with self.subTest(resultado=resultado):
                self.resultado_supabase = resultado
                respuesta = self.cliente.patch(
                    "/api/doctores/citas/31/estado",
                    json={"estado": "NO_ASISTIO"},
                    headers=self.cabeceras,
                )
                self.assertEqual(respuesta.status_code, esperado)
                self.assertNotIn("persistido", respuesta.json)
