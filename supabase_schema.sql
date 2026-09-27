-- ============================================================================
-- Schema do Painel Financeiro Youup — rode UMA VEZ no editor SQL do Supabase.
-- (Supabase > SQL Editor > New query > cole tudo > Run)
-- Espelha as tabelas do backend local, para o app funcionar na nuvem.
-- ============================================================================

create table if not exists transactions (
    id                text primary key,
    data              date,
    escopo            text,
    fonte             text,
    descricao         text,
    entrada           numeric default 0,
    saida             numeric default 0,
    tipo              text,
    categoria         text,
    categoria_manual  text,
    obs               text,
    import_ts         timestamptz default now()
);
create index if not exists ix_tx_data   on transactions (data);
create index if not exists ix_tx_escopo on transactions (escopo);

create table if not exists recurring_overrides (
    chave     text primary key,
    label     text,
    categoria text,
    escopo    text,
    valor     numeric default 0,
    dia       integer,
    ativo     boolean default true,
    origem    text
);

create table if not exists settings (
    chave text primary key,
    valor text
);

-- ----------------------------------------------------------------------------
-- Segurança (RLS). O app usa a chave de serviço (service_role), que ignora RLS.
-- Deixamos RLS ligado e SEM políticas públicas: nada é lido/escrito com a chave
-- anônima. Só o backend (service_role) acessa. NÃO exponha a service_role no
-- front-end — ela vive só no servidor (variável de ambiente SUPABASE_KEY).
-- ----------------------------------------------------------------------------
alter table transactions        enable row level security;
alter table recurring_overrides enable row level security;
alter table settings            enable row level security;
