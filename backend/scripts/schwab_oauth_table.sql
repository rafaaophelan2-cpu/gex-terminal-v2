-- Correr una sola vez en el SQL Editor de Supabase antes de usar
-- bootstrap_schwab_token.py. Tabla de una sola fila (id=1) que guarda el
-- token OAuth de Schwab en vez de un archivo en disco -- Back4app no tiene
-- filesystem persistente entre deploys/restarts.

create table if not exists schwab_oauth_token (
  id int primary key default 1,
  token_json jsonb not null,
  updated_at timestamptz not null default now(),
  constraint schwab_oauth_token_single_row check (id = 1)
);

alter table schwab_oauth_token enable row level security;

-- Mismo nivel de permisividad que ya usan gex_intraday/chat_messages/etc.
-- con la key anon del backend. Si esas tablas tienen una política más
-- restrictiva en tu proyecto, ajusta esta igual para consistencia.
create policy "allow service read/write schwab_oauth_token"
  on schwab_oauth_token
  for all
  using (true)
  with check (true);
