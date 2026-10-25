-- NildãoFut — ranking de palpites com grupos e comentários
--
-- Como usar: Supabase > SQL Editor > New query > cole TUDO isto > Run.
-- Pode rodar de novo sem medo: o arquivo só cria o que ainda não existe e atualiza as funções.
--
-- Como a segurança funciona:
--  * Ninguém mexe nas tabelas direto. Tudo passa pelas funções abaixo, que conferem quem é o usuário
--    (auth.uid()), se ele é membro do grupo, se é o dono, e se o jogo ainda não começou.
--  * Quem não entrou (só com a chave pública) não consegue nada.
--  * O robô do GitHub usa a chave service_role, que ignora essas travas, só para gravar jogos e placares.

-- ============================================================ TABELAS

create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  nickname    text not null check (char_length(nickname) between 3 and 16 and nickname = btrim(nickname)),
  created_at  timestamptz not null default now()
);
-- apelido único no app inteiro, sem diferenciar maiúscula de minúscula
create unique index if not exists profiles_nickname_key on public.profiles (lower(nickname));

-- Jogos: quem grava é o robô (update.py + sync_supabase.py). A chave é "data|mandante|visitante".
create table if not exists public.games (
  key         text primary key,
  champ       text not null,
  home        text not null,
  away        text not null,
  kickoff     timestamptz not null,
  home_goals  int check (home_goals >= 0),
  away_goals  int check (away_goals >= 0),
  active      boolean not null default true,
  updated_at  timestamptz not null default now()
);
create index if not exists games_kickoff_idx on public.games (kickoff);

create table if not exists public.predictions (
  user_id     uuid not null references public.profiles (id) on delete cascade,
  game_key    text not null references public.games (key) on delete cascade,
  home_goals  int not null check (home_goals between 0 and 20),
  away_goals  int not null check (away_goals between 0 and 20),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, game_key)
);
create index if not exists predictions_game_idx on public.predictions (game_key);

create table if not exists public.groups (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (char_length(name) between 2 and 30 and name = btrim(name)),
  code        text not null unique check (code ~ '^[A-Z]{6}$'),
  owner_id    uuid not null references public.profiles (id) on delete cascade,
  created_at  timestamptz not null default now()
);
create index if not exists groups_owner_idx on public.groups (owner_id);

create table if not exists public.group_members (
  group_id    uuid not null references public.groups (id) on delete cascade,
  user_id     uuid not null references public.profiles (id) on delete cascade,
  joined_at   timestamptz not null default now(),
  primary key (group_id, user_id)
);
create index if not exists group_members_user_idx on public.group_members (user_id);

-- quem foi removido pelo dono não volta só digitando o código de novo
create table if not exists public.group_removed (
  group_id    uuid not null references public.groups (id) on delete cascade,
  user_id     uuid not null references public.profiles (id) on delete cascade,
  primary key (group_id, user_id)
);

create table if not exists public.comments (
  id          bigint generated always as identity primary key,
  group_id    uuid not null references public.groups (id) on delete cascade,
  user_id     uuid not null references public.profiles (id) on delete cascade,
  body        text not null check (char_length(body) between 1 and 300),
  created_at  timestamptz not null default now()
);
create index if not exists comments_group_idx on public.comments (group_id, id desc);

-- ============================================================ SEGURANÇA DAS TABELAS

alter table public.profiles      enable row level security;
alter table public.games         enable row level security;
alter table public.predictions   enable row level security;
alter table public.groups        enable row level security;
alter table public.group_members enable row level security;
alter table public.group_removed enable row level security;
alter table public.comments      enable row level security;

drop policy if exists profiles_select_own    on public.profiles;
drop policy if exists games_select           on public.games;
drop policy if exists predictions_select_own on public.predictions;

create policy profiles_select_own    on public.profiles    for select to authenticated using (id = auth.uid());
create policy games_select           on public.games       for select to authenticated using (active);
create policy predictions_select_own on public.predictions for select to authenticated using (user_id = auth.uid());
-- (grupos, membros e comentários: nenhuma política = ninguém lê nem grava direto; só pelas funções)

