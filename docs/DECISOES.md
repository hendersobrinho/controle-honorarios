# Decisões de projeto

Registro do que foi decidido e por quê, para não ser reaberto sem motivo.

## Regras de negócio

### Juros por dia é fixo por cliente, não derivado do valor
A planilha calcula, na prática, `juros/dia ≈ valor do boleto × 0,0667%`
(2% ao mês ÷ 30): a mediana é 0,0666% na aba principal e 0,0667% na de IRPF, e
194 de 206 linhas caem em ±0,005 p.p. disso. Mesmo assim, **o sistema usa um
valor fixo por cliente**, com histórico de vigência, conforme decidido em
29/09/2026. As 12 linhas em que o juros ficou desatualizado em relação ao valor
(5 clientes) entram no relatório de importação como
aviso, para correção manual.

### Dias anteriores à primeira vigência usam a primeira taxa
O histórico de juros diz de quando em diante cada valor vale. Para os dias
**anteriores** à vigência mais antiga, vale essa mesma taxa mais antiga. Sem
isso, um cliente cadastrado hoje com honorário vencido há dois meses teria juros
zero. Alterações posteriores continuam valendo só para frente.

### Pagamento parcial reduz o juros na proporção do saldo
Ao registrar um pagamento parcial, o juros devido até aquela data é congelado no
pagamento e, do dia seguinte em diante, o juros/dia passa a valer na proporção
`saldo / valor original`. Exemplo: boleto de 1.000 com 0,67/dia; pagando 600 de
principal em 10/09, o saldo de 400 corre a 0,268/dia.

O juros já cobrado (ou abonado) em pagamentos anteriores é abatido do total
calculado, para o mesmo período não ser cobrado duas vezes.

### Pagamento parcial não cria status novo
O honorário continua `Em aberto` com `saldo_aberto` menor. Um status "parcial"
faria o honorário sumir das telas de cobrança, que é justamente onde ele precisa
continuar aparecendo.

### Arredondamento só no total
`ROUND(Σ dias × taxa, 2)`, meio-para-cima, como a planilha. Arredondar por
segmento de vigência mudaria o resultado em taxas de fração de centavo.

### "Pago direto para Eloisa" e "Enviado para Cliente"
Não são status de pagamento. O primeiro é **forma de pagamento**
(`FormaPagamento.DIRETO_ELOISA`, com o honorário em `Pago`); o segundo é
**situação de envio** (`SituacaoEnvio.ENVIADO`), num eixo separado do status.
A planilha usava o primeiro na coluna *Forma dos Honorários* e nunca usou o
segundo.

### IRPF
Competência modelada como `competencia_ano` + `competencia_mes` anulável. O tipo
declara se exige mês, só ano ou nada (`ExigeCompetencia`), e o rótulo
(`08/2026`, `IRPF 2026`, `Ata de Sócios`) é derivado. A aba separada de IRPF
deixa de existir: tudo fica na ficha do cliente, e a cobrança geral separa por
grupo.

### Link do WhatsApp: `wa.me`
Não existe app oficial de WhatsApp para Linux, então `whatsapp://send` não tem
handler registrado no Zorin/Wayland e `QDesktopServices.openUrl` falharia em
silêncio. `https://wa.me/55DDDNUMERO?text=…` abre no navegador padrão e cai no
WhatsApp Web já autenticado. O formato é configurável (`wa.me`,
`api.whatsapp.com`, `whatsapp://`).

### Copiar não registra cobrança
O registro acontece só em "Marcar como cobrado", porque copiar a mensagem e não
enviar é situação comum.

### A resposta do cliente não é anotada na hora de cobrar
Quando a mensagem sai, ainda não existe resposta — pedir o resultado ali é
contraditório e polui a tela. Toda cobrança nasce com resultado
`AGUARDANDO` ("Aguardando resposta"), e o retorno é anotado depois, na tela
**Cobranças enviadas** ou pelo Histórico do honorário.

A unidade de acompanhamento é a **mensagem enviada** (o lote), não cada
honorário: foi uma conversa só com a empresa, e a resposta vale para todos os
honorários que estavam nela.

### Uma tela por situação: atrasados, a vencer e pagos
A antiga "Cobrança geral" tinha uma alternância Pendentes | Pagos | Todos e
filtros que valiam para uma situação e não para outra (faixa de atraso não faz
sentido em pagos; período não faz sentido em pendentes). Virou três telas, cada
uma com só o que importa para ela:

* **Atrasados** — seções por faixa de atraso, da dívida mais antiga para a mais
  recente; cobrar, cobrança em lote, renegociar e simular data.
* **A vencer** — seções por proximidade do vencimento (hoje, próximos dias, mais
  adiante); o botão principal é o lembrete.
* **Pagos** — seções por mês do pagamento, com período; cartão próprio que diz
  se pagou em dia ou com atraso, com juros cobrados e abono.

