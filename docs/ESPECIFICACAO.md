# Especificação — Financeiro Métodos 1.5.1

Consolidação do que foi acordado, do que a planilha antiga fazia e do que o
sistema faz no lugar dela.

| | |
|---|---|
| **Programa** | Financeiro Métodos |
| **Versão** | 1.5.1 (outubro de 2026) |
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
- Na tela Cobrar, os juros vão até **valores atualizados até** (hoje, ou outra
  data); o **vencimento (pagar até)** é só o prazo da imagem e do lembrete e não
  muda os juros. A conta de cada honorário aparece por extenso, e o juros pode
  ser digitado à mão só naquela cobrança (vale para mensagem, imagem, acordo e
  registro).
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
Os layouts da importação personalizada ficam em `configuracao`, na chave
`importacao_layouts` (JSON), sem tabela própria.

Índice único parcial em `(cliente, tipo, competencia_chave)` ignorando
cancelados: é o que impede a geração de competência duplicar. Os índices
parciais valem no SQLite e no PostgreSQL, e a suíte de testes roda nos dois.

As migrações são do Alembic. Banco novo recebe todas as tabelas e é marcado na
última versão; banco existente é atualizado ao abrir.

## 5. Fases entregues

| Fase | Conteúdo | Versão | Situação |
|---|---|---|---|
| 0 | Esqueleto, `.gitignore`, Alembic, pytest | 1.0.0 | concluída |
| 1 | Clientes PF/PJ/Doméstica, contatos, juros com vigência, cálculo com testes | 1.0.0 | concluída |
| 2 | Tipos, contratos, geração de competência, avulsos, baixa (total, parcial, abono) | 1.0.0 | concluída |
| 3 | Cobrança geral, ficha da empresa, fluxo "Cobrar" com WhatsApp | 1.0.0 | concluída |
| 4 | Cobrança em sequência de várias empresas, importação da planilha, backup (as filas do dia e de envio saíram depois, a pedido) | 1.0.0 | concluída |
| 5 | Painel, exportação Excel/PDF, renegociação, reajuste em massa | 1.0.0 | concluída |
| 6 | Telas por situação (A vencer, Atrasados, Pagos por competência), rankings, análise de juros, Clientes de IR | 1.0.0 | concluída |
| 7 | Imagem da cobrança com Pix e acordo, comprovante "Pagamento confirmado", notificações | 1.0.0 | concluída |
| 8 | Gerenciador de e-mail (Outlook/Microsoft 365 e Gmail): conferência da lista, baixa dos que saíram, correção de linhas, resposta | 1.0.0 | concluída |
| 9 | Honorário recorrente no cadastro do cliente, "Paga pela empresa", geração automática, próximo dia útil | 1.0.0 | concluída |
| 10 | PostgreSQL do escritório, primeiro uso, backup/restauração, instalador do Windows | 1.0.0 | concluída |
| 11 | Assinatura em imagem no e-mail ao financeiro; juros da imagem da cobrança até o "Pagar até" | 1.0.1 | concluída |
| 12 | Importação personalizada: coluna do Excel de cada informação, layout salvo e exportado como modelo, conferência que não duplica cliente PF/PJ, contrato nem honorário | 1.1.0 | concluída |
| 13 | Conta Microsoft guardada no cofre do Windows em pedaços (corrige o erro 1783 do CredWrite), prévia da importação conferida em memória | 1.1.1 | concluída |
| 14 | Identidade visual do Financeiro: ícone canhoto, abertura, menu lateral navy de tamanho fixo, PDFs no papel do canhoto, imagem de cobrança e comprovante na identidade nova com o QR do Pix do escritório de fábrica, e o assistente do instalador com a marca | 1.2.0 | concluída |
| 15 | Busca das telas de honorários sem travar (espera a digitação, redesenho único, "Buscando…" discreto) e integração com o Claude: servidor MCP com 38 ferramentas (consulta e gravação com as regras das telas, e-mail do financeiro, cobrança no WhatsApp), aba Configurações → Claude (MCP) e o `FinanceiroMetodosMCP.exe` no instalador | 1.3.0 | concluída |
| 16 | O servidor MCP se grava sozinho, a cada abertura, em todo Claude do computador: Claude Desktop comum, Claude Desktop da Microsoft Store (que lê de dentro do pacote) e Claude Code; a aba do Claude passa a mostrar onde está gravado | 1.3.1 | concluída |
| 17 | Claude com acesso a todo o cadastro e ao banco: contatos um a um e em lote cruzando a lista das empresas com o cadastro, planilhas e layouts da importação personalizada, tipos, grupos e formas de envio, geração dos contratos, acordo, renegociação, backup e SQL direto (consulta e gravação, com log) — 61 ferramentas | 1.4.0 | concluída |
| 18 | Tela Cobrar refeita em passos (honorários, conferência dos juros, datas, mensagem e imagem): a conta de cada honorário por extenso, juros digitado à mão, "valores atualizados até" (hoje ou outra data) separado do "vencimento (pagar até)" — corrige a imagem que cobrava juros até o prazo —, lembrete com o vencimento escolhido e prévia da imagem na própria tela; o MCP ganha as mesmas opções. Atualização pelo próprio sistema (Configurações → Atualizações: consulta o GitHub, baixa, confere o SHA-256, instala em silêncio e reabre; aviso de versão nova ao abrir) e o GitHub Actions que gera e publica o instalador a cada tag | 1.5.0 | concluída |
| 19 | Empacotamento do MCP sem o `mcp.cli` (exigia o `typer` e derrubava o PyInstaller no Windows limpo do GitHub Actions): primeira versão publicada pela automação | 1.5.1 | concluída |