grant usage on schema public to anon, authenticated, service_role;
revoke all on all tables in schema public from anon, authenticated;
grant select on public.profiles, public.games, public.predictions to authenticated;
grant all on all tables in schema public to service_role;

-- ============================================================ FUNÇÕES INTERNAS

-- 5 pontos pelo placar exato, 3 por acertar quem ganha (ou o empate), 0 se errar. Sem resultado: null.
create or replace function public.points_of(ph int, pa int, gh int, ga int)
returns int language sql immutable as $$
  select case
    when gh is null or ga is null then null
    when ph = gh and pa = ga then 5
    when sign((ph - pa)::numeric) = sign((gh - ga)::numeric) then 3
    else 0
  end
$$;

-- usuário logado e com apelido
create or replace function public._uid()
returns uuid language plpgsql stable security definer set search_path = public as $$
declare v uuid := auth.uid();
begin
  if v is null then raise exception 'nao_logado'; end if;
  if not exists (select 1 from public.profiles where id = v) then raise exception 'sem_apelido'; end if;
  return v;
end $$;

-- código de 6 letras (sem I e O, para não confundir com 1 e 0)
create or replace function public._random_code()
returns text language plpgsql volatile as $$
declare
  letters text := 'ABCDEFGHJKLMNPQRSTUVWXYZ';
  r text := '';
  i int;
begin
  for i in 1..6 loop
    r := r || substr(letters, 1 + floor(random() * length(letters))::int, 1);
  end loop;
  return r;
end $$;

-- classificação de um grupo: pontos, depois mais placares exatos; empate total divide a posição
create or replace function public._standings(p_group uuid)
returns table (uid uuid, nick text, pts int, exatos int, acertos int, pos int)
language sql stable security definer set search_path = public as $$
  with s as (
    select m.user_id as uid,
           pr.nickname as nick,
           coalesce(sum(public.points_of(x.home_goals, x.away_goals, g.home_goals, g.away_goals)), 0)::int as pts,
           (count(*) filter (where public.points_of(x.home_goals, x.away_goals, g.home_goals, g.away_goals) = 5))::int as exatos,
           (count(*) filter (where public.points_of(x.home_goals, x.away_goals, g.home_goals, g.away_goals) >= 3))::int as acertos
    from public.group_members m
    join public.profiles pr on pr.id = m.user_id
    left join public.predictions x on x.user_id = m.user_id
    left join public.games g on g.key = x.game_key
    where m.group_id = p_group
    group by m.user_id, pr.nickname
  )
  select s.uid, s.nick, s.pts, s.exatos, s.acertos,
         (rank() over (order by s.pts desc, s.exatos desc))::int as pos
  from s
$$;

-- ============================================================ FUNÇÕES DO APP

-- Primeiro acesso: apelido único (também serve para trocar de apelido depois)
create or replace function public.set_nickname(p_nick text)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v text := btrim(coalesce(p_nick, ''));
begin
  if v_uid is null then raise exception 'nao_logado'; end if;
  if char_length(v) < 3 or char_length(v) > 16 then raise exception 'apelido_tamanho'; end if;
  if v ~ '[<>&"'']' or v ~ '[[:cntrl:]]' then raise exception 'apelido_invalido'; end if;
  insert into public.profiles (id, nickname) values (v_uid, v)
    on conflict (id) do update set nickname = excluded.nickname;
  return v;
exception when unique_violation then
  raise exception 'apelido_em_uso';
end $$;

