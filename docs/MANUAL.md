# Manual de uso — Financeiro Métodos

Tela por tela, o que cada uma faz e como o trabalho de cobrança anda no sistema.
Para instalar e configurar, veja [INSTALACAO.md](INSTALACAO.md).

## Telas

| Tela | Para que serve |
|---|---|
| **Vencimentos → A vencer** (1ª aba) | Em aberto e dentro do prazo, pelo número da empresa (agrupada quando tem mais de um). Daqui sai o lembrete antes do vencimento |
| **Vencimentos → Atrasados** | A tela de trabalho da cobrança: só os vencidos e em aberto, pelo número da empresa (do menor para o maior; empresa com mais de um honorário fica agrupada, com o total), com cobrar, editar (valor, vencimento, descrição), **Confirmar pagamento** (botão verde em cada cartão em aberto, também em A vencer e Imposto de Renda), cobrança em lote e renegociação |
| **Vencimentos → Pagos** | Os quitados, **uma competência por vez** (◀ ▶ e o menu com as competências que têm pagos; abre na mais recente). O histórico completo de cada empresa fica na ficha dela. Mostra se pagou em dia ou com atraso, os juros cobrados e o abono |
| **Clientes de IR** | Cobrança própria dos clientes que só fazem IR com o escritório: em aberto (atrasados e a vencer) ou pagos, com filtro por ano do IR. Esses clientes não aparecem em Atrasados, A vencer e Pagos |
| **Tarefas** | O envio do honorário trimestral. O trimestre de cada empresa conta da competência em que ela virou cliente (campo **Cliente do escritório desde**), não do trimestre do ano: entrou em 15/08 → 08, 09 e 10; depois 11, 12 e 01… No dia seguinte ao fim do trimestre nasce a tarefa **Para fazer**, com **Dar baixa** (verde) quando o honorário for enviado. Também mostra os **Próximos trimestres**, as **Feitas** (com **Desfazer baixa**) e as trimestrais **Sem data de entrada**, com o botão para preencher. Só entram os trimestres dos últimos 12 meses; **Dar baixa em todas** serve para o começo, para os que já tinham sido enviados. O número no menu é o de pendentes |
| **Cobranças enviadas** | Cada mensagem enviada e o que o cliente respondeu, com período e agrupamento à escolha. É aqui que a resposta é anotada |
| **Clientes** | Abas **Ativos**, **Imposto de Renda** (quem só tem honorário de IR) e **Inativos**; PF \| PJ \| Todos e busca sem acento/pontuação; ficha completa da empresa. Dívida e atraso não aparecem aqui (têm telas próprias). Aqui também se suspende e retoma a cobrança de um cliente. O cadastro tem as abas **Dados**, **Contatos** e **Honorário recorrente**: no cliente novo, o honorário mensal (ou trimestral…) é cadastrado junto; quem tem "Paga pela empresa" salva sem honorário; sem honorário e sem empresa pagadora, o sistema pergunta antes (cliente só de IR ou de avulsos). No cliente já cadastrado, a aba lista os recorrentes dele, com novo, editar, reajustar e suspender |
| **Honorários** | A gestão dos honorários, em três abas (o recorrente se cadastra no cliente). **Mês a mês**: tudo o que foi emitido no mês (recorrente ou avulso), com ◀ ▶ e um menu para ir direto a qualquer mês, os totais (emitido, pago, em aberto, cancelados), filtros de origem e situação, e o aviso de contratos que ainda não geraram a competência — "Gerar competência" já abre no mês da tela. **Recorrentes**: contratos, reajuste (individual e em massa) e "Gerar competência MM/AAAA" com prévia. **Avulsos**: lançar, corrigir e cancelar serviços que não vêm de contrato (IRPF, alteração contratual, atas…) e consultar o histórico por período, pagos ou não, com a situação de cada um. A cobrança desses honorários fica em Atrasados e A vencer |
| **Painel** | O ano em números e gráficos: emitido × quitado por mês de competência (com a opção de ver em tabela), o que entrou no caixa por mês, de onde vem o faturamento (grupo e PF/PJ) e frases com o que os números dizem, comparando com o ano anterior quando há base. **Exportar PDF…** gera o relatório no mesmo visual da análise de juros (o papel do Financeiro, gráficos e tabela mês a mês). Atraso e devedores ficam no Ranking dos atrasados |
| **Ranking dos atrasados** | Pódio de quem mais deve em dinheiro, quem deve há mais tempo, quem junta mais boletos e quem mais foi cobrado — dois gráficos por aba; clicar num nome abre a ficha. A aba **Análise de juros** lista os clientes que pagaram e mostra, para cada um, original + juros = pago, o trabalho que deu para receber em gráfico (ele × a média dos clientes: atrasos, dias em atraso, cobranças, juros por cobrança), a linha do tempo do atraso de cada honorário com as cobranças feitas, um gráfico dos cenários, honorário por honorário, uma explicação em frases e cenários de taxa (+10% a dobrar, sem abono, valor testado) com o efeito de cada cenário honorário por honorário; **Exportar PDF…** gera o relatório da análise do cliente (documento interno) para compartilhar; o primeiro item é a visão geral de todos |
| **Relatórios e exportação** | Planilha Excel da lista filtrada e extrato de débitos em PDF |
| **Importar planilha** | Lê a planilha antiga, mostra prévia e relatório de erros, e só grava depois da confirmação |
| **Importação personalizada** | Importa qualquer planilha: para cada informação do cadastro (cliente, contato, vínculo e suspensão, contrato, honorário) se diz a letra da coluna do Excel. O layout é salvo e exportado como planilha-modelo. Cliente já cadastrado não é duplicado |
| **Tipos e formas de envio** | Aba **Grupos e tipos**: grupos à esquerda (a ordem é a das seções nas telas), tipos do grupo à direita, cada um mostrando a frase como sai na cobrança e quanto é usado. O cadastro do tipo mostra a prévia da mensagem enquanto se digita. Aba **Formas de envio**: cadastrar, renomear e ativar/desativar, com quantos contratos e honorários usam cada uma |
| **Configurações** | PIX, modelos de mensagem, imagem da cobrança, e-mail e backup |

