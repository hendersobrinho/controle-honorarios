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
   `instalador\saida\Instalador_Financeiro_Metodos_<versão>.exe`.

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

**Claude (MCP).** O instalador põe o `FinanceiroMetodosMCP.exe` ao lado do
programa, e o programa, toda vez que abre, se grava em cada Claude do computador
(Claude Desktop comum, Claude Desktop da Microsoft Store e Claude Code). Abra o
sistema uma vez depois de instalar (ou depois de instalar o Claude), feche o Claude
por completo — inclusive o ícone perto do relógio — e abra de novo. **Configurações
→ Claude (MCP)** mostra os arquivos onde ele está gravado; o log do sistema registra
cada gravação.

**Publicar uma versão nova.** Suba o `__version__` em `src/honorarios/__init__.py`
(é o único lugar: o `pyproject.toml`, o .exe e o instalador leem de lá), faça o
commit e crie a tag com o mesmo número:

```bash
git tag v1.6.0 && git push origin main v1.6.0
```

O GitHub Actions (`.github/workflows/lancamento.yml`) gera o programa e o
instalador num Windows do próprio GitHub e publica o **Release** com o instalador
anexado e a lista do que mudou — uns 10 minutos. Não precisa mais gerar o
instalador à mão (o `gerar_instalador.bat` continua servindo para testar antes).

**Atualizar os computadores.** Em cada um: **Configurações → Atualizações →
Verificar e atualizar**. O sistema consulta o GitHub, baixa o instalador da versão
nova, confere o arquivo pelo SHA-256 que o GitHub publica, fecha (fazendo o backup
de saída), instala em silêncio e abre de novo. Se a instalação foi feita "para todos
os usuários", o Windows pede a confirmação de administrador. O programa instalado
também procura versão nova sozinho ao abrir (dá para desligar na mesma aba) e avisa
no canto e nas notificações. O `AppId` fixo faz o Windows reconhecer a instalação
anterior; o banco e os backups não são tocados. O registro da última instalação
fica em `atualizacao.log`, na pasta de dados.

A primeira versão com esse botão (1.5.1) precisa ser instalada à mão uma vez; dali
em diante, o botão resolve.

## Desenvolvimento

No código-fonte (`.venv/bin/python -m honorarios.app`), o banco é um SQLite em
`dados/`. `HONORARIOS_DADOS` aponta para outra pasta, e `HONORARIOS_BANCO_URL`
para qualquer banco (ex.: um PostgreSQL de teste). `--primeiro-uso` mostra a
tela de conexão sem gravar nada.

**Testes contra o PostgreSQL:** `HONORARIOS_TESTE_PG=postgresql+psycopg://...
pytest` roda tudo num banco de teste. As tabelas são apagadas e recriadas a cada
teste, então use um banco só para isso.
