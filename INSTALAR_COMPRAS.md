# Módulo de Ordens de compra — como instalar

## O que já está pronto

| Arquivo | O que fazer |
|---|---|
| `models.py` | **substitui** o seu (é o mesmo arquivo, com o módulo novo no fim e a tela `compras` na matriz de permissões) |
| `routes/compras.py` | arquivo novo |
| `templates/compras.html` | arquivo novo |
| `migrar_ordens_compra.py` | roda uma vez na raiz do projeto e pode apagar depois |

Ordem: copiar os arquivos → `python migrar_ordens_compra.py` → os 3 ajustes abaixo → reiniciar.

## Os 3 ajustes que dependem de arquivos que não vieram

### 1. Registrar a blueprint no `app.py`

Junto das outras (`bp_manutencao`, `bp_estoque`…):

```python
from routes.compras import bp_compras
app.register_blueprint(bp_compras)
```

O `bp_compras` já nasce com `url_prefix="/api"`. Se no seu `app.py` as blueprints
são registradas com o prefixo por fora — `app.register_blueprint(bp_estoque, url_prefix="/api")` —
então abra `routes/compras.py` e troque a linha da blueprint por:

```python
bp_compras = Blueprint("compras", __name__)
```

Para conferir, com o sistema no ar: `/api/ordens_compra` tem que responder uma lista
(`[]` no começo), não 404.

### 2. Criar a rota da página (no `paginas.py`)

Copie exatamente o que existe para `estoque` ou `manutencao`, trocando o nome:

```python
@bp_paginas.get("/compras")
@pagina_protegida("compras")          # use o mesmo decorador das outras telas
def compras():
    return render_template("compras.html")
```

Se as páginas do seu `paginas.py` forem geradas por um laço sobre `TELAS_SISTEMA`,
não precisa fazer nada aqui — a tela `compras` já entrou nessa lista.

### 3. Item no menu (`base.html`)

No grupo **Operação**, junto de "Ordens de serviço":

```html
{% if pode('compras') %}
<a class="item-menu {{ 'ativo' if tela == 'compras' }}" href="/compras">
  <i class="fa-solid fa-cart-shopping"></i> Ordens de compra
</a>
{% endif %}
```

Ajuste as classes para as mesmas dos outros itens do seu menu.

## Permissões

A tela nova é `compras`. Quem tem **`editar`** nela é quem aprova, reprova e marca
como comprada; quem tem **`visualizar`** só consulta.

Atenção a um detalhe do sistema: perfil `operador` recebe `editar` em toda tela nova
por padrão (`PADRAO_POR_PERFIL`). Ou seja, hoje qualquer operador consegue aprovar.
Para separar de verdade quem pede de quem autoriza, grave `compras: visualizar` na
matriz de quem só solicita — a linha específica vence o padrão do perfil.

Já deixei prontas duas sugestões em `CARGOS_SUGERIDOS`:
- **Almoxarifado** ganhou `compras: editar`;
- **Financeiro / compras** (cargo novo) com `compras: editar` e o resto só leitura.

## Regras que ficaram gravadas no código

- A ordem **nunca** mexe no saldo do estoque — nem ao aprovar, nem ao comprar.
  A entrada continua sendo pela nota fiscal, no Estoque.
- `Pendente → Aprovada → Comprada`, com `Pendente → Reprovada` e um botão
  **Reabrir** que devolve a reprovada para Pendente (corrige e reenvia, sem redigitar).
- Itens só entram e saem enquanto a ordem está **Pendente**; o cabeçalho também
  só é editável nesse estado.
- Reprovar **exige** o motivo — ele volta para quem pediu e sai na impressão.
- Excluir só é permitido em Pendente ou Reprovada.
- A numeração é automática: `OC-0001`, `OC-0002`…
- O status **não** entra no formulário de cadastro de propósito: ele só muda pelas
  rotas `/aprovar`, `/reprovar`, `/comprar` e `/reabrir`, que gravam quem decidiu,
  quando, e registram no log de auditoria.

## Coisas que talvez você queira mudar

- **Justificativa obrigatória**: em `routes/compras.py`, `obrigatorios=("data_solicitacao", "justificativa")`.
  Tire `"justificativa"` da tupla se achar burocrático demais.
- **Item repetido**: hoje dá para lançar a mesma peça duas vezes na mesma ordem
  (às vezes é proposital: marcas ou prazos diferentes). Se quiser bloquear, é uma
  checagem em `adicionar_item`.

## API criada

| Método | Rota | Quem pode |
|---|---|---|
| GET | `/api/ordens_compra?inicio=&fim=&status=` | visualizar |
| GET · POST · PUT · DELETE | `/api/ordens_compra[/<id>]` | visualizar / editar |
| GET | `/api/ordens_compra/<id>/itens` | visualizar |
| POST · DELETE | `/api/ordens_compra/<id>/itens[/<item_id>]` | editar |
| POST | `/api/ordens_compra/<id>/aprovar` · `/reprovar` · `/comprar` · `/reabrir` | editar |

`POST .../itens` aceita as duas formas de lançar:

```json
{ "peca_id": 18, "quantidade": 10 }                                  // do estoque
{ "descricao": "Correia 6PK 1200", "unidade": "PC", "quantidade": 2 } // escrito à mão
```
