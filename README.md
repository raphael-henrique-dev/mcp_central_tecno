# mcp-tecnospeed

Servidor MCP local que conecta agentes de programação (OpenCode) à documentação
técnica pública da TecnoSpeed, hospedada no Zendesk Help Center.

## Requisitos

- Python 3.11+ (recomendado 3.12)
- Acesso à internet para consultar `atendimento.tecnospeed.com.br`
- Nenhuma credencial ou token

## Instalação

```bash
git clone <url-do-repositorio> mcp-tecnospeed
cd mcp-tecnospeed

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip

# desenvolvimento: modo editável, com ferramentas de desenvolvimento
.venv/bin/python -m pip install -e ".[dev]"

# ou uso local, sem editar o código
.venv/bin/python -m pip install .
```

No Windows, use `.venv\Scripts\python.exe` no lugar de `.venv/bin/python`.

Alternativa com `uv` (opcional):

```bash
uv venv
uv pip install -e ".[dev]"
```

## Configuração de produtos

O arquivo `config/products.json` define quais categorias do Zendesk pertencem a
cada produto. Um produto é mapeado pela **categoria**; `secoes` é opcional e
serve para restringir a busca dentro da categoria.

```json
{
  "base_url": "https://atendimento.tecnospeed.com.br",
  "locale": "pt-br",
  "timeout_segundos": 20,
  "produtos": {
    "PlugSign": {
      "aliases": ["plugsign", "plug sign"],
      "categorias": [24283461594647],
      "secoes": []
    }
  }
}
```

Regras validadas no startup:

- cada produto precisa de ao menos uma categoria ou seção;
- IDs devem ser inteiros positivos;
- aliases não podem apontar para dois produtos diferentes;
- `timeout_segundos` deve ficar entre 1 e 60.

O caminho do arquivo é resolvido nesta ordem:

1. `MCP_TECNOSPEED_CONFIG`, quando definida;
2. `config/products.json` do projeto (clone ou instalação editável);
3. cópia empacotada no wheel, para instalações via `pip install .` fora do
   diretório do projeto.

### Adicionar um produto

Não é necessário alterar código: basta acrescentar uma entrada em
`config/products.json` e reiniciar o OpenCode. Exemplo com o PlugNotas:

```json
"PlugNotas": {
  "aliases": ["plugnotas", "plug notas"],
  "categorias": [360001354313],
  "secoes": []
}
```

O produto passa a aparecer em `status_servidor` e nas três ferramentas. Use
`secoes` quando quiser restringir a busca a partes específicas da categoria.

Em instalação não editável (`pip install .`), edite uma cópia do arquivo e
aponte `MCP_TECNOSPEED_CONFIG` para ela; não altere `site-packages`.

### IDs já validados

| Categoria | ID | Configurado |
|---|---|---|
| PlugSign | `24283461594647` | sim |
| Plug4Market | `4410321200279` | sim |
| TecnoSign | `25583719080727` | — |
| SpeedChat | `9838044930071` | — |
| PlugMessage | `6855680308887` | — |
| PlugMobile | `360001512273` | — |
| PlugStorage | `360000571693` | — |
| PlugNotas | `360001354313` | — |
| PlugDFe Suíte | `4422587629335` | — |
| Manager SaaS | `4422578579351` | — |
| Boleto | `360000550253` | — |
| Pagamentos | `360002212453` | — |
| Extrato OpenFinance | `36019014240919` | — |
| Consulta de Crédito | `360001954693` | — |
| API PIX | `10624929017623` | — |
| Geral | `360000599854` | — |

Categorias públicas em 2026-10-29. Para conferir a lista atual:

```bash
curl -s "https://atendimento.tecnospeed.com.br/api/v2/help_center/pt-br/categories.json?per_page=100"
```

## Execução

```bash
.venv/bin/mcp-tecnospeed
# equivalente:
.venv/bin/python -m mcp_tecnospeed
```

O servidor fala MCP via **stdio**. Ele não abre porta e não deve ser executado
manualmente para uso normal: quem o inicia é o OpenCode.

Para uma verificação rápida de que o processo sobe e responde ao handshake,
use um cliente MCP ou o MCP Inspector.

## Integração com o OpenCode

> Requer **OpenCode v2**. Na v2 os servidores ficam em `mcp.servers` e usa-se
> `disabled` (e não `enabled`) para desativar um servidor.

1. Copie `opencode.json.example` para o `opencode.json` do projeto (ou para
   `~/.config/opencode/opencode.json`, se quiser disponibilidade global).
2. Substitua `/caminho/absoluto/para/mcp-tecnospeed` pelo caminho real do
   repositório na sua máquina.
3. Reinicie o OpenCode e confira a conexão:

```bash
opencode mcp list
```