O critério é o vencimento, e a data é a de referência do cálculo — a mesma que
decide os juros —, não o relógio do sistema. Honorário atrasado com promessa de
pagamento continua em Atrasados: a promessa aparece no cartão, e o que ela pede
de ação está em Cobranças enviadas.

### Lista em cartões, não em tabela, nas telas de cobrança
Atrasados, A vencer, Pagos e Cobranças enviadas mostram cada registro como um
cartão com faixa colorida à esquerda (vermelho em atraso, âmbar pedindo atenção,
verde resolvido) e os botões daquele registro no próprio cartão. Tabela continua
onde a leitura é comparativa (Clientes, Contratos, Painel, Importação).

Desempenho, que a tabela resolvia com o modelo, aqui se resolve em três camadas:

1. **Recorte na consulta.** O histórico de pagos tem um seletor de período
   (padrão: últimos 3 meses). O que está fora nem é lido do banco nem calculado.
   Os pendentes continuam vindo por inteiro de propósito: esconder dívida antiga
   por causa de um filtro de tela seria pior que a lentidão.
2. **Cartão construído sob demanda.** A seção guarda os itens de domínio e a
   função que monta o cartão; formatar moeda e data só acontece para o que vai
   ser desenhado.
3. **Orçamento de widgets.** São desenhados no máximo 90 cartões por vez, 30 por
   seção, com "mostrar mais" onde falta. Com 220 pagos na tela, isso é 38 widgets
   em vez de 220.

Honorário importado da planilha antiga não tem data de pagamento (ela não existia
lá), então o recorte de período usa o vencimento nesses casos, e o rótulo do mês
avisa: "(sem data de pagamento, pelo vencimento)".

### Suspender cobrança não suspende a dívida
A suspensão marca o cliente (cartão cinza, etiqueta própria) e faz o sistema recusar o
registro de cobrança dele. Os honorários continuam em aberto e o juros continua
correndo: quem suspende quer parar de cobrar, não perdoar. Para perdoar existe
cancelar ou renegociar.

A suspensão aceita data de retomada; sem data, vale até ser retomada na mão.
Na cobrança geral o honorário continua aparecendo, em cinza e com a etiqueta
"Cobrança suspensa" — esconder a dívida seria pior que mostrá-la parada.

### Vínculo de pessoa física com a empresa que paga
`Cliente.empresa_id` aponta da pessoa física para a empresa que costuma pagar os
honorários dela. O vínculo:

* tem um nível só (a empresa não pode estar vinculada a outra);
* não transfere o honorário, que continua pertencendo à pessoa e aparecendo na
  ficha dela;
* é opcional na hora de cobrar: a tela de Cobrar da empresa oferece incluir os
  honorários das pessoas vinculadas.

Quando a mensagem mistura titulares, ela usa obrigatoriamente o modelo de lista
e cada linha começa com o nome de quem deve — cobrar "o honorário de agosto" de
alguém que não o reconhece é o caminho mais curto para uma discussão.

### Clientes só de Imposto de Renda têm tela própria
É cliente só de IR quem tem honorário (não cancelado) e todos eles são de tipos
do grupo marcado como Imposto de Renda, sem contrato recorrente ativo de outro
tipo. Quem tem mensal e IR continua sendo cliente comum.

A regra é calculada, não um campo do cadastro: não há o que esquecer de marcar e
não sai de sincronia. E segue a **marcação do grupo** (`imposto_de_renda`), não
o nome — renomear o grupo não quebra nada. Só um grupo pode ter a marcação.

Esses clientes saem de Atrasados, A vencer e Pagos e aparecem na tela Imposto de
Renda, que alterna em aberto e pagos (nunca misturados) e filtra pelo ano do IR.

### Grupos e tipos numa tela própria
Era uma aba escondida em Configurações, com grupos criados por uma caixinha de
texto e sem lista. Virou tela em Cadastros: grupos à esquerda, na ordem das
seções, com subir/descer; tipos do grupo à direita em cartões que mostram a
frase como sai na cobrança e quantos honorários e contratos usam o tipo. O
cadastro do tipo explica quando cada um dos três textos é usado, mostra a prévia
enquanto se digita e insere as variáveis por botão.

### Sem Fila do dia e Fila de envio
As duas telas saíram a pedido (30/09/2026): repetiam o que Atrasados já mostra e
não ficava claro para que serviam. O que tinham de útil foi para outro lugar —
a promessa vencida aparece no cartão e em Cobranças enviadas, e a cobrança de
várias empresas em sequência (o antigo assistente) é disparada selecionando
honorários de mais de uma empresa em Atrasados.

### "Acompanhamento" virou "Cobranças enviadas"
O nome antigo não dizia o que a tela mostra. O novo diz: são as cobranças que
já saíram, e é ali que se anota o que o cliente respondeu.

### Escolha de cliente por busca, não por lista suspensa
Com centenas de clientes, a lista suspensa ficava impraticável. O seletor usa
uma busca leve (sem calcular dívida) por nome sem acento, código ou parte do
CPF/CNPJ; código exato ou resultado único escolhem direto, sem abrir janela.