A navegação é agrupada por momento do trabalho:

- **Cobrança**: **Vencimentos** (abas A vencer, Atrasados e Pagos, com a
  quantidade em aberto em cada aba; o número no menu é o de atrasados), Clientes
  de IR, Tarefas (com o número de pendentes), Cobranças enviadas e Gerenciador de e-mail (com o número de e-mails não lidos).
- **Cadastros**.
- **Gestão**.

Cada grupo tem a sua cor da logo (Cobrança em verde-água, Cadastros em
laranja, Gestão em azul-marinho). O nome do grupo fica numa faixa, e um fio da mesma cor
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

Os campos de **data** e de **valor** são de digitação livre. Data: `30/10/2026`,
`30102026`, `30/10/26`, `30-10` (o ano atual) ou `hoje` — as barras entram
sozinhas, e o calendário fica no botãozinho dentro do campo. Valor: `1.234,56`,
`1234,56`, `1234.56` ou `2`; o "R$" e os pontos aparecem ao sair do campo, e ao
entrar nele o número fica selecionado para digitar por cima. O que não faz
sentido (31/02, letra no valor) deixa o campo com borda vermelha e a explicação
ao passar o mouse; o valor anterior continua valendo até corrigir.

Onde se escolhe um cliente (contrato, honorário avulso, extrato, empresa que
paga), há um campo de busca: digite nome (sem se preocupar com acento), código
ou parte do CPF/CNPJ e aperte Enter. Com o código exato ou um resultado só, a
escolha é direta; senão abre a janela de busca, que filtra enquanto você digita.

