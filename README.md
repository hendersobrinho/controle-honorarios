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
| **Cobrança geral** | Tela de trabalho. Pendentes \| Pagos \| Todos, nunca misturados; cada honorário é um cartão com faixa colorida de situação e botão para o seu histórico. O histórico de pagos tem seletor de período (padrão: últimos 3 meses) |
| **Fila do dia** | Promessa vencida, vence hoje, nunca cobrado e sem cobrança há X dias (substitui a aba "Recall Inadimplentes") |
| **Fila de envio** | Cobrança em lote: marca as empresas e o assistente passa uma por vez com a mensagem pronta |
| **Acompanhamento** | Cada mensagem enviada e o que o cliente respondeu, com período e agrupamento à escolha. É aqui que a resposta é anotada |
| **Clientes** | PF \| PJ \| Todos, busca sem acento/pontuação, total em aberto e maior atraso; ficha completa da empresa. Aqui também se suspende e retoma a cobrança de um cliente |
| **Honorários recorrentes** | Contratos, reajuste (individual e em massa) e "Gerar competência MM/AAAA" com prévia |
| **Honorários avulsos** | IRPF, alteração contratual, atas e afins |
| **Painel** | Emitido, pago, em aberto, juros, inadimplência, faixas de atraso e maiores devedores |
| **Relatórios e exportação** | Planilha Excel da lista filtrada e extrato de débitos em PDF |
| **Importar planilha** | Lê a planilha antiga, mostra prévia e relatório de erros, e só grava depois da confirmação |
| **Configurações** | PIX, modelos de mensagem, tipos, grupos, formas de envio e backup |

A navegação é agrupada por momento do trabalho: **Cobrança**, **Cadastros** e
**Gestão**.

Atalhos: `F5` atualiza, `Ctrl+1..9` troca de tela, `Ctrl+B` cobra, `Ctrl+P`
registra pagamento, `Ctrl+R` registra a resposta, `Ctrl+F` abre a ficha, `Ctrl+C`
copia a mensagem, `Ctrl+W` abre o WhatsApp, `Ctrl+G` gera competência.

### Suspender a cobrança de um cliente

Na ficha do cliente (ou na lista), **Suspender cobrança** pede o motivo e, se
você quiser, a data de retomada automática. O cliente sai da **Fila do dia** e
da **Fila de envio**, o cartão dele fica cinza com a etiqueta "Cobrança
suspensa", e o sistema recusa registrar cobrança dele até você retomar.

A dívida não muda: os honorários seguem em aberto e o juros continua correndo —
o que para é a cobrança.

### Pessoa física que paga pela empresa

No cadastro de uma pessoa física há o campo **"Paga pela empresa"**. Quando ele
está preenchido, a tela de Cobrar da empresa oferece **"Incluir N honorário(s)
de N pessoa(s) que pagam por esta empresa"**: marcando, os honorários dela
entram na mesma mensagem, e cada linha diz de quem é —
`• SOCIO EXEMPLO: imposto de renda/2026, vencimento 25/06/2026 – R$ 269,24`.

O vínculo tem um nível só (pessoa física → pessoa jurídica) e não muda a quem o
honorário pertence: ele continua na ficha da pessoa.

### Como a cobrança anda

1. **Cobrança geral** ou **Fila do dia**: escolhe os honorários e clica em Cobrar.
2. O diálogo monta a mensagem; você copia ou abre o WhatsApp e clica em
   **Marcar como cobrado**. A cobrança nasce *aguardando resposta* — nada de
   resposta é pedido nesse momento, porque ela ainda não existe.
3. Quando o cliente responde, a resposta entra no **Acompanhamento** (ou pelo
   botão Histórico do próprio honorário): prometeu pagar, pediu renegociação,
   contestou, não respondeu.
4. O **Histórico** de cada honorário mostra a linha do tempo completa e diz
   quando a cobrança saiu em lote e com quais outros honorários.

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
