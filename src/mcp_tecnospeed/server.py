"""Inicialização do servidor MCP e registro das ferramentas."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from . import __version__
from .config import Configuracao, ConfiguracaoInvalida, carregar_config
from .tools import LIMITE_LISTAGEM_PADRAO, LIMITE_PADRAO
from .tools import buscar_documentacao as _buscar_documentacao
from .tools import consultar_artigo as _consultar_artigo
from .tools import listar_artigos_produto as _listar_artigos_produto
from .zendesk_client import ZendeskClient

NOME_SERVIDOR = "tecnospeed_docs"

INSTRUCOES = """
Servidor local de consulta à documentação técnica pública da TecnoSpeed.

Use `buscar_documentacao` para localizar artigos oficiais quando a tarefa
envolver funcionalidades, endpoints, erros ou comportamentos de um produto.
Use `listar_artigos_produto` para descobrir quais assuntos estão documentados
para um produto. Use `consultar_artigo` com o ID retornado para ler o conteúdo
completo. Informe o produto quando ele for conhecido; caso contrário, pesquise
sem filtro. Sempre cite a URL do artigo consultado e diferencie o que está
documentado do que foi inferido a partir do código.
""".strip()


def _descrever_produtos(config: Configuracao) -> str:
    linhas: list[str] = []
    for nome, produto in config.produtos.items():
        escopos: list[str] = []
        if produto.categorias:
            escopos.append("categorias: " + ", ".join(str(c) for c in produto.categorias))
        if produto.secoes:
            escopos.append("seções: " + ", ".join(str(s) for s in produto.secoes))
        linhas.append(f"- **{nome}** — {'; '.join(escopos)}")
    return "\n".join(linhas)


def criar_servidor(
    config: Configuracao | None = None,
    cliente: ZendeskClient | None = None,
) -> MCPServer:
    """Cria o servidor MCP com as ferramentas registradas.

    `cliente` é injetável para permitir testes sem rede.
    """
    config = config or carregar_config()
    cliente = cliente or ZendeskClient(config.base_url, config.locale, config.timeout_segundos)

    @asynccontextmanager
    async def _lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await cliente.aclose()

    mcp = MCPServer(
        NOME_SERVIDOR,
        version=__version__,
        instructions=INSTRUCOES,
        lifespan=_lifespan,
    )

    @mcp.tool()
    def status_servidor() -> str:
        """Retorna o status do servidor MCP e os produtos configurados."""
        return (
            "# MCP TecnoSpeed — status\n\n"
            f"- **Versão:** {__version__}\n"
            f"- **Central:** {config.base_url}\n"
            f"- **Idioma:** {config.locale}\n"
            f"- **Timeout HTTP:** {config.timeout_segundos:g}s\n"
            f"- **Produtos configurados:** {len(config.produtos)}\n"
            f"{_descrever_produtos(config)}\n\n"
            "- **Ferramentas:** `status_servidor`, `buscar_documentacao`, "
            "`listar_artigos_produto`, `consultar_artigo`"
        )

    @mcp.tool()
    async def buscar_documentacao(
        consulta: str,
        produto: str | None = None,
        limite: int = LIMITE_PADRAO,
    ) -> str:
        """Pesquisa a documentação técnica oficial da TecnoSpeed.

        Use quando precisar investigar funcionalidades, endpoints, erros ou
        comportamentos de um produto. Retorna título, trecho, ID e URL dos
        artigos mais relevantes.

        Args:
            consulta: Assunto ou dúvida, em português.
            produto: Produto TecnoSpeed (ex.: "PlugSign", "Plug4Market").
                Omita quando não for possível identificá-lo com segurança.
            limite: Quantidade máxima de resultados (1 a 10).
        """
        return await _buscar_documentacao(cliente, config, consulta, produto, limite)

    @mcp.tool()
    async def listar_artigos_produto(
        produto: str,
        limite: int = LIMITE_LISTAGEM_PADRAO,
        pagina: int = 1,
    ) -> str:
        """Lista os artigos publicados de um produto TecnoSpeed.

        Use para descobrir quais assuntos estão documentados para um produto,
        sem precisar de uma consulta textual. Retorna metadados resumidos e
        paginação; use `consultar_artigo` para ler o conteúdo completo.

        Args:
            produto: Produto TecnoSpeed (ex.: "PlugSign", "Plug4Market").
            limite: Quantidade de artigos por página (1 a 50).
            pagina: Página de resultados, começando em 1.
        """
        return await _listar_artigos_produto(cliente, config, produto, limite, pagina)

    @mcp.tool()
    async def consultar_artigo(artigo_id: int) -> str:
        """Retorna o conteúdo completo de um artigo da central TecnoSpeed.

        Use depois de `buscar_documentacao`, com o ID retornado. O HTML é
        convertido em Markdown, preservando código, listas e tabelas. Artigos
        muito longos são truncados com aviso explícito e link para o original.

        Args:
            artigo_id: Identificador numérico do artigo no Zendesk.
        """
        return await _consultar_artigo(cliente, artigo_id)

    return mcp


def main() -> None:
    try:
        config = carregar_config()
    except ConfiguracaoInvalida as exc:
        # stdout é reservado ao protocolo MCP; erros vão para stderr.
        print(f"[mcp-tecnospeed] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    criar_servidor(config).run("stdio")