O juros ao dia é um valor só por empresa e se muda no próprio cadastro (campo
**Valor por dia de atraso**) ou em **Alterar juros** no topo da ficha. O novo
valor vale para **tudo o que está em aberto** da empresa, inclusive os juros já
corridos; honorário já pago não muda. O valor anterior fica no log de alterações.

No cadastro, **Cliente do escritório desde** (opcional) é a data em que a empresa
virou cliente. Para quem tem honorário trimestral, é dela que conta o trimestre
na tela **Tarefas**.

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

### Importação personalizada

Para trazer dados de uma planilha que não é a antiga. Na aba **Colunas do
layout** estão todas as informações que o sistema cadastra, em grupos (Cliente,
Contato, Vínculo e suspensão, Contrato e Honorário). Na frente de cada uma:

- **Coluna**: a letra do Excel onde ela está (A, B… AA);
- **Valor fixo**: usado quando a célula vem vazia, ou quando a informação não
  está na planilha — por exemplo, o tipo de honorário igual para todas as linhas.

O que fica em branco não é importado. Também se informa a **aba** (vazio, a
primeira) e a **linha onde começam os dados**. **Salvar layout** guarda tudo com
um nome, para usar de novo. **Exportar modelo…** gera uma planilha com o título de
cada informação na coluna certa, uma aba **Instruções** dizendo o que cada uma
aceita e o layout escondido — **Abrir de um modelo…** traz o layout de volta a
partir dessa planilha.

**Escolher planilha…** lê o arquivo e mostra a **Prévia**, sem gravar nada. Para
cada linha ela diz o que vai acontecer com o cliente, o contrato e o honorário.
A conferência com o cadastro segue estas regras:

- O cliente é reconhecido pelo **CPF/CNPJ**, depois pelo **código** e, sem
  nenhum dos dois, pelo **nome** (sem diferença de acento e maiúscula). PF ou PJ,
  quem já está cadastrado **não é cadastrado de novo**: recebe só o que a
  planilha traz de diferente (nome, CPF/CNPJ que faltava, juros por dia — que passa
  a valer para tudo em aberto —, data de entrada no escritório, contato novo,
  observações acrescentadas,
  empresa que paga, suspensão da cobrança). O código do cadastro é mantido.
- Código que já é de outro CPF/CNPJ trava a linha, para não misturar clientes.
- O mesmo cliente pode aparecer em várias linhas (uma por honorário).
- **Contrato**: criado quando a linha traz tipo e valor. Se o cliente já tem
  contrato desse tipo, ele é atualizado; valor diferente vira **reajuste**, com
  histórico.
- **Honorário**: lançado quando a linha traz tipo, valor e vencimento. O que já
  existe (mesma competência, ou mesmo vencimento e valor no avulso) e o que se
  repete na planilha não entram de novo. Status Pago entra quitado, com o valor
  congelado e a data de "Pago em".

Desmarcando **Atualizar dados de clientes já cadastrados**, quem já existe fica
como está e só entram clientes novos, contratos novos e honorários. Linha com
erro não pode ser marcada; os avisos e erros ficam no **Relatório de erros e
ajustes**. **Importar marcados** grava depois da confirmação.

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

O sistema abre com a tela de carregamento: um cartão em forma de canhoto, com a
marca do Financeiro Métodos no corpo azul e, depois do picote, o canhoto ciano
com a etapa que está carregando, a porcentagem e a barra. A logo fica depois no pé do menu lateral. Não aparece nenhum cartão de resumo ao
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
quem está em aberto, e quem cobra responde com o andamento. A tela **Gerenciador de e-mail** é uma caixa de e-mail só dessa conversa.

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
    enviar.
    **Enviar resposta** pede confirmação e envia pela sua conta, na
    mesma conversa, com o e-mail do financeiro citado embaixo. Também há
    **Copiar** e **Salvar rascunho**.
