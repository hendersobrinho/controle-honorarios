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
| **Vencimentos → A vencer** (1ª aba) | Em aberto e dentro do prazo: vence hoje, nos próximos dias e mais adiante. Daqui sai o lembrete antes do vencimento |
| **Vencimentos → Atrasados** | A tela de trabalho da cobrança: só os vencidos e em aberto, agrupados por faixa de atraso (a dívida mais antiga primeiro), com cobrar, editar (valor, vencimento, descrição), **Confirmar pagamento** (botão verde em cada cartão em aberto, também em A vencer e Imposto de Renda), cobrança em lote e renegociação |
| **Vencimentos → Pagos** | Registro dos quitados, por mês do pagamento, com seletor de período (padrão: últimos 3 meses). Mostra se pagou em dia ou com atraso, os juros cobrados e o abono |
| **Imposto de Renda** | Cobrança própria dos clientes que só fazem IR com o escritório: em aberto (atrasados e a vencer) ou pagos, com filtro por ano do IR. Esses clientes não aparecem em Atrasados, A vencer e Pagos |
| **Cobranças enviadas** | Cada mensagem enviada e o que o cliente respondeu, com período e agrupamento à escolha. É aqui que a resposta é anotada |
| **Clientes** | Abas **Ativos**, **Imposto de Renda** (quem só tem honorário de IR) e **Inativos**; PF \| PJ \| Todos e busca sem acento/pontuação; ficha completa da empresa. Dívida e atraso não aparecem aqui (têm telas próprias). Aqui também se suspende e retoma a cobrança de um cliente |
| **Honorários** | Três abas. **Mês a mês**: tudo o que foi emitido no mês (recorrente ou avulso), com ◀ ▶ e um menu para ir direto a qualquer mês, os totais (emitido, pago, em aberto, cancelados), filtros de origem e situação, e o aviso de contratos que ainda não geraram a competência — "Gerar competência" já abre no mês da tela. **Recorrentes**: contratos, reajuste (individual e em massa) e "Gerar competência MM/AAAA" com prévia. **Avulsos**: lançar, corrigir e cancelar serviços que não vêm de contrato (IRPF, alteração contratual, atas…) e consultar o histórico por período, pagos ou não, com a situação de cada um. A cobrança desses honorários fica em Atrasados e A vencer |
| **Painel** | O ano em números e gráficos: emitido × quitado por mês de competência (com a opção de ver em tabela), o que entrou no caixa por mês, de onde vem o faturamento (grupo e PF/PJ) e frases com o que os números dizem, comparando com o ano anterior quando há base. **Exportar PDF…** gera o relatório no mesmo visual da análise de juros (fundo da cobrança, gráficos e tabela mês a mês). Atraso e devedores ficam no Ranking dos atrasados |
| **Ranking dos atrasados** | Pódio de quem mais deve em dinheiro, quem deve há mais tempo, quem junta mais boletos e quem mais foi cobrado — dois gráficos por aba; clicar num nome abre a ficha. A aba **Análise de juros** lista os clientes que pagaram e mostra, para cada um, original + juros = pago, o trabalho que deu para receber em gráfico (ele × a média dos clientes: atrasos, dias em atraso, cobranças, juros por cobrança), a linha do tempo do atraso de cada honorário com as cobranças feitas, um gráfico dos cenários, honorário por honorário, uma explicação em frases e cenários de taxa (+10% a dobrar, sem abono, valor testado) com o efeito de cada cenário honorário por honorário; **Exportar PDF…** gera o relatório da análise do cliente (documento interno) para compartilhar; o primeiro item é a visão geral de todos |
| **Relatórios e exportação** | Planilha Excel da lista filtrada e extrato de débitos em PDF |
| **Importar planilha** | Lê a planilha antiga, mostra prévia e relatório de erros, e só grava depois da confirmação |
| **Grupos e tipos** | Grupos à esquerda (a ordem é a das seções nas telas), tipos do grupo à direita, cada um mostrando a frase como sai na cobrança e quanto é usado. O cadastro do tipo mostra a prévia da mensagem enquanto se digita |
| **Configurações** | PIX, modelos de mensagem, formas de envio e backup |

A navegação é agrupada por momento do trabalho:

