# Licenciamento por módulo — "TV por assinatura" — como instalar

## A ideia

Hoje o perfil `admin` sempre vê tudo. Isso passa a valer só para o que a
**empresa contratou**:

- **Controle de frota** (tudo que já existe hoje) → sempre incluído, nunca trava.
- **Módulo administrativo** (telas `usuarios`, `auditoria`,
  `auditoria_estoque_os`, `notificacoes`) → só funciona depois que **você**
  roda o comando de liberação. Nem o admin da empresa consegue destravar
  isso por conta própria — é exatamente como o pacote de futebol da TV
  paga: quem não assinou, não vê o canal.

Isso é **separado** da matriz de permissões por tela que já existe (aquela
decide o que cada *usuário* vê dentro do que a *empresa* contratou; esta
aqui decide o que a *empresa* contratou).

## O que já está pronto

| Arquivo | O que fazer |
|---|---|
| `migrar_licencas.py` | arquivo novo — copiar e rodar uma vez, pode apagar depois |

Os ajustes abaixo são em arquivos que já existem no seu projeto, então venho
como trechos para colar (não como arquivo inteiro, pra não sobrescrever
suas outras mudanças).

Ordem: 1 → 6 abaixo, depois `python migrar_licencas.py`, reiniciar.

## 1. `models.py` — o modelo e a função de checagem

Cole no final do arquivo:

```python
# ============================================================================
# Licenciamento por módulo
# ----------------------------------------------------------------------------
# "Controle de frota" é a base e nunca trava. Módulos extras (ex.:
# "administrativo") só ficam liberados depois que o desenvolvedor confirma
# o pagamento e roda `flask licenca liberar <modulo>`. Diferente da matriz
# de PermissaoAcesso: aquela decide o que CADA USUÁRIO vê dentro do que a
# empresa contratou; esta decide o que a EMPRESA contratou — nem o perfil
# "admin" da empresa passa por cima disso.
# ============================================================================
MODULOS_BASE = {"frota"}  # sempre liberado, não precisa de linha em Licenca

MODULOS_SISTEMA = [
    ("frota", "Controle de frota (padrão)"),
    ("administrativo", "Módulo administrativo (usuários, auditoria, notificações)"),
]


class Licenca(db.Model):
    __tablename__ = "licencas"

    id = db.Column(db.Integer, primary_key=True)
    modulo = db.Column(db.String(40), unique=True, nullable=False)
    liberado = db.Column(db.Boolean, default=False, nullable=False)
    liberado_em = db.Column(db.DateTime)
    observacao = db.Column(db.String(200))  # ex.: nº do pedido/pagamento


def modulo_liberado(modulo):
    """True se a empresa contratou este módulo (frota é sempre True)."""
    if modulo in MODULOS_BASE:
        return True
    lic = Licenca.query.filter_by(modulo=modulo).first()
    return bool(lic and lic.liberado)
```

## 2. `routes/crud.py` — trava para as rotas de API

Junto dos outros decoradores (perto de `perfil_obrigatorio`):

```python
from models import modulo_liberado  # junto dos outros imports de models


def licenca_obrigatoria(modulo):
    """Trava de licenciamento: bloqueia mesmo para perfil admin da empresa.
    Só o desenvolvedor libera (flask licenca liberar <modulo>)."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("usuario_id"):
                return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
            if not modulo_liberado(modulo):
                return jsonify({"erro": "Este módulo não está incluído na sua licença."}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator
```

Depois, adicione a linha `@licenca_obrigatoria("administrativo")` **acima**
de cada `@perfil_obrigatorio("admin")` que protege as rotas de usuários,
auditoria e notificações:

| Arquivo | Linha aproximada |
|---|---|
| `routes/auth.py` | 136 |
| `routes/extras.py` | 455, 474, 489 |
| `routes/api.py` | 1025, 1050, 1058 |

Exemplo de como fica:

```python
@licenca_obrigatoria("administrativo")
@perfil_obrigatorio("admin")
def sua_rota_existente(...):
    ...
```

## 3. `routes/paginas.py` — trava para as páginas HTML

No topo do arquivo, junto de `TELAS_SOMENTE_ADMIN`:

```python
from models import modulo_liberado

# Telas do "módulo administrativo" contratável separadamente.
TELA_MODULO = {
    "usuarios": "administrativo",
    "auditoria": "administrativo",
    "auditoria_estoque_os": "administrativo",
    "notificacoes": "administrativo",
}
```

Dentro de `exige_tela`, logo depois do bloco `if tela in TELAS_SOMENTE_ADMIN:`,
acrescente a checagem de licença (ela vale mesmo para quem já passou pela
checagem de perfil admin):

