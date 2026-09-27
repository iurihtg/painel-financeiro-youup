# Fase 2 — Entrada por WhatsApp (IA)

> **Status:** o *cérebro* está pronto e testado (`contabil/assistente.py` + o motor
> anti-duplicação `contabil/reconciliar.py`). O que falta é **ligar o WhatsApp**,
> e isso a gente faz junto — porque toca na infra da clínica (Evolution + n8n) e
> precisa de credenciais que **não** passam pelo chat.

O objetivo da Fase 2, além de lançar por voz/foto/texto, é o que você pediu:
**não deixar acontecer dupla contagem** de recebimentos e transferências
(ex.: recebe na maquininha PJ → transfere PJ→PF → paga contas). Isso já está
resolvido no app, na aba **🔁 Duplicações** — o WhatsApp só vai *alimentar* esse
mesmo motor.

---

## O que já funciona hoje (sem WhatsApp)

- **Lançar por frase** — aba ✍️ Lançamentos → "🗣️ Lançar por frase". Escreve
  "gastei 50 no ifood" e o sistema entende tipo, valor, categoria, escopo e data.
  É exatamente o mesmo motor que o WhatsApp vai usar; dá pra testar agora.
- **Anti-duplicação** — aba 🔁 Duplicações. Toda vez que entra dado novo, o
  sistema procura transferências internas e lançamentos repetidos e te mostra
  para confirmar. Nada é apagado/neutralizado sem o seu clique.

---

## Como o WhatsApp vai plugar (arquitetura)

```
Você (WhatsApp)
   │  texto / áudio / foto
   ▼
Evolution API  ──►  n8n (webhook)  ──►  [transcrição / OCR]  ──►  parser
   (já roda no          (já roda no          Whisper p/ áudio,       contabil/
    seu VPS)             seu VPS)            OCR p/ foto de nota)     assistente.py
                                                                        │
                                                                        ▼
                                                               rascunho de lançamento
                                                                        │
                                                       n8n devolve no WhatsApp:
                                                       "Despesa R$50 · iFood · PF — confirmar? (sim/não)"
                                                                        │  sim
                                                                        ▼
                                                       grava no Supabase (mesma
                                                       tabela transactions do painel)
```

Pontos-chave:

1. **Reaproveita a infra que já existe** (Evolution + n8n no VPS). Não sobe nada novo.
2. **Confirmação obrigatória** — nada entra sem você responder "sim". Isso respeita
   a regra do AGENTS.md (não agir sem aprovação) e evita lançamento errado.
3. **Mesmo banco do painel** — o que entra pelo WhatsApp aparece na hora no painel
   e passa pelo mesmo motor anti-duplicação.

---

## O que EU faço (quando você me liberar)

- Escrever o fluxo do n8n (webhook → parser → confirmação → grava no Supabase).
- Expor o parser como um endpoint pequeno (ou rodar o parser dentro de um
  node Function do n8n, sem servidor extra).
- Escrever a lógica de transcrição (áudio) e OCR (foto de nota) chamando o
  serviço que você preferir.

## O que só VOCÊ faz (segurança)

- Me autorizar a mexer no n8n da clínica (é produção — não toco sem seu ok).
- Cadastrar as credenciais **no lugar certo** (variáveis do n8n / Streamlit
  Secrets), **nunca no chat**:
  - URL + API key da Evolution API
  - Chave do serviço de transcrição/OCR (se for usar voz/foto)
  - A `SUPABASE_KEY` (service_role) do projeto financeiro — a mesma que já está
    nos Secrets do painel.
- Decidir o número/instância do WhatsApp que a IA vai escutar (recomendo um
  número/instância só seu, com allowlist, como já é a política do Jarvis).

---

## Decisões pendentes (a gente resolve quando retomar)

1. **Só texto no começo, ou já com voz/foto?** Sugiro começar por texto (mais
   simples e 100% confiável) e ligar voz/foto na sequência.
2. **Confirmar cada lançamento, ou só os "duvidosos"?** Sugiro confirmar tudo no
   início; depois relaxamos para auto-confirmar os de confiança alta.
3. **Alertas proativos** (ex.: "gasto de X está 40% acima da média") — dá pra
   fazer o Jarvis te cutucar no WhatsApp. Fase 2.1.

---

_Resumo: a parte inteligente e arriscada (entender a frase + não duplicar) já
está pronta e rodando no painel. Ligar o WhatsApp é integração de infra — rápida,
mas precisa das suas credenciais e do seu ok para mexer no n8n da clínica._