### Rankings desenhados à mão
Os quatro rankings (valor, tempo, quantidade de boletos, tentativas de cobrança)
são pintados com QPainter e não com QtCharts: medalhas de pódio, coroa no
primeiro lugar, barras que crescem ao abrir a aba e uma curiosidade por gráfico.
Cada mensagem enviada conta uma tentativa — uma mensagem com três honorários é
uma tentativa, não três.

### Datas em destaque nos cartões
Vencimento, pagamento, última cobrança e promessa aparecem como pílulas (só
texto, sem ícone) no topo do cartão, tingidas com a cor da situação quando pedem atenção (atrasado, vence
em breve, promessa vencida). A etiqueta de situação não repete a data que já
está na pílula.

### Análise de juros
A aba "Análise de juros" (em Ranking dos atrasados) existe para uma decisão: aumentar ou não
o juros. Por isso ela não mostra só quanto entrou, mas também:

- **juros devido × cobrado × abonado**: se boa parte é abonada na baixa,
  aumentar a taxa não aumenta a receita. Com abono a partir de 25% do devido, a
  tela sugere olhar os abonos antes;
- **juros efetivo ao mês**: juros recebido ÷ (original atrasado × meses de
  atraso), ao lado do que a taxa cadastrada daria sem abono. Serve para comparar
  com uma taxa de mercado, já que o juros do cliente é um valor fixo por dia;
- **simulação**: com +X% e o mesmo comportamento do período, quanto teria
  entrado, e quanto os honorários atrasados de hoje renderiam a mais por mês.
  A simulação só olha para frente, igual à regra da taxa: mudança de juros
  nunca é retroativa.

A análise é **por cliente**: à esquerda ficam os clientes que pagaram no período
(quem paga entra na lista) e, ao escolher um, a tela mostra original + juros =
pago, cada honorário quitado com suas datas, uma explicação em frases e os
cenários com o juros ao dia dele (+10%, +25%, +50%, dobrar, sem abono e um valor
testado à mão). A frase "Leitura:" no fim da explicação é uma observação sobre o
comportamento do cliente (atrasa com frequência, dá mais trabalho que a média,
paga em dia, abono alto) — a decisão continua sendo de quem usa a tela. A visão
geral de todos fica no primeiro item da lista.

A análise também mostra **o trabalho que o cliente deu para pagar**: quantos
honorários pagou com atraso, os dias de atraso somados (média e maior), quantas
cobranças foram feitas até o pagamento, quanto de juros entrou por cobrança e o
que ele tem atrasado hoje. Cada número do cliente vem comparado com a média dos
clientes. As cobranças contam como no ranking "mais cobrados": cada mensagem é
uma tentativa, mesmo com vários honorários dentro.

Clicando num cenário, a seção **Cenário honorário por honorário** aplica aquele
cenário a cada honorário: para os pagos, o juros pago contra o juros no cenário
(mesmo atraso, mesma proporção de abono), a diferença e o total; para os que
estão em atraso hoje, o juros por dia hoje → no cenário e o total se ele pagar
daqui a 30 dias. O juros que já correu não muda, porque a taxa nova só valeria
da data da mudança. O cenário da tabela geral é a soma desses honorários (cada
um arredondado), para os números das duas tabelas baterem.

Entram só honorários quitados com `Pagamento` registrado: os pagos importados da
planilha não têm valor nem data de pagamento e ficariam como "pagou exatamente
o original", puxando a análise para baixo. A tela lembra de conferir o contrato
de cada cliente antes de mudar a taxa.

### PDF da análise de juros
O botão **Exportar PDF…** da análise de um cliente gera o relatório com o
mesmo conteúdo da tela, inclusive o cenário escolhido na tabela (que aparece
destacado e detalhado honorário por honorário). Os textos dos indicadores vêm
do serviço, não da tela, para a tela e o PDF mostrarem o mesmo número. O PDF é
marcado como **documento interno** no rodapé: a "Leitura" do comportamento do
cliente não é texto para mandar a ele.

O PDF sai no papel do Financeiro (ver "Um molde para os PDFs"). Os blocos do relatório são mantidos
inteiros na página (título, tabela e nota juntos), sem `KeepTogether` dentro de
`KeepTogether`: aninhado, o reportlab calcula a altura errado e pula página.

### Painel sem atraso, com gráficos
O Painel mostra o ano: emitido e quitado por competência, o caixa pela data da
baixa e a origem do faturamento. Faixas de atraso, maiores devedores, juros
acumulado e inadimplência saíram — repetiam o Ranking dos atrasados. "Quitado"
conta o valor original (parcial conta o que já foi abatido), para quitado +
em aberto somar exatamente o emitido. A comparação com o ano anterior só
aparece com dado em pelo menos metade dos meses do período: um honorário solto
no ano anterior dava "19000% a mais".

