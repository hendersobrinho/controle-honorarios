# Instalação — Financeiro Métodos

O instalador se chama **Financeiro Métodos**: cria o atalho na área de trabalho e
no menu Iniciar, com o ícone do sistema.

## Gerar o instalador

**Gerar** (num Windows com Python 3.12 e o [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```bat
python -m venv .venv
.venv\Scripts\pip install -e .[empacotar]
instalador\gerar_instalador.bat
```

O script faz duas etapas:
1. O PyInstaller, com `instalador\financeiro_metodos.spec`, gera o programa em
   `dist\FinanceiroMetodos`.
2. O Inno Setup, com `instalador\financeiro_metodos.iss`, gera
   `instalador\saida\Instalador_Financeiro_Metodos_<versão>.exe` (hoje, `..._1.0.1.exe`).

**Ícones.** `src/honorarios/recursos/icone.svg` é o ícone do programa (área de
trabalho, janela, barra de tarefas) e `instalador/instalador.png`, o do
instalador. Os `.ico` saem de `scripts/gerar_icones.py`. O do programa é
desenhado a partir do SVG em cada tamanho, de 16 a 256 px, então fica nítido em
qualquer tamanho de ícone do Windows. O do instalador vai até 96 px, o tamanho do
PNG de origem.

## Banco de dados

**PostgreSQL do escritório.** Todos os computadores usam o
mesmo banco, num PostgreSQL de um computador da rede. Na primeira abertura, o
programa pede **servidor** (IP ou nome), **porta** (5432), **banco**
(`financeiro_metodos`), **usuário** e **senha**. Há **Testar conexão** e, se o
banco ainda não existir, **Criar o banco agora**, com um usuário que tenha
permissão.
- Na primeira conexão, as tabelas são criadas. Num banco que já tem dados, ele
  é atualizado para a versão do programa.
- Servidor, porta, banco e usuário ficam em
  `%APPDATA%\Financeiro Métodos\configuracao.json`. A **senha** fica no cofre de
  senhas do Windows.
- Se o servidor não responder ao abrir, aparecem **Tentar de novo**,
  **Configurar conexão…** e **Sair**.
- Para trocar depois: **Configurações → Backup → Banco de dados → Trocar
  conexão…**.

**No computador do banco** (uma vez, por quem cuida do servidor): instalar o
PostgreSQL e criar um usuário para o sistema. Para aceitar os outros
computadores da rede, ajustar `listen_addresses` no `postgresql.conf` e liberar
a faixa da rede no `pg_hba.conf` (ex.: `host all all 192.168.0.0/24
scram-sha-256`). Liberar também a porta 5432 no firewall.

## Backups e atualização

**Backups.** "Gerar backup" e o backup ao fechar copiam o banco inteiro do
servidor para um arquivo na pasta local de cada computador
(`%LOCALAPPDATA%\Financeiro Métodos\dados\backups`). "Restaurar" devolve um
desses arquivos ao servidor numa transação só, e antes faz um backup do estado
atual. Para cópias do servidor em si, o `pg_dump` agendado no computador do
banco continua sendo o recomendado.

**Atualizar.** Suba o `__version__` em `src/honorarios/__init__.py` (é o único
lugar: o `pyproject.toml`, o .exe e o instalador leem de lá), gere de novo e rode
o instalador por cima. O `AppId` fixo faz o Windows
reconhecer a instalação anterior.

## Desenvolvimento

No código-fonte (`.venv/bin/python -m honorarios.app`), o banco é um SQLite em
`dados/`. `HONORARIOS_DADOS` aponta para outra pasta, e `HONORARIOS_BANCO_URL`
para qualquer banco (ex.: um PostgreSQL de teste). `--primeiro-uso` mostra a
tela de conexão sem gravar nada.

**Testes contra o PostgreSQL:** `HONORARIOS_TESTE_PG=postgresql+psycopg://...
pytest` roda tudo num banco de teste. As tabelas são apagadas e recriadas a cada
teste, então use um banco só para isso.
