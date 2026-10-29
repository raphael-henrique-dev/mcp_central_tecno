"""Carregamento e validação da configuração de produtos."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CAMINHO_PROJETO = Path(__file__).resolve().parents[2] / "config" / "products.json"
CAMINHO_EMPACOTADO = Path(__file__).resolve().with_name("products.json")


class ConfiguracaoInvalida(Exception):
    """Erro de configuração que impede o servidor de iniciar."""


class ProdutoConfig(BaseModel):
    """Escopo de documentação de um produto.

    O produto é identificado por uma ou mais categorias do Zendesk. As seções
    são opcionais e servem para restringir a busca dentro dessas categorias.
    """

    model_config = ConfigDict(extra="forbid")

    aliases: list[str] = Field(default_factory=list)
    categorias: list[int] = Field(default_factory=list)
    secoes: list[int] = Field(default_factory=list)

    @field_validator("categorias", "secoes")
    @classmethod
    def _ids_positivos(cls, valores: list[int]) -> list[int]:
        for valor in valores:
            if valor <= 0:
                raise ValueError("os IDs devem ser inteiros positivos")
        return list(dict.fromkeys(valores))

    @field_validator("aliases")
    @classmethod
    def _aliases_limpos(cls, valores: list[str]) -> list[str]:
        vistos: set[str] = set()
        resultado: list[str] = []
        for valor in valores:
            alias = valor.strip()
            if not alias:
                continue
            chave = alias.casefold()
            if chave in vistos:
                continue
            vistos.add(chave)
            resultado.append(alias)
        return resultado

    @model_validator(mode="after")
    def _escopo_obrigatorio(self) -> ProdutoConfig:
        if not self.categorias and not self.secoes:
            raise ValueError("informe ao menos uma categoria ou seção")
        return self


class Configuracao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://atendimento.tecnospeed.com.br"
    locale: str = "pt-br"
    timeout_segundos: float = 20.0
    produtos: dict[str, ProdutoConfig]

    @field_validator("base_url")
    @classmethod
    def _base_url_valida(cls, valor: str) -> str:
        url = valor.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("base_url deve começar com http:// ou https://")
        return url

    @field_validator("locale")
    @classmethod
    def _locale_valido(cls, valor: str) -> str:
        locale = valor.strip()
        if not locale:
            raise ValueError("locale não pode ser vazio")
        return locale

    @field_validator("timeout_segundos")
    @classmethod
    def _timeout_valido(cls, valor: float) -> float:
        if not 1 <= valor <= 60:
            raise ValueError("timeout_segundos deve estar entre 1 e 60")
        return valor

    @field_validator("produtos")
    @classmethod
    def _produtos_validos(cls, produtos: dict[str, ProdutoConfig]) -> dict[str, ProdutoConfig]:
        if not produtos:
            raise ValueError("configure ao menos um produto")

        nomes: set[str] = set()
        aliases: dict[str, str] = {}
        for nome, produto in produtos.items():
            nome_limpo = nome.strip()
            if not nome_limpo:
                raise ValueError("o nome do produto não pode ser vazio")

            chave_nome = nome_limpo.casefold()
            if chave_nome in nomes:
                raise ValueError(f"produto duplicado: {nome_limpo}")
            nomes.add(chave_nome)

            for alias in [nome_limpo, *produto.aliases]:
                chave = alias.casefold()
                if chave in aliases and aliases[chave] != nome_limpo:
                    raise ValueError(
                        f"alias '{alias}' associado a mais de um produto "
                        f"({aliases[chave]} e {nome_limpo})"
                    )
                aliases[chave] = nome_limpo
        return produtos


def caminho_config() -> Path:
    """Resolve o caminho da configuração, respeitando MCP_TECNOSPEED_CONFIG.

    Ordem de precedência:

    1. `MCP_TECNOSPEED_CONFIG`, quando definida;
    2. `config/products.json` do projeto (instalação editável ou clone);
    3. cópia empacotada no wheel (`mcp_tecnospeed/products.json`).

    A cópia empacotada permite `pip install .` sem depender do diretório do
    projeto, mantendo `config/products.json` como fonte editável no repositório.
    """
    env = os.environ.get("MCP_TECNOSPEED_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    if CAMINHO_PROJETO.is_file():
        return CAMINHO_PROJETO
    return CAMINHO_EMPACOTADO


def carregar_config(caminho: Path | str | None = None) -> Configuracao:
    """Lê e valida o arquivo de configuração.

    Levanta ConfiguracaoInvalida com uma mensagem compreensível para qualquer
    problema de leitura, JSON ou schema.
    """
    arquivo = Path(caminho).expanduser() if caminho is not None else caminho_config()

    try:
        texto = arquivo.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfiguracaoInvalida(
            f"não foi possível ler a configuração em {arquivo}: {exc}"
        ) from exc

    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ConfiguracaoInvalida(
            f"JSON inválido em {arquivo} (linha {exc.lineno}, coluna {exc.colno}): {exc.msg}"
        ) from exc

    try:
        return Configuracao.model_validate(dados)
    except ValidationError as exc:
        raise ConfiguracaoInvalida(f"configuração inválida em {arquivo}:\n{exc}") from exc