Os gráficos seguem regras fixas: uma escala por gráfico, empilhado só para parte
do todo, legenda com duas séries ou mais, número escrito só onde ajuda e o mesmo
dado em tabela. As cores (azul e laranja, e verde-água para a composição) foram
validadas para daltonismo e contraste no fundo claro e no escuro.

### Avulsos: lançar e consultar, não cobrar
A tela de Honorários avulsos era uma segunda fila de cobrança (com Cobrar e
Registrar pagamento) para honorários que já estão em Atrasados e A vencer. Virou
o lugar de lançar, corrigir, cancelar e consultar o histórico dos avulsos por
período, pagos ou não, como a aba Recorrentes é o lugar dos contratos. As duas
ficam no mesmo item do menu, **Honorários**, em abas — como Clientes separa
ativos, IR e inativos.
Para corrigir sem trocar de tela, os cartões em aberto da cobrança ganharam
**Editar** (honorário pago continua não editável: estorne antes).

### Um molde para os PDFs
Os PDFs (análise de juros, painel e extrato de débitos) usam o mesmo molde
(`servicos/pdf_relatorio.py`): a página é um canhoto, como a abertura — faixa
navy no topo com o título e a marca do Financeiro, o picote com os furos nas
laterais e o canhoto ciano no pé com o rodapé —, os estilos, a tabela de
cabeçalho cinza e a grade de indicadores. Antes o papel era o fundo da imagem de
cobrança renderizado a ~200 dpi; agora é tudo vetor, desenhado no próprio PDF. A
marca vem do `marca_negativo.svg` por um conversor pequeno
(`servicos/svg_pdf.py`, só os comandos que os SVGs da marca usam), para os
serviços continuarem sem Qt. Os gráficos
do painel vão para o PDF como imagem, desenhados pela interface sempre no tema
claro (o PDF é branco) e em dobro de resolução.

### A imagem de cobrança já vem pronta
O modelo do sistema (`recursos/fundo_cobranca.svg`) tem a identidade do
Financeiro — o canhoto da abertura — e o QR do Pix do escritório vem junto
(`recursos/qrcode_pix.png`), para a imagem sair certa sem importar nada. O QR é
o PNG que o banco gerou, só recortado e com os módulos redesenhados nítidos
(conferido: lê o mesmo conteúdo do original); o sistema não gera QR de Pix. Na
configuração, vazio quer dizer "o do escritório" e `nenhum` quer dizer sem QR.
Ao abrir a versão nova uma vez (`identidade_visual_v1`), a imagem volta ao
modelo; o fundo escolhido antes fica guardado para "Voltar para o meu fundo". A
logo da Métodos continua no pé (quem cobra é o escritório) e ganhou arquivo
próprio, `recursos/metodos.svg`; a logo antiga do Financeiro (`logo.svg`) saiu.

### Os juros vão até a data dos valores, nunca até o "pagar até"
Na 1.0.1 a imagem passou a calcular os juros até o "pagar até": com o prazo dez
dias à frente, a imagem já cobrava dez dias de juros que não tinham corrido — as
duplicatas saíam maiores que a conta do sistema. Agora são duas datas separadas na
tela Cobrar: **valores atualizados até** (hoje, ou outra data escolhida) é até onde
vão os juros; **vencimento (pagar até)** é só o prazo, na imagem e no lembrete.
A conta de cada honorário fica à vista ("dias × juros por dia = juros") e o juros
pode ser digitado à mão, só para aquela cobrança: o total, a imagem, o acordo e o
registro usam o digitado, e a conferência mostra o que o cálculo dava. A fórmula
em si (`juros_dia × dias`, por faixa de vigência) foi conferida contra os 20
honorários em aberto do banco de desenvolvimento e bateu em todos.

### Acordo de valor ("pague R$ X até tal data")
A imagem separa a data dos valores ("atualizados até") do prazo ("pagar até").
Guardado como acordo (tabela `acordo_valor`, um por honorário), o valor congelado
vale para pagamentos até o prazo: a prévia da baixa sugere o juros combinado e o
texto do abono. Nada é alterado no honorário — passado o prazo, o acordo só deixa
de ser considerado e o juros corre desde o vencimento original, "retroativo". Um
pagamento parcial no meio muda o saldo e invalida o acordo, porque a conta dele
partia do saldo antigo.

### Imagem da cobrança com fundo SVG
O fundo é um SVG feito fora do sistema e desenhado em vetor na largura final
(1080 px), então não perde qualidade. O sistema não posiciona nada por
coordenada própria: textos `{campo}` são trocados no SVG, e a lista e o QR são
desenhados dentro dos retângulos `lista` e `qrcode` que o próprio desenho
define — trocar o layout é só trocar o arquivo. O SVG escolhido é copiado para a
pasta de dados, para não depender de onde o original estava.

A imagem segue a seleção do diálogo Cobrar, igual à mensagem. O QR code é o PNG
da chave Pix gerado no app do banco e escolhido nas Configurações (o sistema
guarda uma cópia na pasta de dados). Chegou a existir um QR gerado pelo próprio
sistema, com o valor da cobrança (BR Code); foi retirado por decisão do
usuário, que prefere o QR oficial do banco. O PNG é ampliado sem suavização,
para a borda dos quadradinhos não borrar e o QR continuar legível.

