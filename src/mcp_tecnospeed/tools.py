"""Regras e formatação das ferramentas expostas ao agente."""

from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import markdownify as markdownify_html

from .config import Configuracao, ProdutoConfig
from .zendesk_client import (
    ArtigoResumo,
    ZendeskClient,
    ZendeskErro,
    ZendeskNaoEncontrado,
)

LIMITE_PADRAO = 5
LIMITE_MAXIMO = 10
LIMITE_LISTAGEM_PADRAO = 20
LIMITE_LISTAGEM_MAXIMO = 50
TAMANHO_TRECHO = 320
TAMANHO_TRECHO_LISTAGEM = 220
LIMITE_CONTEUDO = 40_000
LIMITE_RESULTADOS_API = 1_000

_TAG_HTML = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


class ProdutoNaoConfigurado(Exception):
    """Produto informado que não existe em products.json."""


def resolver_produto(config: Configuracao, nome: str) -> tuple[str, ProdutoConfig]:
    """Resolve o nome de um produto por nome canônico ou alias."""
    chave = nome.strip().casefold()
    for nome_produto, produto in config.produtos.items():
        candidatos = {nome_produto.casefold(), *(a.casefold() for a in produto.aliases)}
        if chave in candidatos:
            return nome_produto, produto
    raise ProdutoNaoConfigurado(nome)


def limpar_trecho(texto: str | None, maximo: int = TAMANHO_TRECHO) -> str:
    """Remove HTML do snippet, normaliza espaços e limita o tamanho."""
    if not texto:
        return ""

    limpo = html.unescape(_TAG_HTML.sub("", texto))
    limpo = _ESPACOS.sub(" ", limpo).strip()
    if len(limpo) <= maximo:
        return limpo

    corte = limpo[:maximo].rsplit(" ", 1)[0] or limpo[:maximo]
    return f"{corte.rstrip()}…"


def _formatar_data(valor: datetime | None) -> str:
    return valor.strftime("%Y-%m-%d") if valor else "data desconhecida"


def _escapar_titulo(titulo: str) -> str:
    return titulo.replace("[", r"\[").replace("]", r"\]")


def _ajustar_para_faixa(valor: int, minimo: int, maximo: int) -> tuple[int, bool]:
    ajustado = max(minimo, min(int(valor), maximo))
    return ajustado, ajustado != valor


def _formatar_artigos(
    artigos: list[ArtigoResumo], tamanho_trecho: int = TAMANHO_TRECHO
) -> list[str]:
    linhas: list[str] = []
    for indice, artigo in enumerate(artigos, start=1):
        trecho = limpar_trecho(artigo.snippet, tamanho_trecho)
        linhas.append(
            f"{indice}. **[{_escapar_titulo(artigo.title)}](<{artigo.html_url}>)**\n"
            f"   - ID: `{artigo.id}`\n"
            f"   - Seção: `{artigo.section_id or 'não informada'}` · "
            f"Atualizado em: {_formatar_data(artigo.updated_at)}"
        )
        if trecho:
            linhas.append(f"   - Trecho: {trecho}")
        linhas.append("")
    return linhas


def _mensagem_produto_desconhecido(config: Configuracao, produto: str) -> str:
    disponiveis = ", ".join(config.produtos)
    return (
        "## Produto não configurado\n\n"
        f"Não há configuração para o produto **{produto}**.\n\n"
        f"Produtos disponíveis: {disponiveis}.\n\n"
        "Se o produto estiver correto, adicione a categoria correspondente em "
        "`config/products.json`. Para pesquisar sem filtro de produto, chame "
        "novamente sem o parâmetro `produto` — os resultados podem ser menos precisos."
    )


def _mensagem_sem_resultados(consulta: str, produto: str | None) -> str:
    escopo = f" em **{produto}**" if produto else " na central"
    return (
        "## Nenhum resultado\n\n"
        f'Não encontrei artigos para **"{consulta}"**{escopo}.\n\n'
        "Sugestões:\n"
        "- use termos mais curtos ou sinônimos;\n"
        "- remova o filtro de produto para ampliar a busca;\n"
        "- confira se o produto está mapeado corretamente em `config/products.json`."
    )


def _mensagem_erro(erro: ZendeskErro) -> str:
    return (
        "## Não foi possível consultar a documentação\n\n"
        f"{erro}\n\n"
        "Tente novamente em instantes. Se o problema persistir, verifique a "
        "conectividade com `atendimento.tecnospeed.com.br`."
    )


