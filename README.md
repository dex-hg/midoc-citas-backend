# MiDoc Backend

Backend del sistema MiDoc desarrollado con Python y Flask.

## Tecnologías

- Python
- Flask
- Flask-CORS
- python-dotenv
- Supabase SDK
- PostgreSQL (Supabase)

## Arquitectura

El backend se organiza por responsabilidades:

- `routes/`: endpoints HTTP de la API.
- `services/`: lógica de negocio.
- `repositories/`: acceso a la base de datos.
- `config/`: configuración y conexión con servicios externos.
- `tests/`: pruebas del backend.

Flujo general:

Frontend React
→ API Flask
→ Services
→ Repositories
→ Supabase
→ PostgreSQL

## Estado actual

### Completado

- Estructura inicial del backend.
- Aplicación Flask mediante Application Factory.
- Configuración de CORS.
- Endpoint general `/api/health`.
- Blueprints para:
  - Auth
  - Cliente
  - Doctor
  - Recepción
  - Promotor BCP
  - Administrador
- Endpoints iniciales de autenticación y registro.
- `AuthService` con validaciones iniciales.
- Validación de DNI.
- Validación de correo.
- Validación básica de contraseña.
- Definición de perfiles disponibles según el rol de la cuenta.
- Variables de entorno protegidas mediante `.gitignore`.
- Módulo de doctor con perfil, agenda y citas en Supabase. Postgres registra
  el resultado de la atención y su auditoría en una transacción.

## Pendiente

### 1. Configuración de Supabase

Copiar `.env.example` a `.env` y configurar `SUPABASE_URL` y
`SUPABASE_KEY`. Para Doctor, usar una clave secreta del servidor o la clave
legada `service_role`. Mantenerla en el backend. Configurar `FRONTEND_URL` con
el origen exacto desde el que React envía la sesión.

### 2. Repositories

Implementar acceso real a Supabase comenzando por:

`app/repositories/usuario_repository.py`

Operaciones iniciales sugeridas:

- buscar usuario por DNI
- buscar usuario por correo
- obtener usuario por ID
- comprobar DNI existente
- comprobar correo existente
- registrar usuario

Posteriormente implementar:

- `consulta_repository.py`
- `cita_repository.py`
- `doctor_repository.py` ya implementa el acceso de Doctor.

### 3. Auth

Conectar `AuthService` con `UsuarioRepository` y Supabase Auth.

Completar:

- login real
- validación de existencia del DNI
- envío de código al correo
- verificación del código
- creación de cuenta

No crear usuarios falsos o lógica hardcodeada para simular la base de datos.

### 4. Servicios por rol

Implementar progresivamente:

- Cliente
- Doctor
- Recepción
- Promotor BCP
- Administrador

Mantener la separación:

Route → Service → Repository → Supabase

La lógica de negocio NO debe colocarse directamente en las rutas.

## Base de datos

La base de datos ya se encuentra creada en Supabase/PostgreSQL.

Actualmente contempla las entidades principales del sistema, incluyendo usuarios, roles, clientes, doctores, sedes, especialidades, horarios, compras, consultas, citas, reprogramaciones y notificaciones.

No se utiliza actualmente un ORM como SQLAlchemy. El acceso a los datos se realizará mediante el SDK de Supabase desde los repositories.

Antes de modificar la estructura de la base de datos, coordinar los cambios necesarios para mantener compatibilidad con los flujos definidos en el sistema.

## Módulo Doctor

El módulo recupera perfil, agenda y citas desde Supabase. La ruta valida la
sesión y el rol, el servicio aplica las reglas de atención y el repositorio
traduce las relaciones de PostgreSQL al contrato HTTP.

| Método | Ruta | Resultado |
| --- | --- | --- |
| GET | /api/doctores/health | Estado del módulo. |
| GET | /api/doctores/perfil | Identificador, nombre, especialidad y sede del doctor autenticado. |
| GET | /api/doctores/agenda | Citas del día de Lima. Acepta los filtros fecha y estado. |
| GET | /api/doctores/citas | Citas asignadas al doctor. Acepta los filtros fecha y estado. |
| PATCH | /api/doctores/citas/<id_cita>/estado | Registra el resultado y devuelve el estado guardado. |
| POST | /api/doctores/citas/<id_cita>/preparar-estado | Valida el cambio, con persistido=false. |

Las lecturas usan fecha con formato AAAA-MM-DD y hora HH:MM:SS de Lima.
La agenda busca el día actual si se omite la fecha. Los estados admitidos
son AGENDADA, ATENDIDA, CANCELADA y NO_ASISTIO. Las respuestas incluyen
Cache-Control: no-store.

### Sesión

El módulo acepta el contexto `g.usuario_autenticado` que establezca el
middleware compartido. Debe incluir `rol: "DOCTOR"`, `activo: true` y un
`id_usuario` de MiDoc o un `id_doctor` ya verificado. Si se usa un token de
acceso en `Authorization: Bearer`, Flask lo verifica en Supabase Auth, busca
la cuenta por `usuario.auth_user_id` y obtiene el doctor por
`doctor.id_usuario`. El rol y la activación se toman de MiDoc.
React envía las credenciales de la sesión al origen configurado para Flask.
El ingreso desde la interfaz requiere la autenticación compartida y una
cuenta activa vinculada con Supabase Auth.

### Registrar el resultado

El PATCH recibe un objeto JSON con el campo `estado` y el valor
`ATENDIDA` o `NO_ASISTIO`. Se permite desde el inicio programado de una
cita `AGENDADA` asignada al doctor autenticado. Al registrar atención, la
consulta queda `UTILIZADA`. Al registrar inasistencia, queda `DISPONIBLE`
si su vigencia incluye el día local de Lima y `VENCIDA` si expiró.

PostgreSQL bloquea la consulta y la cita antes de actualizar ambas y de
insertar la auditoría en `resultado_cita_doctor`. El reintento con el mismo
resultado devuelve éxito si coincide con el registro de auditoría. Una cita
ajena o inexistente responde 404. Una cita futura, cancelada o con otro
resultado responde 409. Los fallos de almacenamiento responden 503.

La función `registrar_resultado_cita_doctor` y la tabla de auditoría están
en `supabase/migrations/20261122190357_registrar_resultado_cita_doctor.sql`.
Aplicar el archivo completo en una transacción. La función solo se
concede al rol `service_role` y la tabla tiene RLS.

### Pruebas de Doctor

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

La prueba `tests/sql/verificar_resultado_doctor.sql` cubre las transiciones,
los permisos, la protección entre doctores, el reintento y la reversión
ante un fallo de auditoría. Ejecutarla en una transacción que termine con
`ROLLBACK`. Para comprobar una migración pendiente, incluir el SQL de la
migración antes de la prueba, dentro de la misma transacción.

## Ejecutar proyecto

Activar el entorno virtual:

`.venv\Scripts\Activate.ps1`

Ejecutar:

`python run.py`

El backend se ejecutará por defecto en el puerto `5000`.

## Importante

Mantener la arquitectura definida y evitar:

- lógica de negocio directamente en `routes`
- credenciales dentro del código
- datos falsos como solución definitiva
- consultas a Supabase desde las vistas/rutas
- subir `.env`
