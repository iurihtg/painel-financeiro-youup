-- ============================================================================
-- Schema COMPLETO do Painel Financeiro Youup.
-- Rode UMA VEZ no editor SQL do Supabase (Supabase > SQL Editor > New query >
-- cole tudo > Run). Pode rodar de novo sem medo: é idempotente (não apaga dados,
-- só cria o que falta). Serve tanto para começar do zero quanto para atualizar
-- um banco que já existe (adiciona as colunas novas).
-- ============================================================================

-- ─────────────────────────── transações (lançamentos) ───────────────────────
create table if not exists transactions (
    id                text primary key,
    data              date,               -- data do evento
    data_pgto         date,               -- data de pagamento / efetivação
    status            text,               -- 'Concluído' ou 'Pendente'
    escopo            text,               -- PF / PJ (inferido da conta)
    fonte             text,               -- conta / cartão de origem
    descricao         text,
    entrada           numeric default 0,
    saida             numeric default 0,
    tipo              text,               -- Receita / Despesa (pela categoria)
    categoria         text,
    categoria_manual  text,
    obs               text,
    import_ts         timestamptz default now()
);
-- adiciona as colunas novas se a tabela já existia (não apaga nada)
alter table transactions add column if not exists data_pgto date;
alter table transactions add column if not exists status    text;
create index if not exists ix_tx_data   on transactions (data);
create index if not exists ix_tx_escopo on transactions (escopo);

-- ─────────────────────── recorrentes (overrides de previsão) ─────────────────
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

-- ─────────────────────── configurações (chave/valor em JSON) ─────────────────
-- Guarda: orcamento (tetos por categoria), cat_grupo (categoria→grupo),
-- categorias_extra, contas (a pagar/receber), contas_reg (contas/cartões),
-- investimentos, meta_patrimonio, planos, dedup_resolvidos.
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