Com muitos honorários selecionados, a imagem estica em vez de virar duas: a
faixa de 1 px logo acima do fim da lista é repetida e o que está abaixo (total,
QR, logo) desce inteiro. Uma imagem só é mais fácil de copiar e mandar que
"1 de 2, 2 de 2". O fundo precisa ter, nessa altura, algo que aguente ser
repetido (cor lisa, cartão, faixa lateral) — degradê vertical ali ficaria
esticado. Até 30 linhas; acima disso, "e mais N".

### Notificações guardadas no banco

Cada notificação tem uma `chave` única que identifica o fato (ex.:
`nao_pago:{cliente}:{vencimento}`), então verificar de novo nunca duplica, e o
que foi lido continua lido depois de fechar o sistema. Os avisos são por cliente
(e por dia de vencimento), não por honorário, para a lista não virar uma fila.
"Não pago na data" olha os últimos 30 dias, para pegar o que venceu num feriado
com o sistema fechado. Ao abrir, só o contador muda: o aviso do canto e a
notificação do sistema aparecem para o que surge depois. O cartão de resumo que
aparecia ao abrir foi retirado, porque mais atrapalhava do que ajudava.
A verificação usa a data de hoje, não a data de referência da tela.

### Agradecimento diferente da cobrança

A imagem de agradecimento usava o mesmo cartão e a mesma faixa azul do total da
cobrança e dava para confundir as duas. Agora ela é um cartão branco de
comprovante: a logo no topo em fundo branco, sem trocar nenhuma cor dela; o selo
azul-marinho com "✓" laranja e o valor num painel verde-água claro; a lista num
canhoto picotado. O verde comum e a faixa verde-água forte foram descartados: o
primeiro não é cor da empresa, e a segunda obrigava a recolorir a logo. Ela sai
em 1620 px de largura (1,5× a cobrança), porque o desenho é todo vetor.

### Geração automática: uma vez por competência

Desligada por padrão. Quando ligada, ela roda a partir do dia escolhido e só uma
vez por mês (fica gravado em `geracao_automatica_ultima`). Honorário cancelado
não conta como "já lançado" na geração. Por isso, rodando toda hora, o que foi
cancelado à mão voltaria. Pelo mesmo motivo, contrato com honorário cancelado na
competência fica de fora mesmo quando a geração é ligada no meio do mês.

### E-mail de cobranças: a lista é do financeiro, o andamento é do sistema

Quem decide quem está em aberto é o financeiro: o e-mail dele é a fonte da
lista. O sistema confere essa lista com os honorários vencidos e responde com
o andamento das cobranças. A resposta usa a lista dele, sem quem saiu, e soma
as anotações do e-mail às do sistema, sem repetir. A comparação é por texto
normalizado.

A linha do e-mail é casada pelo código do cliente, quando vem. Sem código, vale
o vencimento mais o nome, e a abreviação conta como começo das palavras do nome
cadastrado. Linha com colunas separadas (tabulação ou 2+ espaços) é lida por
coluna, para a competência com espaços não grudar no nome. "Saiu da lista" só
vale para o que venceu antes da data do e-mail, e ninguém é baixado
automaticamente: o valor e a data do pagamento não estão no e-mail.

O sistema não envia o e-mail: copia com a formatação, para colar em Responder
a todos, ou salva um `.eml` com `In-Reply-To`/`References` (mesma conversa) e
`X-Unsent: 1` (o Outlook abre como rascunho).

### Caixa de e-mail: uma pasta, um assunto, nada além

O sistema lê uma pasta só (que a regra do Outlook ou o filtro do Gmail
preenche) e, dela, só os e-mails com o assunto da conversa, sem "RE:"/"ENC:" e
sem acento. No IMAP a leitura é `readonly` com `BODY.PEEK`, então nada é
marcado como lido na caixa. A autorização dá acesso técnico à caixa inteira;
quem limita é a pasta.

- **Microsoft 365 pelo Graph, com código de dispositivo.** A Microsoft não
  aceita mais usuário e senha (IMAP/SMTP básico). O fluxo de código não precisa
  de servidor nem de segredo do aplicativo, só do ID dele. As permissões são as
  mínimas: `Mail.Read` e `Mail.Send`. A resposta usa `replyAll` com o corpo e
  os destinatários editados, e não precisa de `Mail.ReadWrite`.
- **Gmail e outros por IMAP/SMTP com senha de app.** O nome da pasta vai no
  "UTF-7 modificado" do IMAP ("Cobranças" → `Cobran&AOc-as`).
- **Segredos no cofre do sistema (`keyring`).** Senha e autorização renovável
  ficam no cofre, nunca no banco nem em arquivo. Nos testes, um cofre em
  memória substitui o real.