Configuração:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "tecnospeed_docs": {
        "type": "local",
        "command": [
          "/caminho/absoluto/para/mcp-tecnospeed/.venv/bin/python",
          "-m",
          "mcp_tecnospeed"
        ],
        "cwd": "/caminho/absoluto/para/mcp-tecnospeed",
        "environment": {
          "MCP_TECNOSPEED_CONFIG": "/caminho/absoluto/para/mcp-tecnospeed/config/products.json"
        }
      }
    }
  }
}
```

O OpenCode nomeia as ferramentas como `<servidor>_<ferramenta>`
(`tecnospeed_docs_status_servidor`, `tecnospeed_docs_buscar_documentacao`,
`tecnospeed_docs_listar_artigos_produto`, `tecnospeed_docs_consultar_artigo`).
Com o Code Mode (padrão da v2), elas também aparecem agrupadas em
`tools.tecnospeed_docs.*`.

Se preferir, o `command` pode usar o console script diretamente:
`["/caminho/absoluto/para/mcp-tecnospeed/.venv/bin/mcp-tecnospeed"]`.

### Instruções persistentes (AGENTS.md)

Além de registrar o servidor, oriente o agente no `AGENTS.md` do projeto (ou em
`~/.config/opencode/AGENTS.md` para valer em todos os projetos). Exemplo:

```markdown
## Documentação TecnoSpeed

Quando a tarefa envolver funcionalidades, endpoints ou comportamentos de um
produto TecnoSpeed, consulte a documentação oficial pelas ferramentas do
servidor MCP `tecnospeed_docs` antes de concluir a análise.

- Cite a URL dos artigos usados nas conclusões.
- Diferencie fatos documentados, evidências do código e hipóteses.
- Não invente funcionalidades, endpoints ou comportamentos ausentes da documentação.
- Se a documentação não for suficiente, diga isso explicitamente.
- Não consulte a documentação quando ela não contribuir para a tarefa.
```

## Estrutura

```
src/mcp_tecnospeed/
├── __main__.py       # python -m mcp_tecnospeed
├── server.py         # MCPServer + registro das ferramentas
├── config.py         # carregamento e validação de products.json
├── tools.py          # regras, formatação Markdown e HTML → Markdown
└── zendesk_client.py # cliente HTTP assíncrono (busca, listagem e artigo)
config/products.json  # mapeamento produto → categoria/seções
```

Em instalações via `pip`, a cópia empacotada do config fica em
`site-packages/mcp_tecnospeed/products.json` e é usada quando o projeto não
está presente.

## Ferramentas disponíveis

### `buscar_documentacao`

```text
buscar_documentacao(consulta="assinatura em cadeia", produto="PlugSign", limite=5)
```

- `consulta` (obrigatória): assunto ou dúvida.
- `produto` (opcional): nome ou alias configurado. Sem produto, a busca é global.
- `limite` (opcional): 1 a 10; valores fora da faixa são ajustados com aviso.

Retorna Markdown com título, trecho, ID, seção, data de atualização e URL.
Produto não configurado e ausência de resultados geram mensagens explícitas,
sem fallback silencioso.

### `listar_artigos_produto`

```text
listar_artigos_produto(produto="Plug4Market", limite=20, pagina=1)
```

- `produto` (obrigatório): nome ou alias configurado.
- `limite` (opcional): 1 a 50 artigos por página; valores fora da faixa são
  ajustados com aviso.
- `pagina` (opcional): começa em 1.

Lista os artigos publicados do produto, do mais recente para o mais antigo
(ordem padrão da API), com título, ID, seção, data e trecho curto. Informa o
total, a página atual e a próxima página. Como o Zendesk limita a paginação a
1.000 resultados, páginas acima desse limite são recusadas com uma mensagem
explicando o máximo permitido — sem chamada HTTP inútil.

### `consultar_artigo`

```text
consultar_artigo(artigo_id=30453194425367)
```

- `artigo_id` (obrigatório): ID retornado por `buscar_documentacao`.

Converte o HTML em Markdown preservando código, listas e tabelas, resolve links
relativos contra a URL do artigo e inclui metadados e a fonte. Conteúdo acima de
40.000 caracteres é truncado com aviso explícito e link para o artigo completo.
Artigos inexistentes ou indisponíveis geram mensagem clara.

## Limitações conhecidas

- A busca do Zendesk é textual e ordena por relevância; consultas longas ou
  vagas podem trazer resultados amplos. Prefira termos curtos e específicos.
- Artigos acima de 40.000 caracteres são truncados, sempre com aviso e link
  para o original.
- A paginação da API é limitada a 1.000 resultados; a listagem recusa páginas
  acima disso em vez de propagar erro.
- Não há cache local: cada chamada consulta a API pública.
- Produtos são mapeados manualmente por categoria/seção; categorias novas
  precisam ser adicionadas em `config/products.json`.
- O servidor é somente leitura e não usa autenticação: artigos restritos ou
  não publicados não aparecem.

## Evoluções possíveis

- Cache curto de respostas para reduzir chamadas repetidas.
- Busca semântica ou normalização de consulta, se o uso indicar ruído.
- Inclusão de mais produtos no `config/products.json` conforme a necessidade.
