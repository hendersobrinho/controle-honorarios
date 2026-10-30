# Financeiro Métodos — Identidade visual v1.0

Figma: https://www.figma.com/design/7p7zlXJI6Cvq8P3GMnfn8k

## O símbolo: um canhoto com um F dentro

- **O canhoto (navy):** o honorário em si
- **O F (vazado):** Financeiro, com as mesmas pontas arredondadas do DocFlow
- **O braço laranja:** o valor que corre, o juros dia a dia
- **O picote:** a baixa; quando o pagamento entra, o canhoto se destaca
- **O canhoto ciano:** o comprovante, o mesmo ciano do grupo Cobrança no menu

Feito no mesmo grid do DocFlow (u = 16 px em 512): símbolo 16 × 24 u, cantos 2 u, F com 3 u, furos de r = 1,5 u.
Em 16–24 px usa a versão "pequeno" (F mais grosso).

## Pastas

- `para-o-repositorio/` — os arquivos com os mesmos caminhos do repositório controle-honorarios
- `PROMPT-claude-code.md` — o passo a passo para aplicar (abertura nova, menu, ícone, tema)
- `kit/simbolo/` — cor, negativo, mono navy e mono branco
- `kit/logo/` — horizontal (principal), uma linha e vertical, cada uma em cor e negativo
- `kit/icone/` — ícone escuro e claro, padrão e pequeno, e PNGs de 16 a 1024
- `kit/capa/` — capa do README (1600 × 400)
- `kit/aplicacoes/` — referência da tela de abertura (540 × 340)
- `kit/exploracao-rascunhos.png` — os rascunhos até chegar no símbolo

Todos os SVGs foram testados no QSvgRenderer (PySide6). Só usam caminhos com `fill-rule`, sem
texto, sem clip-path e sem filtro, e o nome já vai convertido em curvas (não precisa da Sora instalada).

## Cores

| Nome | HEX | Papel |
|---|---|---|
| Navy Métodos | `#203461` | o canhoto, fundos, botões principais |
| Ciano Canhoto | `#4BBDCD` | pago, comprovante, grupo Cobrança (texto em cima: navy) |
| Laranja Juros | `#F9B259` | o valor que corre, contadores do menu (texto em cima: navy) |

Vermelho, âmbar e verde continuam só para a situação do honorário (atrasado, atenção, pago).

## O que não muda

A imagem da cobrança e o "Pagamento confirmado" continuam com a logo da Métodos (`logo.svg`).
O cliente se relaciona com o escritório, não com o programa.