- **Segredo grande vai em pedaços.** O Gerenciador de Credenciais do Windows
  aceita até 2.560 bytes por credencial e o `keyring` grava em UTF-16; a
  autorização renovável da Microsoft passa disso e o `CredWrite` recusava
  (erro 1783). Acima de 1.000 caracteres, o segredo vai em pedaços
  (`nome#1`, `nome#2`…) e a entrada principal guarda só quantos são. Se o cofre
  recusar mesmo assim, a entrada na conta não se perde: a autorização vale
  enquanto o programa estiver aberto, com aviso de que será preciso entrar de
  novo depois.
- **Rede em segundo plano.** Verificar e enviar rodam no `QThreadPool`, sem
  tocar na sessão do banco. O resultado volta por sinal, e é na tela que se
  grava.
- **Enviar sempre pede confirmação.** A resposta enviada é guardada na
  conversa, e o e-mail original fica como "respondido".

### Baixa dos que saíram da lista: prévia, não automática

Quem sai da lista do financeiro provavelmente pagou, mas o e-mail não diz
quando nem quanto. Por isso a baixa nunca é automática. Uma janela abre ao lado
(não modal, para conferir no e-mail), com tudo marcado e editável:

- data do pagamento: padrão é a data do e-mail, que é o limite de quando foi
  pago;
- valor: com juros até a data (padrão, igual à tela de pagamento) ou só o
  original, com abono justificado "saiu da lista do financeiro de dd/mm";
- forma de pagamento: padrão Boleto.

A baixa só acontece com a confirmação. Um honorário que veio no e-mail mas já
está pago no sistema (baixa depois do e-mail) é reconhecido e fica fora da
resposta.

### Comprovante sem data de pagamento

O dia exato em que o dinheiro entrou nem sempre se sabe. Por isso o comprovante
não mostra a data do pagamento, e cada linha traz o vencimento do honorário.

### Mais leve: telas montadas quando abertas e sem reler à toa

Medido com cerca de mil honorários em aberto:

- Abrir o sistema levava 2,0 s porque montava as 14 telas, e cada uma lia e
  calculava os seus dados. Agora só a primeira tela e a de E-mail (que verifica
  a caixa) são montadas ao abrir; as outras, na primeira vez em que são
  abertas. Abrir caiu para 0,7 s.
- Toda troca de tela relia a tela e, para os contadores do menu, carregava
  todos os honorários em aberto com juros e histórico. Agora:
  - os contadores são uma contagem direta no banco;
  - a tela só relê se algo foi gravado desde a última leitura (o `Contexto`
    conta as gravações) ou se o dia ou a data de referência mudaram. O F5
    sempre relê.
  Voltar a uma tela já aberta caiu de até 0,35 s para 0,04 s.
- A lista de e-mails não carrega o corpo das mensagens; o corpo só é lido
  quando o e-mail é aberto.

### Divergências do e-mail: corrigidas à mão e guardadas no e-mail

Nem toda linha do e-mail bate sozinha: o nome é abreviado, o vencimento está
noutro dia, o cliente não é do sistema. A conferência automática tenta, em
ordem: código ou nome com o mesmo vencimento; depois o nome com a mesma
competência e vencimento a até 31 dias. O que sobrar a pessoa corrige: associa
a linha a um honorário ou a ignora. A correção fica na coluna
`email_mensagem.correcoes` (chave da linha → id do honorário, 0 = ignorar), vale
antes da conferência automática e dá para desfazer.

Num e-mail de resposta, a mensagem citada embaixo é cortada antes de ler. Sem
isso, a lista antiga entra de novo e cada honorário aparece duas vezes.

### "Paga pela empresa" impede a geração

Quem tem a empresa pagadora preenchida não gera honorário na competência: o
valor cobrado da empresa já cobre a pessoa, e o campo é a justificativa. A
regra fica na prévia da geração, como um impedimento com o nome da empresa.
Por isso vale igual para a geração manual e para a automática, e o Mês a mês
não conta essas pessoas como "faltando". Lançar honorário à mão para ela
continua possível.

### Vencimento no próximo dia útil

O vencimento gerado pelo contrato que cai em sábado, domingo ou feriado vai para
o próximo dia útil, e o juros só conta a partir dele. Contam os feriados
nacionais (inclusive Carnaval, Sexta-feira Santa e Corpus Christi, calculados
pela Páscoa), Nossa Senhora da Penha (ES) e 23 de maio (Vila Velha), em
`dominio/feriados.py`. Honorários já gerados não mudam, e o vencimento digitado
à mão (avulso, edição) fica como foi digitado.

## Decisões técnicas

### PostgreSQL no escritório, SQLite no desenvolvimento

Instalado, o banco é o PostgreSQL de um computador da rede, compartilhado por
todos. A conexão é pedida no primeiro uso. Ela fica num JSON em `%APPDATA%`, e
a senha no cofre do sistema. O código-fonte e os testes seguem em SQLite. A
mesma bateria roda contra um PostgreSQL de teste (`HONORARIOS_TESTE_PG`), e foi
assim que apareceram as diferenças corrigidas:

- **Índice único "só quando preenchido":** só tinha a condição do SQLite, e
  ganhou a do PostgreSQL.
- **`strftime` e `date()`:** existem só no SQLite e viraram `extract` ou
  intervalo de datas.
- **`GROUP BY` com comparação:** o PostgreSQL exige a mesma expressão do
  `SELECT`, então a comparação passou para o Python.
- **Tamanho das colunas:** o PostgreSQL recusa texto maior que a coluna. Os
  títulos de notificação e os campos de e-mail são cortados no tamanho.

O backup do PostgreSQL vai para um SQLite local (mesmo formato dos outros
backups), tabela por tabela, na ordem das chaves estrangeiras. A coluna que
aponta para a própria tabela (`cliente.empresa_id`) é preenchida numa segunda
passada, e os contadores de id são acertados depois. Só se restaura backup da
mesma versão do banco.

### SQLAlchemy 2.0 + Alembic
Migrations versionadas eram requisito. O ORM evita SQL manual espalhado por 20
telas, e o Alembic é o par natural. Banco novo é criado pelo metadata e marcado
com `stamp head`; banco existente recebe `upgrade head`.

### `Decimal` gravado como texto
SQLite não tem tipo decimal. Os tipos `Dinheiro` e `Taxa`
(`infra/modelos.py`) serializam via `str`, o que impede o valor de passar por
`float` e perder centavo. `Taxa` guarda 4 casas para a proporção do saldo em
pagamento parcial não perder precisão.

### Enums vão e voltam como enum
O tipo `EnumTexto` converte o texto do banco de volta para o membro do enum. Sem
isso, o ORM devolve `str` e comparações `is` do domínio falham caladas. O mesmo
vale para os combos da interface (`ComboEnum` reconverte o dado do Qt) — foi um
bug real, que fazia a data prometida não ser gravada.

### Uma sessão para a interface
Aplicativo local, um usuário. A interface usa uma sessão longa com commit
explícito em cada ação; cada tela chama `contexto.atualizar()` (que faz
`expire_all`) antes de recarregar. Registros novos são anexados pelo
relacionamento (`cliente.honorarios.append`), não por `session.add`, para as
coleções já carregadas não ficarem desatualizadas.

### Importação personalizada confere em memória
A prévia lê de uma vez os clientes, os contratos e os honorários dos clientes
já cadastrados e confere linha a linha em memória. Com o PostgreSQL na rede,
uma consulta por linha deixava a prévia de milhares de linhas em dezenas de
segundos. A gravação confere de novo contra o banco, item a item, porque ele
pode ter mudado desde a prévia. Os layouts ficam em `configuracao`
(`importacao_layouts`, JSON), sem tabela nem migration.

### Importação não inventa dado
A planilha não guardava data nem valor do pagamento. Honorário pago entra
congelado pelo valor do boleto, com observação dizendo exatamente isso, e sem
registro de `Pagamento`. Cobrança extraída do texto guarda o texto original em
`origem_texto_planilha`.

### Busca espera a digitação
O campo de busca avisa 300 ms depois da última tecla (Enter busca na hora). Antes,
cada tecla refazia a consulta e recriava todos os cartões; os cartões antigos,
soltos do pai antes do `deleteLater`, chegavam a piscar como janelas próprias no
Windows. Agora eles são escondidos antes de soltar, a lista redesenha uma vez só
(`setUpdatesEnabled`) e o painel não empilha recargas enquanto uma está correndo.
Nos testes a espera é zero (`CampoBusca.atraso_ms`).

### Claude com acesso total, pelo MCP
O escritório pediu o Claude podendo fazer tudo o que a tela faz. O servidor MCP
chama a mesma camada de serviços (nada de SQL próprio), uma transação por
ferramenta, e erro de negócio volta como mensagem. Não há modo somente leitura;
as ferramentas que apagam ou desfazem levam `destructiveHint`. Cada chamada anota
hora e ferramenta em `configuracao` (`mcp_ultimo_uso`), que é o que a tela usa para
dizer se o Claude está usando — o servidor só existe enquanto o Claude o abre.

- **Executável à parte** (`FinanceiroMetodosMCP.exe`, console): o programa de
  janela do PyInstaller não tem entrada e saída padrão, que é por onde o MCP fala.
- **SDK `mcp` 1.x** (`<2`): a 2.x trocou o `FastMCP` de nome e de API.
- **Rascunho em `.eml`**, não na pasta Rascunhos do Outlook: criar rascunho pelo
  Graph pede `Mail.ReadWrite`, e o aplicativo cadastrado tem `Mail.Read` e
  `Mail.Send`. Trocar o escopo derrubaria a autorização de quem já entrou.
- **WhatsApp não envia sozinho**: o link só deixa a mensagem escrita. A chave Pix
  vai sozinha na última linha, porque da imagem o cliente não consegue copiar.