- **Cobrança**: **Vencimentos** (abas A vencer, Atrasados e Pagos, com a
  quantidade em aberto em cada aba; o número no menu é o de atrasados), Imposto
  de Renda, Cobranças enviadas e E-mail (com o número de e-mails não lidos).
- **Cadastros**.
- **Gestão**.

Cada grupo tem a sua cor da logo (Cobrança em verde-água, Cadastros em
laranja, Gestão em azul). O nome do grupo fica numa faixa, e um fio da mesma cor
acompanha as telas dele.

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

No cadastro de uma pessoa física há o campo **"Paga pela empresa"**. Ele quer
dizer que o que a empresa paga já cobre essa pessoa. Por isso a geração da
competência (manual ou automática) **não cria honorário para ela**, e a prévia
mostra o motivo, "Paga pela empresa …". O cadastro fica. Se um dia for preciso,
dá para lançar um honorário para ela à mão. Para esse honorário, a tela de
Cobrar da empresa oferece **"Incluir N honorário(s)
de N pessoa(s) que pagam por esta empresa"**: marcando, os honorários dela
entram na mesma mensagem, e cada linha diz de quem é —
`• SOCIO EXEMPLO: imposto de renda/2026, vencimento 25/06/2026 – R$ 269,24`.

O vínculo tem um nível só (pessoa física → pessoa jurídica) e não muda a quem o
honorário pertence: ele continua na ficha da pessoa.

### Agradecimento pelo pagamento

Ao confirmar um pagamento, a caixa **"Abrir a imagem de agradecimento"** gera a
imagem "Pagamento confirmado" para copiar e mandar ao cliente. Ela é um
comprovante, de propósito diferente da cobrança: cartão branco com a logo nas
cores originais, o selo de confirmação e o total pago num painel verde-água
claro, e embaixo um canhoto com o cliente, o CNPJ e o que foi pago. Sai em
1620 px de largura, mais nítida que a cobrança. A escolha da
caixa fica lembrada. Nos cartões de **Pagos** o botão **Agradecimento** gera a
mesma imagem depois.

### Ao abrir

O sistema abre com a logo (Métodos Financeiro) e uma barra de carregamento; a
logo fica depois no pé do menu lateral. Não aparece nenhum cartão de resumo ao
abrir: o que pede atenção fica no contador de **Notificações** e nos números ao
lado de cada tela do menu.

### Geração automática dos honorários mensais

Em **Configurações → Honorários mensais** dá para ligar **"Gerar a competência do
mês automaticamente"** e escolher a partir de qual dia (1 a 28). Ela vem
desligada. Ligada, a partir desse dia o sistema gera a competência do mês ao
abrir, ou com ele aberto, e avisa nas notificações. Valem as mesmas regras da
geração manual: contrato suspenso, fora da vigência ou já lançado fica de fora.
Ela roda uma vez por competência, então o que você cancelar depois no Mês a mês
não volta. Um contrato criado no meio do mês entra pela geração manual, e a
tela Mês a mês avisa o que falta.

### E-mail

O financeiro manda o e-mail **"Clientes c/Honorários vencidos"** com a lista de
quem está em aberto, e quem cobra responde com o andamento. A tela **E-mail de
cobranças** — no menu, só **E-mail** — é uma caixa de e-mail só dessa conversa.

**A tela**
- À esquerda, duas listas separadas: **Recebidos** (o que o financeiro mandou,
  com as etiquetas *Nova* e *Respondida*) e **Enviados por você** (as respostas
  que saíram do sistema).
- **Verificar caixa** busca os e-mails novos. O sistema também verifica sozinho
  ao abrir e a cada 30 minutos. E-mail novo vira notificação, e o menu mostra
  quantos não foram lidos.
