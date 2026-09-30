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
faria o honorário sumir das filas de cobrança, que é justamente onde ele precisa
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
**Acompanhamento** ou pelo Histórico do honorário.

A unidade de acompanhamento é a **mensagem enviada** (o lote), não cada
honorário: foi uma conversa só com a empresa, e a resposta vale para todos os
honorários que estavam nela.

### Lista em cartões, não em tabela, nas telas de cobrança
Cobrança geral, Fila do dia e Acompanhamento mostram cada registro como um
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
A suspensão tira o cliente das filas de trabalho e faz o sistema recusar o
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