- **Montar resposta** (no cabeçalho do e-mail aberto, em destaque) refaz a
  resposta com o que está no sistema agora, com as baixas e os retornos anotados,
  e abre a aba. Se você já tinha escrito no texto, o sistema pergunta antes.
- **Novo e-mail pelo sistema** (no topo) monta um e-mail novo com os vencidos de
  hoje e as anotações das cobranças, para quando não há e-mail do financeiro para
  responder. Ele já vem endereçado ao e-mail do financeiro das Configurações, ou
  a quem mandou o último e-mail da conversa, e é enviado daqui.
- Sem conta configurada, o menu **Ações** abre um e-mail de arquivo (.eml, PDF
  impresso do Outlook, .txt) ou aceita o texto colado.

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

*Assinatura:* em **Assinatura (imagem)**, **Escolher imagem…** põe a imagem
(PNG, JPG…) no fim do que o sistema envia ao financeiro pelo **Enviar**. Ela
fica no banco e vale em qualquer computador, e dá para salvá-la antes de
configurar a conta. Imagens grandes são reduzidas (até 600 × 200 px); se mesmo
assim passarem de 300 KB, o sistema pede outra. Na aba Responder, desmarcar a
caixa **Assinatura** tira a imagem só daquele envio: no próximo e-mail ela volta
marcada. **Copiar** e **Salvar rascunho** saem sem a imagem, porque o Outlook
já põe a sua própria assinatura.

A senha de app e a autorização da Microsoft ficam no **cofre de senhas do
sistema** (Gerenciador de Credenciais no Windows), nunca no banco. A
autorização da Microsoft é grande para uma credencial só do Windows, por isso
aparece lá dividida em algumas entradas `honorarios-email`. Se o cofre recusar,
a conta funciona até fechar o programa, com um aviso de que será preciso entrar
de novo. Os e-mails
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
2. A tela **Cobrar** monta a mensagem e a imagem (veja abaixo); você copia ou abre
   o WhatsApp e clica em **Marcar como cobrado**. A cobrança nasce *aguardando resposta* — nada de
   resposta é pedido nesse momento, porque ela ainda não existe.
3. Quando o cliente responde, a resposta entra em **Cobranças enviadas** (ou pelo
   botão Histórico do próprio honorário): prometeu pagar, pediu renegociação,
   contestou, não respondeu.
4. O **Histórico** de cada honorário mostra a linha do tempo completa e diz
   quando a cobrança saiu em lote e com quais outros honorários.

### A tela Cobrar

Tudo numa tela só, em passos numerados — à esquerda, o que se cobra (a lista e a
conferência da conta); à direita, as datas e o que vai para o cliente. A janela se
ajusta à tela: num notebook, as frases de ajuda dos passos ficam no título (passe o
mouse) e a coluna "Venceu em" sai da lista (o vencimento continua na conferência),
para o total ficar sempre à vista. No alto, à direita, a soma de sempre à vista:
**valor + juros = total a cobrar**.

1. **Quais honorários vão na cobrança** — marque e desmarque. A lista mostra o
   vencimento, os dias de atraso, o valor, os juros e o total de cada um.
2. **Conferência dos juros** — a conta de cada honorário marcado, por extenso:
   "50 dias × R$ 1,01 por dia = R$ 50,50" e "R$ 1.507,80 + R$ 50,50 de juros =
   R$ 1.558,30" (com troca de juros por dia ou pagamento parcial, a conta mostra
   cada parte). Para cobrar **outro valor de juros**, clique no honorário na lista
   e digite em "Juros a cobrar…"; ele fica marcado com ✎ e a conferência mostra o
   que o cálculo dava. **Usar o calculado** desfaz. O juros digitado vale
   para a mensagem, a imagem, o acordo e o registro da cobrança — só nesta
   cobrança; nada muda no cadastro.
