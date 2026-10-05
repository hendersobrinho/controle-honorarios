# Especificação — Financeiro Métodos 1.0.0

Consolidação do que foi acordado, do que a planilha antiga fazia e do que o
sistema faz no lugar dela.

| | |
|---|---|
| **Programa** | Financeiro Métodos |
| **Versão** | 1.0.0 (outubro de 2026) |
| **Plataforma** | Windows (instalador Inno Setup); roda também do código em Linux |
| **Tecnologia** | Python 3.12, PySide6 (Qt 6), SQLAlchemy 2, Alembic |
| **Banco** | PostgreSQL num computador da rede do escritório, compartilhado por todos; SQLite só no desenvolvimento e nos testes |

## 1. O que a planilha tinha (levantamento de 29/09/2026)

Arquivo `01. Controle de Honorários em Abertos com Juros Atualizados 1.xlsx`.

| Aba | Conteúdo |
|---|---|
| `Controle Financeiro` | Base: cabeçalho na linha 2, dados nas linhas 3–213 → **211 lançamentos**, 181 clientes, 183 códigos. 178 `Pago`, 33 `Em aberto` |
| `Controle de IRPF` | 49 linhas, 48 pagas, competência `IRPF 2026`. Cruza com a base só por CPF/CNPJ (1 coincidência), nunca por código |
| `Recall Inadimplentes` | **Lista mestra de clientes**: 225 clientes, 52 códigos que não estão na base. Colunas de acompanhamento 100% vazias e grade Jan–Dez preenchida em 9 linhas |
| `Dashboard` | Agregava por **vencimento**, não por competência, e misturava valor original com total atualizado |
| `Configurações` | Listas de status, tipo, tipo de faturamento, forma de envio e Boleto/Pix |

**Fórmulas preservadas:** `dias = TODAY() − vencimento` (só se `Em aberto` e
vencido), `juros = ROUND(dias × juros_dia; 2)`, `total = valor + juros`,
`total do cliente = SUMIFS` dos em aberto.

**Sujeira encontrada e tratada na importação:**

- Competência em quatro formatos: texto `MM/AAAA` (206), data (1), serial do
  Excel `46174` (1), nome de serviço `ATA DE SOCIOS` (1) e vazia (3).
- 1 linha sem código, 5 sem CPF/CNPJ, 3 sem vencimento, 2 sem valor, 3 sem juros.
- Mesmo nome com códigos diferentes.
- Juros/dia divergente entre linhas do mesmo cliente (4 clientes).
- Cobranças como texto livre na coluna Observações: 15 linhas preenchidas, 48
  linhas de texto, 47 no formato `dd/mm/aaaa - texto`.

**Resultado da importação da planilha real:** 229 clientes, 252 honorários e 47
cobranças; 6 linhas ficaram de fora (3 sem valor, 3 sem vencimento) com o motivo
no relatório.

## 2. Cálculo (item central, em `dominio/juros.py`)

- Dias em atraso: `vencimento+1 … data de referência`.
- Para cada dia vale o juros/dia vigente **naquele dia** (histórico do cliente).
- `juros = ROUND(Σ dias do segmento × taxa do segmento, 2)` — por segmentos, não
  dia a dia.
- Exemplo verificado em teste: vencimento 01/09, 0,50/dia até 14/09 e 1,00 a
  partir de 15/09, referência 20/09 → 13 × 0,50 + 6 × 1,00 = **R$ 12,50**.
- Simulação por data em toda tela que mostra total (campo "Simular para").
- `Cancelado` e `Renegociado` não geram juros nem entram em cobrança.
- "Hoje" é a data local em `America/Sao_Paulo`.

## 3. Mensagem de cobrança (`dominio/mensagens.py`)

Três modelos editáveis: **um honorário**, **vários honorários** e **lembrete**
(antes do vencimento, sem "consta em aberto" e sem "atualizado").

