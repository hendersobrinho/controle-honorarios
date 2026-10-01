# Decisões de projeto

Registro do que foi decidido e por quê, para não ser reaberto sem motivo.

## Regras de negócio

### Juros por dia é fixo por cliente, não derivado do valor
A planilha calcula, na prática, `juros/dia ≈ valor do boleto × 0,0667%`
(2% ao mês ÷ 30): a mediana é 0,0666% na aba principal e 0,0667% na de IRPF, e
194 de 206 linhas caem em ±0,005 p.p. disso. Mesmo assim, **o sistema usa um
valor fixo por cliente**, com histórico de vigência, conforme decidido em
29/09/2026. As 12 linhas em que o juros ficou desatualizado em relação ao valor
(AMINON, JKL, RONALDH, VANDA, LEONARDO) entram no relatório de importação como
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

O PDF usa o fundo da imagem de cobrança como papel: o SVG sem o grupo
`id="conteudo"` (a camada que só serve à imagem), desenhado a ~200 dpi e esticado
para a proporção do A4 repetindo a faixa do meio — a mesma técnica da imagem
comprida, que não deforma logos. O conteúdo vai num cartão branco entre o logo
do topo e o do rodapé; as medidas do cartão são constantes em
`servicos/relatorio_juros.py`, ajustadas ao fundo atual. Sem o grupo no SVG, o
PDF sai no visual simples, sem fundo. Os blocos do relatório são mantidos
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

## Decisões técnicas

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

### Importação não inventa dado
A planilha não guardava data nem valor do pagamento. Honorário pago entra
congelado pelo valor do boleto, com observação dizendo exatamente isso, e sem
registro de `Pagamento`. Cobrança extraída do texto guarda o texto original em
`origem_texto_planilha`.