3. **Datas**
   - **Valores atualizados até**: **Hoje** (o padrão) ou **Outra data**. Os juros
     vão até essa data.
   - **Vencimento (pagar até)**: o prazo para pagar que aparece na imagem e no
     lembrete. **Não aumenta os juros.** Sozinho, ele é a data dos valores — ou,
     quando nada marcado está atrasado, o vencimento do próprio honorário (a
     competência que vence no mês seguinte, por exemplo). Dá para escolher outro;
     **Voltar ao automático** volta ao padrão.
4. **Mensagem e imagem** — para quem vai, o **tipo de mensagem** (**Cobrança**,
   para o que está em atraso, ou **Lembrete**, para o que ainda está no prazo — o
   sistema escolhe sozinho e dá para trocar) e as abas **Mensagem de texto** (dá
   para editar antes de copiar) e **Imagem**, com a prévia já com as datas e os
   valores da tela, para conferir antes de copiar.

Na imagem, **Guardar como acordo** congela os valores: pagando até o vencimento,
a baixa já sugere esse total (a diferença de juros entra como abono justificado);
passado o vencimento, o acordo deixa de valer e os juros voltam a correr desde o
vencimento original. O acordo é registrado ao copiar ou salvar a imagem, e o
cartão do honorário mostra "Acordo até dd/mm" enquanto ele vale.

Cada aba tem os seus botões: na **Mensagem de texto**, **Copiar mensagem** e
**Abrir no WhatsApp**; na **Imagem**, **Copiar imagem** (para colar no WhatsApp com
Ctrl+V), **Copiar chave Pix** (para mandar como texto logo depois da imagem: o
cliente toca e copia) e **Salvar imagem…**. Embaixo fica só **Marcar como
cobrado**. Copiar não registra a cobrança.

### Imagem da cobrança

A imagem já sai pronta, sem precisar importar nada: o modelo do sistema tem a
identidade do Financeiro (o canhoto — faixa navy com a marca no topo, o cartão
com o cliente, a lista e o total, e depois do picote o canhoto ciano com o QR do
Pix do escritório e a chave), com a logo da Métodos no pé. O mesmo fundo vale
para a cobrança e para o lembrete; o **Pagamento confirmado** é um comprovante
com a marca do Financeiro, sobre o mesmo fundo.

Ao abrir a versão com a identidade nova pela primeira vez, a imagem passa para
esse modelo; um fundo seu escolhido antes continua guardado e volta com
**Voltar para o meu fundo**. Outro fundo pode ser escolhido em
**Configurações → Imagem da cobrança** (o modelo também pode ser salvo como
ponto de partida). No SVG:

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
- **sem QR code**, os grupos `id="mensagem-qrcode"` (o "aponte a câmera…") e
  `id="quadro-qrcode"` (a moldura branca dele) não aparecem, e o que tiver
  `data-sem-qrcode="translate(x y)"` se move: no modelo, o bloco "Pague com Pix"
  + chave vai para o lugar do QR, em vez de deixar um quadrado vazio. Com o QR,
  tudo volta como desenhado.

- se o fundo tiver dois logos (`id="logo-imagem"` e `id="logo-pdf"`), a imagem
  usa o `logo-pdf`; o `logo-imagem` só aparece quando é o único do fundo;
- a camada da cobrança (textos, lista, QR) fica num grupo `<g id="conteudo">`.

Os PDFs (painel, análise de juros, extrato) não usam esse fundo: saem no papel
do Financeiro, com a faixa navy, o picote e o canhoto ciano.

O QR code do Pix do escritório (Métodos Serviços Contábeis, gerado no app do
banco) **já vem no sistema**. É o QR da chave, sem valor — o cliente digita o
valor ao pagar. Para trocar, salve o novo QR como PNG no app do banco e escolha
em **Configurações → Imagem da cobrança → Escolher PNG do QR code…**; **Usar o
do escritório** volta ao que vem no sistema, e **Sair sem QR** tira o QR da
imagem (a prévia avisa).
