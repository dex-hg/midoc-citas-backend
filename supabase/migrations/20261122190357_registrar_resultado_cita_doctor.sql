create table if not exists public.resultado_cita_doctor (
    id_cita bigint primary key references public.cita (id_cita),
    id_doctor bigint not null references public.doctor (id_doctor),
    estado varchar not null check (estado in ('ATENDIDA', 'NO_ASISTIO')),
    fecha_registro timestamptz not null default pg_catalog.now()
);

alter table public.resultado_cita_doctor enable row level security;
revoke all on table public.resultado_cita_doctor from public, anon, authenticated;
grant select, insert on table public.resultado_cita_doctor to service_role;

create or replace function public.registrar_resultado_cita_doctor(
    p_id_doctor bigint,
    p_id_cita bigint,
    p_estado text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $funcion$
declare
    v_id_consulta bigint;
    v_estado_consulta text;
    v_vencimiento date;
    v_estado_cita text;
    v_inicio timestamptz;
    v_instante timestamptz := pg_catalog.statement_timestamp();
begin
    if p_estado is null or p_estado not in ('ATENDIDA', 'NO_ASISTIO') then
        return 'NO_PERMITIDA';
    end if;

    select c.id_consulta
      into v_id_consulta
      from public.cita as c
     where c.id_cita = p_id_cita and c.id_doctor = p_id_doctor;

    if not found then
        return 'NO_ENCONTRADA';
    end if;

    -- Adquirir los bloqueos en el orden consulta, cita.
    select q.estado_consulta, q.fecha_vencimiento
      into v_estado_consulta, v_vencimiento
      from public.consulta as q
     where q.id_consulta = v_id_consulta
       for update;

    if not found then
        return 'NO_PERMITIDA';
    end if;

    select c.estado, c.fecha_inicio
      into v_estado_cita, v_inicio
      from public.cita as c
     where c.id_cita = p_id_cita
       and c.id_doctor = p_id_doctor
       and c.id_consulta = v_id_consulta
       for update;

    if not found then
        return 'NO_ENCONTRADA';
    end if;

    if v_estado_cita = p_estado and exists (
        select 1
          from public.resultado_cita_doctor as r
         where r.id_cita = p_id_cita and r.id_doctor = p_id_doctor and r.estado = p_estado
    ) then
        return 'REGISTRADA';
    end if;

    if v_estado_cita <> 'AGENDADA' or v_estado_consulta = 'UTILIZADA' then
        return 'NO_PERMITIDA';
    end if;

    if v_inicio > v_instante then
        return 'NO_INICIADA';
    end if;

    update public.cita set estado = p_estado where id_cita = p_id_cita;

    update public.consulta
       set estado_consulta = case
           when p_estado = 'ATENDIDA' then 'UTILIZADA'
           when v_vencimiento >= pg_catalog.timezone('America/Lima', v_instante)::date
               then 'DISPONIBLE'
           else 'VENCIDA'
       end
     where id_consulta = v_id_consulta;

    insert into public.resultado_cita_doctor (id_cita, id_doctor, estado)
    values (p_id_cita, p_id_doctor, p_estado);

    return 'REGISTRADA';
end;
$funcion$;

revoke all on function public.registrar_resultado_cita_doctor(bigint, bigint, text)
    from public, anon, authenticated;
grant execute on function public.registrar_resultado_cita_doctor(bigint, bigint, text)
    to service_role;