Cada fase com recurso novo sobe a versão do meio; correção sobe a última. A 1.0.0
chegou a ser reaproveitada para as fases 12 e 13 enquanto o sistema não estava
em uso; a numeração acima é a que vale.

## 6. O que continua fora do sistema

Emissão de boleto, baixa automática por banco e envio automático pelo WhatsApp.
O sistema registra, calcula e prepara o texto. O WhatsApp é sempre enviado à
mão: nem o sistema nem o Claude apertam Enviar. O e-mail de resposta ao
financeiro só sai com a confirmação de quem usa o sistema — na tela, pelo botão
Enviar; pelo Claude, quando a pessoa pede o envio. Nenhuma baixa vem do e-mail
sem confirmação.

## 7. Integração com o Claude (MCP)

O sistema é também um servidor MCP (`honorarios.mcp_servidor`; no instalado,
`FinanceiroMetodosMCP.exe`, executável de console ao lado do programa, porque o
protocolo usa a entrada e a saída padrão). O Claude abre o servidor quando
precisa; ele usa o mesmo banco do programa e a mesma camada de serviços das
telas, então juros, validações e log valem igual. Cada ferramenta grava numa
transação própria.

| Área | O que o Claude faz |
|---|---|
| Consulta | Resumo, clientes, honorários com juros na data, histórico de cobrança, prévia de baixa, rankings, tipos, contratos, configurações |
| Cadastro | Cria, altera e exclui cliente (contatos preservados), vínculo PF → empresa, juros com vigência, suspende e retoma cobrança |
| Honorários | Lança, corrige, cancela; dá baixa (total, parcial, abono) e estorna |
| Cobrança | Registra cobrança e promessa, estorna, gera o texto do modelo |
| Contatos | Adiciona, atualiza e remove; cruza uma lista de contatos das empresas com o cadastro (código, CPF/CNPJ, telefone já cadastrado — com ou sem 55 e o 9 — ou nome exato) e grava os que baterem: telefone igual atualiza o contato, senão entra novo |
| Contratos | Cria, reajusta, suspende, exclui; gera os honorários de uma competência |
| Cadastros de apoio | Tipos e grupos de honorário, formas de envio, acordo de valor, renegociação em parcelas, backup |
| Planilhas | Lê `.xlsx`/`.csv`; cria, apaga e exporta layouts da importação personalizada; prévia e importação |
| Banco | Estrutura das tabelas, consulta SQL (sempre desfeita) e comando SQL que grava, anotado no log |
| E-mail do financeiro | Verifica a pasta, lê e confere a lista com o sistema, dá baixa em quem saiu, responde com a lista atualizada (rascunho `.eml` aberto no Outlook ou envio pela conta do sistema) |
| WhatsApp | Abre a conversa do contato com a mensagem e a chave Pix na última linha (da imagem não dá para copiar) e deixa a imagem de cobrança copiada para Ctrl+V |

Não há modo somente leitura (pedido do escritório). As ferramentas que apagam
ou desfazem levam `destructiveHint`, para o Claude pedir confirmação. A cada
chamada o servidor anota a hora e a ferramenta. O programa instalado, ao abrir,
grava o servidor em cada Claude do computador, sem mexer nos outros servidores:
Claude Desktop comum (`%APPDATA%\Claude`), Claude Desktop da Microsoft Store (o
Windows desvia o `%APPDATA%` dele para dentro do pacote, em
`%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude`) e Claude Code
(`.claude.json` do usuário). A aba **Configurações → Claude (MCP)** mostra onde
está gravado e o último uso.

O rascunho direto na pasta Rascunhos do Outlook exigiria a permissão
`Mail.ReadWrite` no aplicativo da Microsoft, que hoje tem só `Mail.Read` e
`Mail.Send`; por isso o rascunho é o `.eml` ligado à conversa. Com o conector do
Microsoft 365 ligado no próprio Claude, ele pode criar o rascunho por lá a partir
de `montar_resposta_financeiro`.
