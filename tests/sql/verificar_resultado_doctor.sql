-- Ejecutar dentro de una transacción que terminará con ROLLBACK.
do $pruebas$
declare
    v_hoy date := timezone('America/Lima', statement_timestamp())::date;
    v_sufijo text := replace(gen_random_uuid()::text, '-', '');
    v_dni integer := 10000000 + floor(random() * 70000000)::integer;
    v_id_base bigint := 8000000000000000000 + floor(random() * 1000000000)::bigint;
    v_sede bigint;
    v_especialidad bigint;
    v_doctor bigint;
    v_doctor_ajeno bigint;
    v_usuario bigint;
    v_cliente bigint;
    v_compra bigint;
    v_consulta bigint;
    v_cita bigint;
    v_citas bigint[] := '{}';
    v_inicio timestamptz;
    v_estado text;
    v_firma text := 'public.registrar_resultado_cita_doctor(bigint,bigint,text)';
begin
    if has_function_privilege('anon', v_firma, 'EXECUTE')
       or has_function_privilege('authenticated', v_firma, 'EXECUTE')
       or not has_function_privilege('service_role', v_firma, 'EXECUTE')
       or has_table_privilege('authenticated', 'public.resultado_cita_doctor', 'SELECT')
       or not has_table_privilege('service_role', 'public.resultado_cita_doctor', 'INSERT') then
        raise exception 'Permisos inesperados en la operación de Doctor.';
    end if;

    insert into public.sede (id_sede, nombre, direccion, activa) overriding system value
    values (v_id_base, 'Prueba ' || v_sufijo, 'Dirección ficticia', true) returning id_sede into v_sede;
    insert into public.especialidad (id_especialidad, nombre, duracion_minutos, activa) overriding system value
    values (v_id_base, 'Prueba ' || v_sufijo, 30, true) returning id_especialidad into v_especialidad;

    for v_numero in 0..2 loop
        insert into public.usuario (id_usuario, id_rol, dni, nombres, apellidos, correo, activo)
        overriding system value
        select v_id_base + v_numero, id_rol, (v_dni + v_numero)::text, 'Usuario', 'Sintético',
               v_sufijo || '-' || v_numero || '@example.invalid', true
          from public.rol
         where nombre = case when v_numero = 2 then 'CLIENTE' else 'DOCTOR' end
        returning id_usuario into v_usuario;
        if v_numero = 2 then
            insert into public.cliente (id_cliente, id_usuario) overriding system value
            values (v_id_base, v_usuario)
            returning id_cliente into v_cliente;
        else
            insert into public.doctor (id_doctor, id_usuario, id_especialidad, id_sede)
            overriding system value
            values (v_id_base + v_numero, v_usuario, v_especialidad, v_sede)
            returning id_doctor into v_doctor_ajeno;
            if v_numero = 0 then
                v_doctor := v_doctor_ajeno;
            end if;
        end if;
    end loop;

    insert into public.compra (id_compra, id_cliente, fecha_compra, canal)
    overriding system value
    values (v_id_base, v_cliente, v_hoy - 7, 'WEB') returning id_compra into v_compra;

    for v_numero in 1..6 loop
        insert into public.consulta (
            id_consulta, id_compra, precio, estado_pago, fecha_vencimiento, estado_consulta
        ) overriding system value
        values (v_id_base + v_numero, v_compra, 30, 'PAGADA',
                case when v_numero = 3 then v_hoy - 1 else v_hoy end, 'AGENDADA')
        returning id_consulta into v_consulta;
        v_inicio := now() + make_interval(hours => case when v_numero = 4 then 3 else -v_numero end);
        insert into public.cita (
            id_cita, id_consulta, id_doctor, id_sede, fecha_inicio, fecha_fin, duracion_minutos, estado
        ) overriding system value values (
            v_id_base + v_numero, v_consulta, v_doctor, v_sede, v_inicio, v_inicio + interval '30 minutes', 30,
            case when v_numero = 5 then 'CANCELADA' else 'AGENDADA' end
        ) returning id_cita into v_cita;
        v_citas := array_append(v_citas, v_cita);
    end loop;

    if public.registrar_resultado_cita_doctor(v_doctor_ajeno, v_citas[1], 'ATENDIDA') <> 'NO_ENCONTRADA'
       or public.registrar_resultado_cita_doctor(v_doctor, v_citas[4], 'NO_ASISTIO') <> 'NO_INICIADA'
       or public.registrar_resultado_cita_doctor(v_doctor, v_citas[5], 'ATENDIDA') <> 'NO_PERMITIDA' then
        raise exception 'No se respetó la asignación, el inicio o el estado terminal de la cita.';
    end if;

    for v_numero in 1..3 loop
        v_estado := case when v_numero = 1 then 'ATENDIDA' else 'NO_ASISTIO' end;
        if public.registrar_resultado_cita_doctor(v_doctor, v_citas[v_numero], v_estado) <> 'REGISTRADA'
           or public.registrar_resultado_cita_doctor(v_doctor, v_citas[v_numero], v_estado) <> 'REGISTRADA' then
            raise exception 'No se guardó la cita o el reintento no fue idempotente.';
        end if;
        if not exists (
            select 1 from public.cita c join public.consulta q using (id_consulta)
            join public.resultado_cita_doctor r using (id_cita, id_doctor)
            where c.id_cita = v_citas[v_numero]
              and c.estado = v_estado and c.id_consulta_activa is null and r.estado = v_estado
              and q.estado_consulta = case v_numero
                  when 1 then 'UTILIZADA' when 2 then 'DISPONIBLE' else 'VENCIDA' end
        ) then
            raise exception 'La cita, la consulta y la auditoría no coincidieron.';
        end if;
    end loop;

    if public.registrar_resultado_cita_doctor(v_doctor, v_citas[1], 'NO_ASISTIO') <> 'NO_PERMITIDA'
       or (select count(*) from public.resultado_cita_doctor where id_cita = any(v_citas)) <> 3 then
        raise exception 'Se modificó una cita terminal o se duplicó la auditoría.';
    end if;

    insert into public.resultado_cita_doctor (id_cita, id_doctor, estado)
    values (v_citas[6], v_doctor, 'NO_ASISTIO');
    begin
        perform public.registrar_resultado_cita_doctor(v_doctor, v_citas[6], 'ATENDIDA');
        raise exception 'Se esperaba un conflicto de auditoría.';
    exception when unique_violation then
        if not exists (
            select 1 from public.cita c join public.consulta q using (id_consulta)
            where c.id_cita = v_citas[6] and c.estado = 'AGENDADA' and q.estado_consulta = 'AGENDADA'
        ) then
            raise exception 'El fallo de auditoría dejó una escritura parcial.';
        end if;
    end;
end;
$pruebas$;
