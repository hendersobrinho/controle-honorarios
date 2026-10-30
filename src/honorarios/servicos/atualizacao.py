"""Atualização pelo GitHub: ver se há versão nova, baixar o instalador e instalar.

As versões são publicadas como Releases do repositório: a cada tag ``vX.Y.Z`` o
GitHub Actions gera o instalador e o anexa (``.github/workflows/lancamento.yml``).
O sistema pergunta ao GitHub qual é a última, compara com a sua, baixa o
instalador para a pasta temporária, confere o SHA-256 que o GitHub informa e roda
o instalador em modo silencioso. O instalador troca os arquivos e abre o programa
de novo (``[Run]`` com ``skipifnotsilent`` no ``.iss``).

``ultima`` e ``baixar`` fazem rede: rodam fora da thread da tela e não tocam no
banco.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import __version__
from .erros import ErroDeNegocio

REPOSITORIO = "hendersobrinho/controle-honorarios"
API_ULTIMA = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
PREFIXO_INSTALADOR = "Instalador_Financeiro_Metodos_"
CHAVE_AO_ABRIR = "atualizacao_ao_abrir"   # configuração: verificar sozinho ao abrir
BLOCO = 256 * 1024


@dataclass(frozen=True)
class Lancamento:
    """Uma versão publicada no GitHub, com o instalador dela."""

    versao: str
    notas: str
    publicado_em: datetime | None
    instalador_url: str
    instalador_nome: str
    tamanho: int
    sha256: str          # vazio quando o GitHub não informa
    pagina: str

    @property
    def tamanho_mb(self) -> str:
        return f"{self.tamanho / 1024 / 1024:.0f} MB"


def numeros(versao: str) -> tuple[int, ...]:
    """"v1.10.2" → (1, 10, 2): compara como número, não como texto ("1.10" > "1.9")."""
    partes = [int(n) for n in re.findall(r"\d+", versao or "")]
    return tuple((partes + [0, 0, 0])[:3])


def mais_nova(lancamento: Lancamento, atual: str = __version__) -> bool:
    return numeros(lancamento.versao) > numeros(atual)


def _pedir(url: str, espera: float):
    pedido = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"FinanceiroMetodos/{__version__}",
    })
    return urllib.request.urlopen(pedido, timeout=espera)   # noqa: S310 - URL fixa, https


def de_json(dados: dict) -> Lancamento:
    """O release do GitHub (JSON da API) no formato do sistema."""
    versao = str(dados.get("tag_name") or "").lstrip("vV")
    instaladores = [
        item for item in dados.get("assets") or []
        if str(item.get("name", "")).startswith(PREFIXO_INSTALADOR)
        and str(item.get("name", "")).lower().endswith(".exe")
    ]
    if not versao or not instaladores:
        raise ErroDeNegocio(
            f"A versão {versao or '?'} ainda não tem instalador publicado no GitHub. "
            "Tente de novo em alguns minutos."
        )
    instalador = instaladores[0]
    digest = str(instalador.get("digest") or "")
    publicado = dados.get("published_at")
    try:
        quando = datetime.fromisoformat(publicado.replace("Z", "+00:00")) if publicado else None
    except ValueError:
        quando = None
    return Lancamento(
        versao=versao,
        notas=str(dados.get("body") or "").strip(),
        publicado_em=quando,
        instalador_url=str(instalador.get("browser_download_url") or ""),
        instalador_nome=str(instalador.get("name")),
        tamanho=int(instalador.get("size") or 0),
        sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
        pagina=str(dados.get("html_url") or ""),
    )


def ultima(espera: float = 15) -> Lancamento:
    """A última versão publicada no GitHub."""
    try:
        with _pedir(API_ULTIMA, espera) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as falha:
        if falha.code == 404:
            raise ErroDeNegocio("Ainda não há versão publicada no GitHub.") from falha
        raise ErroDeNegocio(f"O GitHub respondeu com erro {falha.code}. "
                            "Tente de novo daqui a pouco.") from falha
    except (urllib.error.URLError, TimeoutError, OSError) as falha:
        raise ErroDeNegocio(
            "Não consegui falar com o GitHub. Confira a internet e tente de novo."
        ) from falha
    except ValueError as falha:
        raise ErroDeNegocio("O GitHub respondeu algo que não entendi.") from falha
    return de_json(dados)


def baixar(
    lancamento: Lancamento,
    pasta: Path | None = None,
    progresso: Callable[[int, int], None] | None = None,
    espera: float = 60,
) -> Path:
    """Baixa o instalador e confere tamanho e SHA-256. Arquivo pela metade não fica."""
    pasta = pasta or Path(tempfile.gettempdir()) / "FinanceiroMetodos-atualizacao"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / lancamento.instalador_nome
    parcial = destino.with_name(destino.name + ".parcial")
    soma = hashlib.sha256()
    feito = 0
    try:
        with _pedir(lancamento.instalador_url, espera) as resposta, parcial.open("wb") as saida:
            total = int(resposta.headers.get("Content-Length") or lancamento.tamanho or 0)
            while bloco := resposta.read(BLOCO):
                saida.write(bloco)
                soma.update(bloco)
                feito += len(bloco)
                if progresso:
                    progresso(feito, total)
    except (urllib.error.URLError, TimeoutError, OSError) as falha:
        parcial.unlink(missing_ok=True)
        raise ErroDeNegocio(
            "O download do instalador parou no meio. Confira a internet e tente de novo."
        ) from falha
    if lancamento.tamanho and feito != lancamento.tamanho:
        parcial.unlink(missing_ok=True)
        raise ErroDeNegocio("O instalador veio incompleto. Tente de novo.")
    if lancamento.sha256 and soma.hexdigest() != lancamento.sha256:
        parcial.unlink(missing_ok=True)
        raise ErroDeNegocio(
            "O instalador baixado não confere com o publicado no GitHub (SHA-256). "
            "Por segurança ele foi apagado. Tente de novo."
        )
    parcial.replace(destino)
    return destino


def pode_instalar() -> bool:
    """Só o programa instalado no Windows se atualiza sozinho (do código, é git pull)."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def instalar(instalador: Path, log: Path | None = None) -> None:
    """Roda o instalador em silêncio, separado do programa (que vai fechar em seguida).

    O instalador fecha o que ainda estiver aberto, troca os arquivos e abre o
    programa de novo. Se a instalação anterior foi "para todos os usuários", o
    Windows pede a confirmação de administrador.
    """
    argumentos = [str(instalador), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                  "/CLOSEAPPLICATIONS"]
    if log is not None:
        argumentos.append(f"/LOG={log}")
    criacao = (getattr(subprocess, "DETACHED_PROCESS", 0)
               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen(argumentos, creationflags=criacao, close_fds=True)   # noqa: S603
