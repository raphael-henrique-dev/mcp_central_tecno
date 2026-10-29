"""Cliente assíncrono, somente leitura, para a API pública do Zendesk Help Center."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import __version__

CAMINHO_BUSCA = "/api/v2/help_center/articles/search.json"
CAMINHO_ARTIGO = "/api/v2/help_center/{locale}/articles/{artigo_id}.json"


class ZendeskErro(Exception):
    """Erro base de comunicação com o Zendesk."""


class ZendeskIndisponivel(ZendeskErro):
    """Falha de rede, timeout ou erro 5xx."""


class ZendeskNaoEncontrado(ZendeskErro):
    """Recurso inexistente ou não acessível (HTTP 404)."""


class ZendeskRequisicaoInvalida(ZendeskErro):
    """Requisição rejeitada pela API (HTTP 4xx que não seja 404/429)."""


class ZendeskRateLimit(ZendeskErro):
    """Limite de requisições atingido mesmo após a retentativa."""


class ZendeskRespostaInvalida(ZendeskErro):
    """Resposta que não é JSON ou não segue o formato esperado."""


class ArtigoResumo(BaseModel):
    """Metadados de um artigo retornados pela busca."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    html_url: str
    snippet: str | None = None
    section_id: int | None = None
    updated_at: datetime | None = None
    result_type: str | None = None


