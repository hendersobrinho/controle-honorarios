Aplique a nova identidade visual do Financeiro Métodos neste repositório (controle-honorarios). Os arquivos novos estão na pasta `para-o-repositorio/` deste pacote, com os mesmos caminhos do repositório. Faça numa branch `identidade-visual`.

## 1. Copiar os arquivos

- `src/honorarios/recursos/icone.svg` → substitui o atual (o gráfico no círculo sai)
- `src/honorarios/recursos/icone_pequeno.svg` → novo (versão para 16–24 px, com o F mais grosso)
- `src/honorarios/recursos/marca.svg` → novo (assinatura do produto, navy `#203461`, para o menu lateral)
- `src/honorarios/recursos/marca_negativo.svg` → novo (branco + ciano, para fundos navy)
- `instalador/financeiro_metodos.ico`, `instalador/instalador.png`, `instalador/instalador.ico` → substituem os atuais
- `docs/imagens/capa.png` → novo (capa do README)

NÃO mexa em `src/honorarios/recursos/logo.svg` nem em `fundo_cobranca.svg`: a logo da Métodos continua nas imagens que vão para o cliente (cobrança e "Pagamento confirmado"). A marca do Financeiro fica só dentro do programa.

## 2. `ui/comum/logo.py`

- Crie `MARCA = ARQUIVO.parent / "marca.svg"`, `MARCA_NEGATIVO = ARQUIVO.parent / "marca_negativo.svg"` e `ICONE_PEQUENO = ARQUIVO.parent / "icone_pequeno.svg"`.
- Generalize `pixmap()` para aceitar o arquivo (`pixmap(largura, escuro=False, arquivo=ARQUIVO)`), mantendo o comportamento atual quando o arquivo não é passado. A troca `#203461 → #E6EAEF` no escuro funciona igual na `marca.svg` (testado: o F vazado mostra o fundo escuro, laranja e ciano continuam).
- `icone(lado)`: use `ICONE_PEQUENO` quando `lado <= 24`.
- Reescreva a `TelaAbertura` (540 × 340, mantenha `avancar()` e a mesma API). O cartão agora é um canhoto:
  - corpo de y = 0 a 252, cantos de raio 20 em cima, degradê de `#203461` (topo esquerdo) para `#16254A` (baixo direito);
  - entre o corpo e o canhoto, uma fresta transparente de 12 px (y = 252 a 264; a janela já é `WA_TranslucentBackground`). Os cantos de baixo do corpo e os de cima do canhoto são recortados por quartos de círculo de raio 14, com centro na borda lateral (x = 0 e x = 540), em y = 252 no corpo e y = 264 no canhoto. Isso forma os furos do picote;
  - picote: tracinhos de 11 × 3 px, de 22 em 22 px, de x = 30 a 510, em `#8C9BC0` com 50% de opacidade, no meio da fresta;
  - canhoto de y = 264 a 340 em `#4BBDCD`, cantos de raio 20 embaixo;
  - no corpo: `marca_negativo.svg` com 96 px de altura, centralizada, topo em y = 56; embaixo dela, "Controle de honorários e cobrança" em `#8C9BC0`, 13 px, centralizado;
  - no canhoto: mensagem à esquerda e porcentagem à direita em `#203461` (600 e 700 de peso, 12–13 px), em y ≈ 284; barra em y = 312, 484 × 6 px, trilho `#203461` com 18% de opacidade e preenchimento `#203461` sólido;
  - remova os arcos coloridos, o brilho radial e o rodapé "Métodos Serviços Contábeis" (a assinatura já diz Métodos);
  - desenhe tudo no `paintEvent` com `QPainterPath`: o retângulo arredondado, menos as elipses dos cantos recortados (`subtracted`). A referência visual está em `kit/aplicacoes/abertura-referencia.png` e o desenho exato em `kit/aplicacoes/abertura-referencia.svg`.

## 3. Menu lateral (`ui/janela_principal.py`)

- Em `_aplicar_tema`, troque `logo.pixmap(170, escuro=...)` pela marca do produto: `logo.pixmap(170, escuro=nome == "escuro", arquivo=logo.MARCA)`.
- Corrija o tooltip de `"Métodos Financeiro"` para `"Financeiro Métodos"`.

## 4. Ícone da janela (`ui/comum/notificacoes.py`)

Em `icone_da_marca()`, renderize `logo.ICONE_PEQUENO` para os lados 16, 20 e 24, e `logo.ICONE` para os demais.

## 5. `scripts/gerar_icones.py`

Use `icone_pequeno.svg` para os tamanhos ≤ 24 ao montar `financeiro_metodos.ico`. Atualize a docstring. Rode o script e confira se o `.ico` gerado bate com o do pacote.

## 6. Tema (`ui/comum/tema.py`), só a cor de destaque

- claro: `"destaque": "#1f6feb"` → `"#203461"` (branco sobre ele: 12,2 : 1)
- escuro: `"destaque": "#5596ff"` → `"#4A6FC2"` (branco sobre ele: 4,8 : 1)
- no claro, o hover do `QPushButton#primario` hoje vira a cor do texto; troque para `#2E4A85`, para o hover continuar visível.
- Não mexa em `atrasado`, `atencao` e `pago`: são cores de situação, não da marca.

## 7. Documentação

- README: coloque `docs/imagens/capa.png` no topo, no lugar do ícone grande. O rodapé com a logo da Métodos fica como está.
- MANUAL.md, seção "Ao abrir": troque a descrição do "cartão azul com os arcos das cores da marca" pelo cartão-canhoto, com a barra carregando no canhoto ciano.
- Depois de rodar o programa, tire uma captura nova da abertura para `docs/imagens/abertura.png`.

## 8. Conferir

- `.venv/bin/python -m pytest` e `.venv/bin/ruff check src testes scripts` passando.
- Abrir o programa nos temas claro e escuro e conferir a abertura, o menu e o ícone na barra de tarefas.
- Commit: `Identidade visual: ícone canhoto, marca do produto e abertura nova`.