- **Imagem na área de transferência por PowerShell** no Windows: a do Qt depende
  do laço de mensagens, que o servidor sem janela não tem; o .NET copia e a
  imagem fica lá depois que ele termina.
- **Grava sozinho, em todo Claude do computador**: a primeira versão gravava só em
  `%APPDATA%\Claude`, e o Claude Desktop da Microsoft Store não lê de lá (o
  Windows desvia o `%APPDATA%` do pacote MSIX para
  `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude`). Agora o
  programa instalado grava, a cada abertura, no Desktop comum, no da Store e no
  `.claude.json` do Claude Code — só onde mudou, com `.bak` e troca atômica do
  arquivo. Os botões de testar e de copiar o comando saíram: não dependiam deles.
- **Contatos em lote cruzam, não cadastram empresa**: a lista de contatos só grava
  onde acha a empresa (código, CPF/CNPJ, telefone já cadastrado ou nome exato, nessa
  ordem). Telefone é comparado por DDD e 8 últimos dígitos, para o número antigo sem
  o 9 e o com 55 serem o mesmo; sem DDD de um lado, vale o número. Telefone que está
  em duas empresas não decide nada. A ferramenta mostra primeiro e grava só com
  `gravar=true`, refazendo o cruzamento na hora.
- **SQL direto, com rede de proteção**: `consultar_banco` sempre desfaz a transação
  (no PostgreSQL ainda abre como somente leitura), então nem um `UPDATE … RETURNING`
  grava por ali. `executar_no_banco` grava e deixa o comando em `log_alteracao`
  (entidade `banco`), porque passa por fora das regras do sistema.
- **A liberação no Claude Code é do usuário**: gravar sozinho a regra
  `mcp__financeiro-honorarios` nas permissões do Claude Code foi barrado pelo próprio
  Claude Code (é o agente se dando permissão). Quem libera é a pessoa, uma vez, em
  `/permissions` ou no `settings.json`.
- **`atualizar_cliente` reenvia os contatos**: o serviço trata a lista como a
  verdade e apagaria os contatos se recebesse vazia.

### Atualização pelo GitHub, sem servidor próprio
O repositório é público e cada versão já era um Release com o instalador. O sistema
consulta `releases/latest` da API do GitHub, compara o número (como número: 1.10
vem depois de 1.9), baixa o `Instalador_Financeiro_Metodos_X.Y.Z.exe` e confere o
SHA-256 que o próprio GitHub publica do arquivo — download pela metade ou trocado é
apagado e não roda. A instalação é o mesmo instalador do Inno Setup, em `/SILENT`:
nada de trocar arquivos do programa com ele aberto. O sistema fecha primeiro (o
instalador é disparado no `aboutToQuit`, depois do backup de saída) e uma linha
`skipifnotsilent` no `[Run]` o abre de novo. A verificação ao abrir só roda no
programa instalado (nunca nos testes nem do código-fonte), oito segundos depois de
abrir e em segundo plano; sem internet, fica para a próxima vez.

O instalador passou a ser gerado pelo GitHub Actions (`windows-latest`, Python
3.12, PyInstaller e Inno Setup) a cada tag `vX.Y.Z`, que também confere se a tag é
igual ao `__version__`. Assim a versão publicada é sempre a do código da tag, e
ninguém precisa gerar instalador no próprio computador.

### Juros: um valor por empresa, sem vigência
Até a 1.5 o juros ao dia tinha histórico de vigências: a mudança valia dali para
frente e os dias anteriores ficavam com o valor antigo. O escritório pediu o
contrário: o juros é o da empresa e vale para tudo o que está em aberto. A tabela
`cliente_juros` continua, com uma linha só por cliente (`clientes.definir_juros`
troca a linha; o anterior vai para o log). A migração `f2c6a9d41b83` deixou em
cada cliente o valor que valia no dia. O cálculo segue sabendo somar faixas —
ainda pode existir mais de uma linha em dados antigos ou importados — e a primeira
linha vale também para os dias antes dela, como sempre.

### Tarefas calculadas, só a baixa gravada
As tarefas do honorário trimestral não são gravadas quando nascem: saem das regras
(`servicos/tarefas.py`) a cada leitura, a partir de "Cliente do escritório desde" e
dos contratos trimestrais ativos. Assim, corrigir a data de entrada de uma empresa
refaz a conta sem sobrar tarefa errada. Só a baixa vira linha (`tarefa`, com a
`chave` contrato + mês de início do trimestre), e desfazer é apagar a linha. A
janela de 12 meses evita que a lista nasça com anos de pendências de clientes
antigos; "Dar baixa em todas" resolve o acúmulo do começo. O trimestre conta da
competência de entrada porque o escritório não usa o trimestre do ano, e a tarefa
nasce no dia seguinte ao fim do trimestre ("quando completar").

### Numeração das versões
A 1.0.0 foi reaproveitada enquanto o sistema não estava em uso. Com ele em uso, a
numeração passou a seguir as entregas (ver a especificação, seção 5): recurso
novo sobe a versão do meio, correção sobe a última.