class Artigo(BaseModel):
    """Artigo completo retornado pelo endpoint de detalhe."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    html_url: str
    body: str = ""
    section_id: int | None = None
    locale: str | None = None
    updated_at: datetime | None = None
    label_names: list[str] = Field(default_factory=list)
    draft: bool = False


class ResultadoBusca(BaseModel):
    """Página de resultados da busca de artigos."""

    total: int
    pagina: int
    paginas: int
    por_pagina: int
    artigos: list[ArtigoResumo]

    @property
    def tem_mais(self) -> bool:
        return self.pagina < self.paginas


def _interpretar_busca(dados: Any) -> ResultadoBusca:
    try:
        return ResultadoBusca(
            total=int(dados["count"]),
            pagina=int(dados["page"]),
            paginas=int(dados["page_count"]),
            por_pagina=int(dados["per_page"]),
            artigos=[ArtigoResumo.model_validate(item) for item in dados["results"]],
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ZendeskRespostaInvalida(
            "a API do Zendesk retornou uma busca em formato inesperado"
        ) from exc


def _interpretar_artigo(dados: Any) -> Artigo:
    try:
        return Artigo.model_validate(dados["article"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise ZendeskRespostaInvalida(
            "a API do Zendesk retornou um artigo em formato inesperado"
        ) from exc


class ZendeskClient:
    """Cliente HTTP reutilizável para o Help Center.

    Uso típico:

        async with ZendeskClient(base_url, locale, timeout) as cliente:
            resultado = await cliente.buscar_artigos(consulta="PlugSign")

    `transport` e `sleep` existem para permitir testes sem rede e sem espera real.
    """

    def __init__(
        self,
        base_url: str,
        locale: str = "pt-br",
        timeout_segundos: float = 20.0,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_tentativas_429: int = 1,
        espera_maxima_429: float = 5.0,
    ) -> None:
        self._locale = locale
        self._sleep = sleep
        self._max_tentativas_429 = max(0, max_tentativas_429)
        self._espera_maxima_429 = max(0.0, espera_maxima_429)
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx2.Timeout(connect=5.0, read=timeout_segundos, write=5.0, pool=5.0),
            headers={
                "Accept": "application/json",
                "User-Agent": f"mcp-tecnospeed/{__version__}",
            },
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> ZendeskClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def buscar_artigos(
        self,
        *,
        consulta: str | None = None,
        categorias: Sequence[int] = (),
        secoes: Sequence[int] = (),
        limite: int = 5,
        pagina: int = 1,
    ) -> ResultadoBusca:
        """Pesquisa artigos, opcionalmente restritos a categorias ou seções.

        A API exige ao menos um entre `query`, `category` e `section`.
        Quando não há consulta textual, os resultados são ordenados por
        atualização; caso contrário, por relevância.
        """
        texto = (consulta or "").strip()
        if not texto and not categorias and not secoes:
            raise ValueError("informe uma consulta, categoria ou seção")
        if not 1 <= limite <= 100:
            raise ValueError("limite deve estar entre 1 e 100")
        if pagina < 1:
            raise ValueError("pagina deve ser maior ou igual a 1")

        params: dict[str, Any] = {
            "locale": self._locale,
            "per_page": limite,
            "page": pagina,
        }
        if texto:
            params["query"] = texto
            params["sort_by"] = "relevance"
        else:
            params["sort_by"] = "updated_at"
            params["sort_order"] = "desc"
        if secoes:
            params["section"] = ",".join(str(secao) for secao in secoes)
        if categorias:
            params["category"] = ",".join(str(categoria) for categoria in categorias)

        dados = await self._get_json(CAMINHO_BUSCA, params)
        return _interpretar_busca(dados)

    async def obter_artigo(self, artigo_id: int) -> Artigo:
        """Recupera um artigo completo pelo identificador."""
        if artigo_id <= 0:
            raise ValueError("artigo_id deve ser um inteiro positivo")

        caminho = CAMINHO_ARTIGO.format(locale=self._locale, artigo_id=artigo_id)
        try:
            dados = await self._get_json(caminho)
        except ZendeskNaoEncontrado as exc:
            raise ZendeskNaoEncontrado(f"artigo {artigo_id} não encontrado") from exc
        return _interpretar_artigo(dados)

    async def _get_json(self, caminho: str, params: dict[str, Any] | None = None) -> Any:
        tentativas_429 = 0

        while True:
            try:
                resposta = await self._client.get(caminho, params=params)
            except httpx2.TimeoutException as exc:
                raise ZendeskIndisponivel(
                    "a API do Zendesk não respondeu dentro do tempo limite"
                ) from exc
            except httpx2.RequestError as exc:
                raise ZendeskIndisponivel(
                    f"falha de rede ao consultar a API do Zendesk: {exc}"
                ) from exc

            if resposta.status_code == 429 and tentativas_429 < self._max_tentativas_429:
                tentativas_429 += 1
                await self._sleep(self._espera_429(resposta))
                continue

            self._validar_status(resposta)

            try:
                return resposta.json()
            except ValueError as exc:
                raise ZendeskRespostaInvalida(
                    "a API do Zendesk retornou conteúdo que não é JSON"
                ) from exc

    def _validar_status(self, resposta: httpx2.Response) -> None:
        status = resposta.status_code

        if status == 404:
            raise ZendeskNaoEncontrado("recurso não encontrado na API do Zendesk")
        if status == 429:
            raise ZendeskRateLimit(
                "limite de requisições do Zendesk atingido; tente novamente em instantes"
            )
        if 300 <= status < 400:
            raise ZendeskRespostaInvalida(
                f"a API do Zendesk retornou um redirecionamento inesperado (HTTP {status})"
            )
        if status >= 500:
            raise ZendeskIndisponivel(f"API do Zendesk indisponível (HTTP {status})")
        if status >= 400:
            detalhe = self._detalhe_erro(resposta)
            sufixo = f": {detalhe}" if detalhe else ""
            raise ZendeskRequisicaoInvalida(
                f"requisição rejeitada pela API do Zendesk (HTTP {status}){sufixo}"
            )

    @staticmethod
    def _detalhe_erro(resposta: httpx2.Response) -> str:
        try:
            dados = resposta.json()
        except ValueError:
            return ""
        if not isinstance(dados, dict):
            return ""
        erro = dados.get("error")
        if isinstance(erro, dict):
            mensagem = erro.get("message") or erro.get("title")
            return str(mensagem) if mensagem else ""
        if isinstance(erro, str):
            return erro
        return ""

    def _espera_429(self, resposta: httpx2.Response) -> float:
        bruto = resposta.headers.get("Retry-After", "").strip()
        try:
            espera = float(bruto)
        except ValueError:
            espera = 1.0
        return max(0.0, min(espera, self._espera_maxima_429))