- À direita fica o e-mail aberto, com três abas:
  - **Mensagem**: o e-mail como chegou.
  - **Conferir com o sistema**: quem continua, quem **saiu da lista** (provável
    pagamento), o que já foi pago no sistema e o que não bate com nada.
    - Ao abrir um e-mail novo com gente que saiu, a janela **Baixa dos que
      saíram da lista** abre sozinha, ao lado, sem travar o sistema, para
      conferir no próprio e-mail. Nela vêm a data do pagamento (padrão: a data
      do e-mail), o valor (com juros até a data, ou só o valor original com
      abono justificado), a forma de pagamento e um ✓ por honorário.
    - **Dar baixa** sempre pede confirmação. Nada é baixado sozinho.
    - **Corrigir…**: para a linha do e-mail que não bateu com o sistema. A
      janela mostra os honorários mais parecidos (cliente, competência,
      vencimento e valor; o mais provável já vem marcado). Escolha a qual
      honorário a linha se refere, ou **Ignorar esta linha**. A escolha fica
      guardada no e-mail, e quem fica sem par passa para "saíram", pronto para a
      baixa. **Desfazer correção** volta atrás.
    - Mesma competência com vencimento diferente (até 31 dias) já conta como o
      mesmo honorário. De um e-mail de resposta, só a mensagem nova é lida (o
      e-mail citado embaixo, "On … wrote:", "De:/Enviado:", linhas com ">", fica
      de fora).
    - **Anotar retorno…**: selecione honorários de um cliente que continua e
      registre o que ele disse (não respondeu, prometeu pagar em…, pediu
      renegociação…). Se há uma cobrança esperando resposta, o retorno vai
      nela; senão, vira um contato de hoje.
  - **Sua resposta**: a resposta pronta. Ela mantém a lista do financeiro, sem
    quem saiu, com as anotações das cobranças. Para, Cc e assunto vêm
    preenchidos ("Responder a todos"). Dá para escrever no texto antes de
    enviar; **Desfazer minhas edições** volta ao texto que o sistema montou.
    **Enviar resposta** pede confirmação e envia pela sua conta, na
    mesma conversa, com o e-mail do financeiro citado embaixo. Também há
    **Copiar** e **Salvar rascunho**.
- Sem conta configurada, o menu **Ações** abre um e-mail de arquivo (.eml, PDF
  impresso do Outlook, .txt), aceita o texto colado ou monta a lista pelo
  sistema.

**O dia a dia**
1. Chega a lista do financeiro: notificação e etiqueta *Nova*.
2. Ao abrir o e-mail, a baixa dos que saíram já aparece. Confira e dê baixa.
3. Cobre os que continuam (pela tela Atrasados, como sempre). Quando o cliente
   responder, anote em **Anotar retorno…** ou em Cobranças enviadas.
4. Na aba **Responder**, a resposta já está montada com o que sobrou em aberto
   e os retornos de cada cliente. Uma anotação que vale só para parte dos
   honorários diz de quais: "(07/2026)". O que foi pago depois do e-mail fica
   de fora. Revise e envie.

**Só esses e-mails.** Uma regra no Outlook (ou um filtro no Gmail) leva os
e-mails do financeiro para uma pasta própria, "Cobranças" por padrão. O sistema
abre só essa pasta e só guarda o que tem o assunto da conversa. Ele lê sem
marcar como lido na caixa.

**Configurar** (Configurações → E-mail de cobranças → **Conta de e-mail…**)

*Outlook / Microsoft 365, uma vez, por quem administra o e-mail:*
1. No portal Microsoft Entra, em **Registros de aplicativo → Novo registro**,
   escolha contas só desta organização.
2. Em **Autenticação**, marque **Permitir fluxos de cliente público** = Sim.
3. Em **Permissões de API**, adicione as permissões delegadas do Microsoft
   Graph **Mail.Read** e **Mail.Send**. Se for pedido, conceda o consentimento
   do administrador.
4. Copie o **ID do aplicativo** e o **ID do diretório (locatário)** para a tela
   Conta de e-mail.
5. No Outlook, crie a pasta **Cobranças** e uma **regra**: de [e-mail do
   financeiro], com o assunto da conversa → mover para a pasta.
6. Em **Entrar na conta Microsoft…**, o sistema mostra um código. Digite esse
   código em microsoft.com/devicelogin e entre com a conta. Isso é feito uma
   vez só.

*Gmail (para testar):*
1. Ative a verificação em duas etapas e crie uma **senha de app** em
   myaccount.google.com/apppasswords.
2. Crie o marcador **Cobranças** e um **filtro**: remetente e assunto → aplicar
   o marcador.
3. Em Conta de e-mail, escolha Gmail, informe o e-mail e a senha de app e
   clique em **Testar conexão**.

