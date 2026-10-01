# Controle de Honorários e Cobrança

Aplicativo desktop (Python + PySide6 + SQLite) que substitui a planilha de
controle de honorários do escritório: registra honorários, cobranças e
pagamentos, recalcula o valor atualizado com o juros diário de cada cliente e
monta a mensagem de cobrança pronta para o WhatsApp.

O sistema **não envia nada sozinho**: ele gera o texto, copia para a área de
transferência e, se você pedir, abre a conversa no WhatsApp. O registro da
cobrança só acontece quando você confirma — copiar não é enviar.

## Como rodar

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m honorarios.app
```

O banco fica em `dados/honorarios.db` (fora do git). Para trabalhar com uma
cópia, aponte outra pasta:

```bash
HONORARIOS_DADOS=/tmp/teste .venv/bin/python -m honorarios.app
```

## Dados de exemplo

Para conhecer o sistema sem usar dados reais:

```bash
.venv/bin/python scripts/dados_exemplo.py            # cria, se o banco estiver vazio
.venv/bin/python scripts/dados_exemplo.py --limpar   # apaga tudo e recria
```

São 14 clientes fictícios (PF, PJ e domésticas) com contatos de WhatsApp,
contratos, nove meses de competências geradas, pagamentos em dia e em atraso,
pagamento parcial, abono de juros, honorário que vence hoje e outro que vence em
breve, IRPF, serviços avulsos, um cancelado, um acordo de renegociação e
cobranças com promessa cumprida e vencida — o suficiente para todas as telas
terem conteúdo.

Para começar a valer com os seus dados: rode `--limpar` para apagar o exemplo e
use a tela **Importar planilha**.

## Como testar

```bash
.venv/bin/python -m pytest          # tudo
.venv/bin/python -m pytest testes/dominio   # só as regras (sem Qt)
.venv/bin/ruff check src testes
```

Os testes de interface usam `pytest-qt` e rodam sem servidor gráfico
(`QT_QPA_PLATFORM=offscreen`, já configurado em `testes/conftest.py`).

## Telas

| Tela | Para que serve |
|---|---|
| **Atrasados** | A tela de trabalho da cobrança: só os vencidos e em aberto, agrupados por faixa de atraso (a dívida mais antiga primeiro), com cobrar, cobrança em lote e renegociação |
| **A vencer** | Em aberto e dentro do prazo: vence hoje, nos próximos dias e mais adiante. Daqui sai o lembrete antes do vencimento |
| **Pagos** | Registro dos quitados, por mês do pagamento, com seletor de período (padrão: últimos 3 meses). Mostra se pagou em dia ou com atraso, os juros cobrados e o abono |
| **Imposto de Renda** | Cobrança própria dos clientes que só fazem IR com o escritório: em aberto (atrasados e a vencer) ou pagos, com filtro por ano do IR. Esses clientes não aparecem em Atrasados, A vencer e Pagos |
| **Cobranças enviadas** | Cada mensagem enviada e o que o cliente respondeu, com período e agrupamento à escolha. É aqui que a resposta é anotada |
| **Clientes** | PF \| PJ \| Todos, busca sem acento/pontuação, total em aberto e maior atraso; ficha completa da empresa. Aqui também se suspende e retoma a cobrança de um cliente |
| **Honorários recorrentes** | Contratos, reajuste (individual e em massa) e "Gerar competência MM/AAAA" com prévia |
| **Honorários avulsos** | IRPF, alteração contratual, atas e afins |
| **Painel** | O ano em números e gráficos: emitido × quitado por mês de competência (com a opção de ver em tabela), o que entrou no caixa por mês, de onde vem o faturamento (grupo e PF/PJ) e frases com o que os números dizem, comparando com o ano anterior quando há base. Atraso e devedores ficam no Ranking dos atrasados |
| **Ranking dos atrasados** | Pódio de quem mais deve em dinheiro, quem deve há mais tempo, quem junta mais boletos e quem mais foi cobrado — dois gráficos por aba; clicar num nome abre a ficha. A aba **Análise de juros** lista os clientes que pagaram e mostra, para cada um, original + juros = pago, o trabalho que deu para receber (atrasos, dias em atraso, cobranças feitas, juros por cobrança, comparados com a média), honorário por honorário, uma explicação em frases e cenários de taxa (+10% a dobrar, sem abono, valor testado) com o efeito de cada cenário honorário por honorário; **Exportar PDF…** gera o relatório da análise do cliente (documento interno) para compartilhar; o primeiro item é a visão geral de todos |
| **Relatórios e exportação** | Planilha Excel da lista filtrada e extrato de débitos em PDF |
| **Importar planilha** | Lê a planilha antiga, mostra prévia e relatório de erros, e só grava depois da confirmação |
| **Grupos e tipos** | Grupos à esquerda (a ordem é a das seções nas telas), tipos do grupo à direita, cada um mostrando a frase como sai na cobrança e quanto é usado. O cadastro do tipo mostra a prévia da mensagem enquanto se digita |
| **Configurações** | PIX, modelos de mensagem, formas de envio e backup |

A navegação é agrupada por momento do trabalho: **Honorários** (Atrasados, A
vencer e Pagos, cada um com a sua tela e o contador ao lado), **Cobrança**,
**Cadastros** e **Gestão**.

Atalhos: `F5` atualiza, `Ctrl+1..9` troca de tela, `Ctrl+B` cobra, `Ctrl+P`
registra pagamento, `Ctrl+R` registra a resposta, `Ctrl+F` abre a ficha, `Ctrl+C`
copia a mensagem, `Ctrl+W` abre o WhatsApp, `Ctrl+G` gera competência.

### Suspender a cobrança de um cliente

Na ficha do cliente (ou na lista), **Suspender cobrança** pede o motivo e, se
você quiser, a data de retomada automática. O cartão dele fica cinza com a
etiqueta "Cobrança suspensa" e o sistema recusa registrar cobrança dele até você
retomar.

A dívida não muda: os honorários seguem em aberto e o juros continua correndo —
o que para é a cobrança.

### Escolher cliente e alterar juros

Onde se escolhe um cliente (contrato, honorário avulso, extrato, empresa que
paga), há um campo de busca: digite nome (sem se preocupar com acento), código
ou parte do CPF/CNPJ e aperte Enter. Com o código exato ou um resultado só, a
escolha é direta; senão abre a janela de busca, que filtra enquanto você digita.

O juros ao dia muda pelo botão **Alterar juros ao dia…** no cadastro do cliente
ou **Alterar juros** no topo da ficha. A mudança pede a data de vigência e vale
só dali para frente.

### Pessoa física que paga pela empresa

No cadastro de uma pessoa física há o campo **"Paga pela empresa"**. Quando ele
está preenchido, a tela de Cobrar da empresa oferece **"Incluir N honorário(s)
de N pessoa(s) que pagam por esta empresa"**: marcando, os honorários dela
entram na mesma mensagem, e cada linha diz de quem é —
`• SOCIO EXEMPLO: imposto de renda/2026, vencimento 25/06/2026 – R$ 269,24`.

O vínculo tem um nível só (pessoa física → pessoa jurídica) e não muda a quem o
honorário pertence: ele continua na ficha da pessoa.

### Como a cobrança anda

1. **Atrasados**: escolhe os honorários e clica em Cobrar. Selecionando
   honorários de várias empresas, a cobrança passa uma empresa por vez, com a
   mensagem de cada uma pronta.
   Para o que ainda não venceu, **A vencer** manda um lembrete.
2. O diálogo monta a mensagem; você copia ou abre o WhatsApp e clica em
   **Marcar como cobrado**. A cobrança nasce *aguardando resposta* — nada de
   resposta é pedido nesse momento, porque ela ainda não existe.
3. Quando o cliente responde, a resposta entra em **Cobranças enviadas** (ou pelo
   botão Histórico do próprio honorário): prometeu pagar, pediu renegociação,
   contestou, não respondeu.
4. O **Histórico** de cada honorário mostra a linha do tempo completa e diz
   quando a cobrança saiu em lote e com quais outros honorários.

### Imagem da cobrança

No diálogo Cobrar, **Imagem da cobrança…** (Ctrl+I) gera uma imagem com os
honorários marcados — um ou vários — sobre o fundo SVG do escritório, com o
QR code do Pix. **Copiar imagem** põe no clipboard para colar no WhatsApp;
**Copiar chave Pix** copia a chave para mandar como texto logo depois;
**Salvar PNG…** guarda o arquivo. Copiar não registra a cobrança.

O fundo é escolhido em **Configurações → Imagem da cobrança** (sem ele, vale o
modelo do sistema, que também pode ser salvo como ponto de partida). No SVG:

- textos com `{cliente}`, `{codigo}`, `{data}`, `{total}`, `{total_original}`,
  `{total_juros}`, `{quantidade}`, `{recebedor}`, `{chave_pix}` viram os valores;
- um retângulo transparente com `id="lista"` recebe os honorários, um por linha.
  Se não couberem, a imagem **estica**: a faixa logo acima do fim da lista é
  repetida e tudo o que está abaixo desce inteiro (até 30 linhas; dali em diante,
  "e mais N honorários"); `data-fonte`, `data-cor`,
  `data-cor-fraca` e `data-cor-linha` nesse retângulo mudam fonte e cores;
- um retângulo transparente com `id="qrcode"` recebe o PNG do QR code (270 px de lado
  ou mais, num fundo de 1080 de largura).

- a camada da cobrança (textos, lista, QR) fica num grupo `<g id="conteudo">`:
  o **PDF da análise de juros** usa o fundo sem esse grupo como papel das
  páginas (esticado para A4 no meio, sem deformar os logos).

O QR code é o da chave Pix, **gerado no app do banco**: salve como PNG e
escolha em **Configurações → Imagem da cobrança → Escolher PNG do QR code…**.
É o QR da chave, sem valor — o cliente digita o valor ao pagar. Sem PNG
escolhido, a imagem sai sem QR e a prévia avisa onde escolher.

## Arquitetura

```
src/honorarios/
├── dominio/     regras puras, sem Qt e sem banco (juros, mensagens, valores)
├── infra/       modelos SQLAlchemy, migrations Alembic, backup
├── servicos/    orquestração (clientes, honorários, cobrança, importação…)
├── ui/          PySide6: paineis/, dialogos/, comum/ (tabelas, campos, tema)
└── config/      caminhos e log
```

A regra de juros e a geração de mensagem vivem em `dominio/` e não importam Qt:
é o que permite testá-las sem abrir janela. Listas grandes usam
`QAbstractTableModel`/`QAbstractItemModel` com proxy de filtro — nunca um widget
por linha.

## Decisões que valem saber

- **Juros** é um valor fixo em R$ por dia, por cliente, com histórico de
  vigência. Mudança vale **a partir da data da mudança**, nunca para trás.
- **Dinheiro é `Decimal`** do começo ao fim, gravado como texto na coluna
  NUMERIC. O arredondamento acontece uma única vez, no total.
- **Baixa congela**: data, dias de atraso, juros devidos, juros cobrados,
  desconto e total ficam gravados. Mudar o juros depois não altera o que foi pago.
- **Nada é apagado**: exclusão lógica (`excluido_em`) e estorno
  (`estornado_em`), com registro em `log_alteracao`.
- **Dados pessoais**: banco, planilhas, backups e exportações estão no
  `.gitignore`. Nenhum dado real de cliente entra no repositório nem nos testes.

O detalhamento está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md) e
[docs/DECISOES.md](docs/DECISOES.md).

## Empacotar (quando chegar a hora)

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --name honorarios --windowed --onefile \
  --add-data "src/honorarios/infra/migracoes:honorarios/infra/migracoes" \
  src/honorarios/app.py
```