Variáveis: `{saudacao}`, `{nome_tratamento}`, `{empresa}`, `{descricao}`,
`{competencia}`, `{ano}`, `{vencimento}`, `{valor}`, `{valor_original}`,
`{juros}`, `{dias_atraso}`, `{expressao_valor}`, `{data_referencia}`,
`{lista_honorarios}`, `{quantidade}`, `{valor_total}`,
`{expressao_valor_total}`, `{razao_social}`, `{rotulo_chave}`, `{chave_pix}`,
`{constam}`, `{honorarios}`.

A descrição de cada honorário vem do **tipo** (três textos: sem empresa, com
empresa e linha de lista), o que permite "honorário referente à competência
08/2026", "honorário referente ao seu imposto de renda/2026" e "boleto referente
ao serviço de Alteração Contratual" com o mesmo motor.

Saudação por horário (Bom dia < 12h, Boa tarde < 18h, Boa noite), com ou sem
nome de tratamento, nas duas ordens. Modelo com variável inexistente é recusado
ao salvar, com a lista do que existe.

## 4. Modelo de dados

`cliente` · `cliente_contato` (nome, **nome_tratamento**, whatsapp, principal) ·
`cliente_juros` (valor_dia, valor_anterior, **vigencia_inicio**, motivo) ·
`grupo_honorario` · `tipo_honorario` (grupo, periodicidade,
`exige_competencia`, três textos de mensagem) · `contrato` +
`contrato_historico` · `honorario` (competência ano/mês + `competencia_chave`,
valor_original, **saldo_aberto**, status, situação de envio, total_congelado) ·
`pagamento` (dias_atraso, juros_devidos, juros_cobrados, desconto,
justificativa, total — tudo congelado) · `cobranca_lote` (uma mensagem) +
`cobranca` (uma por honorário, com resultado, promessa e valor no momento) ·
`renegociacao` + `renegociacao_item` · `acordo_valor` (oferta com prazo, da
imagem da cobrança) · `modelo_mensagem` · `configuracao` · `forma_envio` ·
`notificacao` · `email_mensagem` (os e-mails da pasta Cobranças, com as
correções de linha) · `importacao` + `importacao_erro` · `log_alteracao`.

Índice único parcial em `(cliente, tipo, competencia_chave)` ignorando
cancelados: é o que impede a geração de competência duplicar. Os índices
parciais valem no SQLite e no PostgreSQL, e a suíte de testes roda nos dois.

As migrações são do Alembic. Banco novo recebe todas as tabelas e é marcado na
última versão; banco existente é atualizado ao abrir.

## 5. Fases entregues

| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Esqueleto, `.gitignore`, Alembic, pytest | concluída |
| 1 | Clientes PF/PJ/Doméstica, contatos, juros com vigência, cálculo com testes | concluída |
| 2 | Tipos, contratos, geração de competência, avulsos, baixa (total, parcial, abono) | concluída |
| 3 | Cobrança geral, ficha da empresa, fluxo "Cobrar" com WhatsApp | concluída |
| 4 | Cobrança em sequência de várias empresas, importação da planilha, backup (as filas do dia e de envio saíram depois, a pedido) | concluída |
| 5 | Painel, exportação Excel/PDF, renegociação, reajuste em massa | concluída |
| 6 | Telas por situação (A vencer, Atrasados, Pagos por competência), rankings, análise de juros, Clientes de IR | concluída |
| 7 | Imagem da cobrança com Pix e acordo, comprovante "Pagamento confirmado", notificações | concluída |
| 8 | Gerenciador de e-mail (Outlook/Microsoft 365 e Gmail): conferência da lista, baixa dos que saíram, correção de linhas, resposta | concluída |
| 9 | Honorário recorrente no cadastro do cliente, "Paga pela empresa", geração automática, próximo dia útil | concluída |
| 10 | PostgreSQL do escritório, primeiro uso, backup/restauração, instalador do Windows — **versão 1.0.0** | concluída |

## 6. O que continua fora do sistema

Emissão de boleto, baixa automática por banco e envio automático de mensagem.
O sistema registra, calcula e prepara o texto. O WhatsApp é sempre enviado à
mão, e o e-mail de resposta ao financeiro só sai depois da confirmação de quem
usa o sistema. Nenhuma baixa vem do e-mail sem confirmação.