*Outro provedor:* informe os servidores IMAP (leitura) e SMTP (envio) e a senha.

A senha de app e a autorização da Microsoft ficam no **cofre de senhas do
sistema** (Gerenciador de Credenciais no Windows), nunca no banco. Os e-mails
baixados ficam no banco local, que não vai para o Git.

### Notificações

No pé do menu, acima da logo, o botão **Notificações** mostra quantas há sem
ler. Elas avisam, por cliente:

- o que **vence hoje**;
- o que **não foi pago na data** (venceu nos últimos 30 dias sem pagamento);
- **promessa** de pagamento que passou;
- **acordo** de valor que vence hoje;
- a **competência gerada automaticamente**, quando a geração automática está ligada.

O sistema verifica ao abrir e a cada 30 minutos enquanto está aberto, sempre com
a data de hoje. Cada fato avisa uma vez só. O que surge com o sistema aberto
aparece num aviso no canto e, se o Linux tiver bandeja de notificações, também
como notificação do sistema. Na lista, **Abrir** marca como lida e leva à tela
(Atrasados ou A vencer) já buscando o cliente. **Marcar todas como lidas** limpa
o contador. Cliente com cobrança suspensa não gera aviso, e as lidas há mais de
60 dias saem da lista. Nada é enviado ao cliente.

### Como a cobrança anda

As telas de cobrança têm o topo enxuto: busca, a ação principal (Cobrar
selecionados / Enviar lembrete) e o menu **Ações** (registrar pagamento, ficha,
cobrança em lote, renegociar, cancelar, exportar — com os atalhos de sempre).
Os filtros são chips ("Atraso: qualquer ▾", "Juros até: hoje ▾"…); o que sai do
padrão fica destacado e aparece **Limpar filtros**.

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
QR code do Pix e o CNPJ/CPF do cliente. Na prévia há duas datas: **Valores
atualizados em** (até quando o juros é calculado) e **Pagar até** (até quando
esse valor vale). Marcando **Guardar como acordo**, a oferta é registrada ao
copiar/salvar a imagem: pagando dentro do prazo, a baixa já sugere o valor
combinado (a diferença de juros entra como abono justificado); passado o prazo,
o acordo deixa de valer e o juros volta a correr desde o vencimento original.
O cartão do honorário mostra "Acordo até dd/mm" enquanto ele vale. **Copiar imagem** põe no clipboard para colar no WhatsApp;
**Copiar chave Pix** copia a chave para mandar como texto logo depois;
**Salvar PNG…** guarda o arquivo. Copiar não registra a cobrança.

O fundo é escolhido em **Configurações → Imagem da cobrança** (sem ele, vale o
modelo do sistema, que também pode ser salvo como ponto de partida). No SVG:

- textos com `{cliente}`, `{codigo}`, `{documento}`, `{tipo_documento}`,
  `{vencimento}`, `{data}`, `{total}`, `{total_original}`,
  `{total_juros}`, `{quantidade}`, `{recebedor}`, `{chave_pix}` viram os valores;
- um retângulo transparente com `id="lista"` recebe os honorários, um por linha,
  com o valor final cheio (o juros não aparece separado).
  Se não couberem, a imagem **estica**: a faixa logo acima do fim da lista é
  repetida e tudo o que está abaixo desce inteiro (até 30 linhas; dali em diante,
  "e mais N honorários"); `data-fonte`, `data-cor`,
  `data-cor-fraca` e `data-cor-linha` nesse retângulo mudam fonte e cores;
- um retângulo transparente com `id="qrcode"` recebe o PNG do QR code (270 px de lado
  ou mais, num fundo de 1080 de largura);
- **sem QR code anexado**, o grupo `id="mensagem-qrcode"` (o "aponte a câmera…")
  não aparece, e o que tiver `data-sem-qrcode="translate(x y)"` se move. No fundo
  da Métodos, o bloco "Pague com Pix" + chave vai para o lugar do QR, em vez de
  deixar um quadrado vazio. Com o QR anexado, tudo volta como desenhado.

- se o fundo tiver um logo só para a imagem (`id="logo-imagem"`) e outro só
  para os PDFs (`id="logo-pdf"`), cada saída usa o seu;
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