def _numero(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def html_para_markdown(conteudo_html: str, base_url: str) -> str:
    """Converte o HTML do artigo em Markdown, resolvendo links relativos.

    `base_url` deve ser a URL pública do artigo, para que âncoras e caminhos
    relativos continuem apontando para o lugar certo.
    """
    soup = BeautifulSoup(conteudo_html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    for tag in soup.find_all(["a", "img"]):
        atributo = "href" if tag.name == "a" else "src"
        valor = tag.get(atributo)
        if valor:
            tag[atributo] = urljoin(base_url, valor)

    markdown = markdownify_html(str(soup), heading_style="ATX", bullets="-")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def truncar_markdown(texto: str, maximo: int = LIMITE_CONTEUDO) -> tuple[str, bool]:
    """Limita o conteúdo sem cortar uma linha no meio quando possível."""
    if len(texto) <= maximo:
        return texto, False

    corte = texto[:maximo]
    quebra = corte.rfind("\n")
    if quebra >= maximo // 2:
        corte = corte[:quebra]
    return corte.rstrip(), True


async def buscar_documentacao(
    cliente: ZendeskClient,
    config: Configuracao,
    consulta: str,
    produto: str | None = None,
    limite: int = LIMITE_PADRAO,
) -> str:
    """Pesquisa artigos e devolve um resumo em Markdown para o agente."""
    texto = (consulta or "").strip()
    if not texto:
        return (
            "## Consulta vazia\n\n"
            "Informe o assunto que deseja pesquisar, por exemplo: "
            '`buscar_documentacao(consulta="assinatura em cadeia", produto="PlugSign")`.'
        )

    nome_produto: str | None = None
    categorias: list[int] = []
    secoes: list[int] = []
    if produto and produto.strip():
        try:
            nome_produto, configuracao_produto = resolver_produto(config, produto)
        except ProdutoNaoConfigurado:
            return _mensagem_produto_desconhecido(config, produto.strip())
        categorias = list(configuracao_produto.categorias)
        secoes = list(configuracao_produto.secoes)

    limite_ajustado, limite_alterado = _ajustar_para_faixa(limite, 1, LIMITE_MAXIMO)

    try:
        resultado = await cliente.buscar_artigos(
            consulta=texto,
            categorias=() if secoes else categorias,
            secoes=secoes,
            limite=limite_ajustado,
        )
    except ZendeskErro as exc:
        return _mensagem_erro(exc)

    if not resultado.artigos:
        return _mensagem_sem_resultados(texto, nome_produto)

    escopo = (
        f"**Produto:** {nome_produto}"
        if nome_produto
        else ("**Produto:** não informado — busca global (resultados podem ser menos precisos)")
    )
    linhas = [
        f'## Documentação TecnoSpeed — "{texto}"',
        "",
        escopo,
        f"**Resultados:** {len(resultado.artigos)} de {resultado.total} "
        f"(página {resultado.pagina} de {resultado.paginas or 1})",
    ]
    if limite_alterado:
        linhas.append(
            f"**Limite ajustado:** {limite_ajustado} (o máximo permitido é {LIMITE_MAXIMO})."
        )
    linhas.extend(["", *_formatar_artigos(resultado.artigos)])
    if resultado.tem_mais:
        linhas.append("> Há mais resultados. Refine a consulta para torná-la mais específica.")
    linhas.append("> Para ler o conteúdo completo, use `consultar_artigo` com o ID do artigo.")
    return "\n".join(linhas).strip()


async def listar_artigos_produto(
    cliente: ZendeskClient,
    config: Configuracao,
    produto: str,
    limite: int = LIMITE_LISTAGEM_PADRAO,
    pagina: int = 1,
) -> str:
    """Lista os artigos publicados de um produto, com metadados resumidos."""
    nome = (produto or "").strip()
    if not nome:
        return (
            "## Produto não informado\n\n"
            "Informe o produto que deseja listar, por exemplo: "
            '`listar_artigos_produto(produto="PlugSign")`.'
        )

    try:
        nome_produto, configuracao_produto = resolver_produto(config, nome)
    except ProdutoNaoConfigurado:
        return _mensagem_produto_desconhecido(config, nome)

    limite_ajustado, limite_alterado = _ajustar_para_faixa(limite, 1, LIMITE_LISTAGEM_MAXIMO)
    pagina_ajustada = max(1, int(pagina))
    pagina_alterada = pagina_ajustada != pagina

    if pagina_ajustada * limite_ajustado > LIMITE_RESULTADOS_API:
        pagina_maxima = LIMITE_RESULTADOS_API // limite_ajustado
        return (
            "## Página fora do limite da API\n\n"
            f"A API do Zendesk permite acessar no máximo {_numero(LIMITE_RESULTADOS_API)} "
            f"resultados. Com `limite={limite_ajustado}`, a página máxima é "
            f"**{pagina_maxima}**.\n\n"
            "Reduza o `limite` ou escolha uma página menor."
        )

    categorias = list(configuracao_produto.categorias)
    secoes = list(configuracao_produto.secoes)

    try:
        resultado = await cliente.buscar_artigos(
            consulta=None,
            categorias=() if secoes else categorias,
            secoes=secoes,
            limite=limite_ajustado,
            pagina=pagina_ajustada,
        )
    except ZendeskErro as exc:
        return _mensagem_erro(exc)

    if not resultado.artigos:
        if pagina_ajustada > 1:
            return (
                "## Página sem resultados\n\n"
                f"A página **{pagina_ajustada}** não retornou artigos para "
                f"**{nome_produto}**.\n\n"
                "O produto pode ter menos páginas do que o solicitado. "
                "Use `pagina=1` para ver o total de artigos."
            )
        return (
            "## Nenhum artigo encontrado\n\n"
            f"O produto **{nome_produto}** está configurado, mas a categoria ou "
            "seção correspondente não retornou artigos publicados.\n\n"
            "Confira os IDs em `config/products.json` e se há artigos publicados "
            "na central."
        )

    linhas = [
        f"## Artigos — {nome_produto}",
        "",
        f"**Total:** {resultado.total} · **Página:** {resultado.pagina} de "
        f"{resultado.paginas or 1} · **Limite:** {resultado.por_pagina}",
    ]
    if limite_alterado:
        linhas.append(
            f"**Limite ajustado:** {limite_ajustado} "
            f"(o máximo permitido é {LIMITE_LISTAGEM_MAXIMO})."
        )
    if pagina_alterada:
        linhas.append(f"**Página ajustada:** {pagina_ajustada}.")

    linhas.extend(["", *_formatar_artigos(resultado.artigos, TAMANHO_TRECHO_LISTAGEM)])
    linhas.append("> Para ler o conteúdo completo, use `consultar_artigo` com o ID do artigo.")
    if resultado.tem_mais:
        linhas.append(
            f"> Há mais artigos. Use `pagina={resultado.pagina + 1}` para a próxima página."
        )
    return "\n".join(linhas).strip()


async def consultar_artigo(cliente: ZendeskClient, artigo_id: int) -> str:
    """Recupera um artigo completo e devolve o conteúdo em Markdown."""
    if artigo_id <= 0:
        return (
            "## Artigo inválido\n\n"
            "O identificador do artigo deve ser um inteiro positivo. "
            "Use `buscar_documentacao` para obter IDs válidos."
        )

    try:
        artigo = await cliente.obter_artigo(artigo_id)
    except ZendeskNaoEncontrado:
        return (
            "## Artigo não encontrado\n\n"
            f"Não encontrei o artigo `{artigo_id}` na central. Ele pode ter sido "
            "removido ou não estar acessível publicamente.\n\n"
            "Use `buscar_documentacao` para localizar o artigo correto e confira "
            "o ID retornado."
        )
    except ZendeskErro as exc:
        return _mensagem_erro(exc)

    completo = html_para_markdown(artigo.body, artigo.html_url)
    conteudo, truncado = truncar_markdown(completo)

    linhas = [
        f"# {artigo.title}",
        "",
        f"- **ID:** `{artigo.id}`",
        f"- **Seção:** `{artigo.section_id or 'não informada'}`",
        f"- **Atualizado em:** {_formatar_data(artigo.updated_at)}",
    ]
    if artigo.label_names:
        linhas.append("- **Labels:** " + ", ".join(f"`{label}`" for label in artigo.label_names))
    linhas.extend([f"- **Fonte:** <{artigo.html_url}>", ""])

    if truncado:
        linhas.extend(
            [
                "> **Conteúdo truncado:** exibindo os primeiros "
                f"{_numero(len(conteudo))} de {_numero(len(completo))} caracteres. "
                f"Leia o artigo completo em <{artigo.html_url}>.",
                "",
            ]
        )

    linhas.extend(
        [
            "---",
            "",
            conteudo or "_O artigo não possui conteúdo textual disponível._",
        ]
    )
    return "\n".join(linhas).strip()


__all__ = [
    "LIMITE_CONTEUDO",
    "LIMITE_LISTAGEM_MAXIMO",
    "LIMITE_LISTAGEM_PADRAO",
    "LIMITE_MAXIMO",
    "LIMITE_PADRAO",
    "ProdutoNaoConfigurado",
    "buscar_documentacao",
    "consultar_artigo",
    "html_para_markdown",
    "limpar_trecho",
    "listar_artigos_produto",
    "resolver_produto",
    "truncar_markdown",
]