```python
            if tela in TELA_MODULO and not modulo_liberado(TELA_MODULO[tela]):
                return render_template(
                    "erro.html", codigo=403,
                    mensagem="Este módulo não está incluído na licença "
                             "deste sistema. Fale com o suporte para "
                             "contratar."), 403
```

## 4. `app.py` — expor `licenciado()` pro menu e criar o comando de liberação

No `context_processor` `permissoes_padrao`, junto do `return`:

```python
        from models import modulo_liberado as _modulo_liberado
        return {"pode": pode, "pode_decidir_compra": pode_decidir_compra,
                "licenciado": _modulo_liberado}
```

E, fora de `create_app`/perto do fim do arquivo, o comando de linha de
comando — é o que você vai rodar no Shell do Render depois que o cliente
pagar (mesmo lugar onde você já rodou `flask db upgrade`):

```python
@app.cli.group("licenca")
def cli_licenca():
    """Liberar/bloquear módulos contratados por esta empresa."""


@cli_licenca.command("listar")
def licenca_listar():
    from models import Licenca, MODULOS_BASE, MODULOS_SISTEMA
    for modulo, rotulo in MODULOS_SISTEMA:
        if modulo in MODULOS_BASE:
            print(f"[sempre liberado] {rotulo}")
            continue
        lic = Licenca.query.filter_by(modulo=modulo).first()
        status = "LIBERADO" if lic and lic.liberado else "travado"
        print(f"[{status}] {rotulo}")


@cli_licenca.command("liberar")
@click.argument("modulo")
def licenca_liberar(modulo):
    from models import Licenca
    from services.tempo import agora
    lic = Licenca.query.filter_by(modulo=modulo).first()
    if not lic:
        lic = Licenca(modulo=modulo)
        db.session.add(lic)
    lic.liberado = True
    lic.liberado_em = agora()
    db.session.commit()
    print(f"✓ módulo '{modulo}' liberado")


@cli_licenca.command("bloquear")
@click.argument("modulo")
def licenca_bloquear(modulo):
    from models import Licenca
    lic = Licenca.query.filter_by(modulo=modulo).first()
    if lic:
        lic.liberado = False
        db.session.commit()
    print(f"✓ módulo '{modulo}' bloqueado")
```

Isso exige `import click` no topo do `app.py` (o Flask já traz o `click`
como dependência, então não precisa instalar nada novo).

## 5. `templates/base.html` — some com o item do menu se não tiver licença

No bloco das telas exclusivas do administrador (Usuários, Auditoria,
Notificações), envolva com a checagem de licença por fora da checagem de
perfil que já existe:

```html
{% if licenciado('administrativo') %}
  {% if session.get('perfil') == 'admin' %}
    <a class="item-menu {{ 'ativo' if tela == 'usuarios' }}" href="/usuarios">
      <i class="fa-solid fa-users-gear"></i> Usuários
    </a>
    <!-- ... auditoria, auditoria_estoque_os, notificacoes, mesma lógica ... -->
  {% endif %}
{% endif %}
```

(mantenha a checagem de perfil admin que já existe hoje — a de licença é
uma trava *adicional*, por fora, não uma substituta.)

## 6. Rodar a migração e testar

```
python migrar_licencas.py
```

No Render, isso é no Shell do serviço (mesmo lugar do `flask db upgrade`
que você já usou antes).

Depois, com o módulo travado (padrão), confira:
- o item "Usuários" **desaparece** do menu, mesmo logado como admin;
- acessar `/usuarios` direto pela URL devolve a tela de erro 403;
- chamar a API de usuários devolve `{"erro": "Este módulo não está
  incluído na sua licença."}`.

Quando o cliente pagar o pacote completo, no Shell do Render:

```
flask licenca liberar administrativo
```

E para revogar (ex.: assinatura vencida, cliente não renovou):

```
flask licenca bloquear administrativo
```

`flask licenca listar` mostra o status de tudo.

## Para o próximo módulo pago que você criar

Não precisa repetir a arquitetura — só:
1. adicionar a linha do módulo em `MODULOS_SISTEMA` (`models.py`);
2. usar `@licenca_obrigatoria("nome_do_modulo")` nas rotas de API dele;
3. mapear as telas dele em `TELA_MODULO` (`routes/paginas.py`);
4. envolver o item de menu dele com `{% if licenciado('nome_do_modulo') %}`.

O `flask licenca liberar/bloquear` já funciona pra qualquer módulo que você
cadastrar — é só trocar o nome no comando.