create or replace function public.create_group(p_name text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := public._uid();
  v_name text := btrim(coalesce(p_name, ''));
  v_code text;
  v_id uuid;
  i int := 0;
begin
  if char_length(v_name) < 2 or char_length(v_name) > 30 then raise exception 'grupo_nome'; end if;
  if (select count(*) from public.groups where owner_id = v_uid) >= 10 then raise exception 'limite_grupos'; end if;
  loop
    v_code := public._random_code();
    begin
      insert into public.groups (name, code, owner_id) values (v_name, v_code, v_uid) returning id into v_id;
      exit;
    exception when unique_violation then
      i := i + 1;
      if i > 20 then raise exception 'tente_de_novo'; end if;
    end;
  end loop;
  insert into public.group_members (group_id, user_id) values (v_id, v_uid);
  return jsonb_build_object('id', v_id, 'name', v_name, 'code', v_code);
end $$;

create or replace function public.join_group(p_code text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := public._uid();
  v_code text := upper(btrim(coalesce(p_code, '')));
  g public.groups%rowtype;
begin
  select * into g from public.groups where code = v_code;
  if not found then raise exception 'codigo_invalido'; end if;
  if exists (select 1 from public.group_removed where group_id = g.id and user_id = v_uid) then
    raise exception 'removido';
  end if;
  if not exists (select 1 from public.group_members where group_id = g.id and user_id = v_uid)
     and (select count(*) from public.group_members where group_id = g.id) >= 100 then
    raise exception 'grupo_cheio';
  end if;
  insert into public.group_members (group_id, user_id) values (g.id, v_uid) on conflict do nothing;
  return jsonb_build_object('id', g.id, 'name', g.name, 'code', g.code);
end $$;

create or replace function public.leave_group(p_group uuid)
returns void language plpgsql security definer set search_path = public as $$
declare v_uid uuid := public._uid();
begin
  if exists (select 1 from public.groups where id = p_group and owner_id = v_uid) then
    raise exception 'dono_nao_sai';
  end if;
  delete from public.group_members where group_id = p_group and user_id = v_uid;
end $$;

create or replace function public.delete_group(p_group uuid)
returns void language plpgsql security definer set search_path = public as $$
declare v_uid uuid := public._uid();
begin
  if not exists (select 1 from public.groups where id = p_group and owner_id = v_uid) then
    raise exception 'sem_permissao';
  end if;
  delete from public.groups where id = p_group;
end $$;

-- só o dono remove participantes
create or replace function public.remove_member(p_group uuid, p_user uuid)
returns void language plpgsql security definer set search_path = public as $$
declare v_uid uuid := public._uid();
begin
  if not exists (select 1 from public.groups where id = p_group and owner_id = v_uid) then
    raise exception 'sem_permissao';
  end if;
  if p_user = v_uid then raise exception 'dono_nao_sai'; end if;
  delete from public.group_members where group_id = p_group and user_id = p_user;
  insert into public.group_removed (group_id, user_id) values (p_group, p_user) on conflict do nothing;
end $$;

create or replace function public.my_groups()
returns table (id uuid, name text, code text, is_owner boolean, members int, pos int, pts int)
language sql stable security definer set search_path = public as $$
  select g.id, g.name, g.code, (g.owner_id = auth.uid()),
         (select count(*) from public.group_members x where x.group_id = g.id)::int,
         s.pos, s.pts
  from public.group_members gm
  join public.groups g on g.id = gm.group_id
  left join lateral (
    select st.pos, st.pts from public._standings(g.id) st where st.uid = auth.uid()
  ) s on true
  where gm.user_id = auth.uid()
  order by gm.joined_at
$$;

create or replace function public.group_ranking(p_group uuid)
returns table (pos int, uid uuid, nick text, pts int, exatos int, acertos int, is_owner boolean, is_me boolean)
language plpgsql stable security definer set search_path = public as $$
declare v_uid uuid := public._uid();
begin
  if not exists (select 1 from public.group_members where group_id = p_group and user_id = v_uid) then
    raise exception 'nao_e_membro';
  end if;
  return query
    select s.pos, s.uid, s.nick, s.pts, s.exatos, s.acertos, (g.owner_id = s.uid), (s.uid = v_uid)
    from public._standings(p_group) s
    join public.groups g on g.id = p_group
    order by s.pos, lower(s.nick);
end $$;

create or replace function public.group_comments(p_group uuid, p_limit int default 100)
returns table (id bigint, uid uuid, nick text, body text, created_at timestamptz, is_owner boolean, is_me boolean)
language plpgsql stable security definer set search_path = public as $$
declare v_uid uuid := public._uid();
begin
  if not exists (select 1 from public.group_members where group_id = p_group and user_id = v_uid) then
    raise exception 'nao_e_membro';
  end if;
  return query
    select c.id, c.user_id, p.nickname, c.body, c.created_at, (g.owner_id = c.user_id), (c.user_id = v_uid)
    from public.comments c
    join public.profiles p on p.id = c.user_id
    join public.groups g on g.id = c.group_id
    where c.group_id = p_group
    order by c.id desc
    limit least(greatest(coalesce(p_limit, 100), 1), 200);
end $$;

create or replace function public.post_comment(p_group uuid, p_body text)
returns bigint language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := public._uid();
  v text := btrim(coalesce(p_body, ''));
  v_id bigint;
begin
  if not exists (select 1 from public.group_members where group_id = p_group and user_id = v_uid) then
    raise exception 'nao_e_membro';
  end if;
  if char_length(v) < 1 or char_length(v) > 300 then raise exception 'comentario_tamanho'; end if;
  if (select count(*) from public.comments where user_id = v_uid and created_at > now() - interval '1 minute') >= 20 then
    raise exception 'muito_rapido';
  end if;
  insert into public.comments (group_id, user_id, body) values (p_group, v_uid, v) returning id into v_id;
  return v_id;
end $$;

-- apaga quem escreveu ou o dono do grupo
create or replace function public.delete_comment(p_comment bigint)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := public._uid();
  c public.comments%rowtype;
begin
  select * into c from public.comments where id = p_comment;
  if not found then return; end if;
  if c.user_id <> v_uid
     and not exists (select 1 from public.groups where id = c.group_id and owner_id = v_uid) then
    raise exception 'sem_permissao';
  end if;
  delete from public.comments where id = p_comment;
end $$;

-- Palpite: vale para todos os grupos. Fecha na hora do jogo; depois disso não muda mais.
create or replace function public.save_prediction(p_game text, p_home int, p_away int)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := public._uid();
  g public.games%rowtype;
begin
  if p_home is null or p_away is null or p_home not between 0 and 20 or p_away not between 0 and 20 then
    raise exception 'placar_invalido';
  end if;
  select * into g from public.games where key = p_game;
  if not found or not g.active then raise exception 'jogo_nao_encontrado'; end if;
  if now() >= g.kickoff then raise exception 'jogo_fechado'; end if;
  insert into public.predictions (user_id, game_key, home_goals, away_goals)
    values (v_uid, p_game, p_home, p_away)
    on conflict (user_id, game_key)
    do update set home_goals = excluded.home_goals, away_goals = excluded.away_goals, updated_at = now();
  return jsonb_build_object('key', p_game, 'h', p_home, 'a', p_away);
end $$;

create or replace function public.my_predictions()
returns table (game_key text, champ text, home text, away text, kickoff timestamptz,
               my_h int, my_a int, res_h int, res_a int, pts int)
language sql stable security definer set search_path = public as $$
  select x.game_key, g.champ, g.home, g.away, g.kickoff,
         x.home_goals, x.away_goals, g.home_goals, g.away_goals,
         public.points_of(x.home_goals, x.away_goals, g.home_goals, g.away_goals)
  from public.predictions x
  join public.games g on g.key = x.game_key
  where x.user_id = auth.uid()
    and (g.active or g.home_goals is not null)
  order by g.kickoff desc
  limit 300
$$;

-- ============================================================ PERMISSÕES DAS FUNÇÕES

revoke all on all functions in schema public from public, anon, authenticated;
grant execute on function
  public.set_nickname(text),
  public.create_group(text),
  public.join_group(text),
  public.leave_group(uuid),
  public.delete_group(uuid),
  public.remove_member(uuid, uuid),
  public.my_groups(),
  public.group_ranking(uuid),
  public.group_comments(uuid, int),
  public.post_comment(uuid, text),
  public.delete_comment(bigint),
  public.save_prediction(text, int, int),
  public.my_predictions()
to authenticated;
