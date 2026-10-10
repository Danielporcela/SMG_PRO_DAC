# Cadastro de Grupos de peças — como instalar

## O que veio no pacote

| Arquivo | O que fazer com ele |
|---|---|
| `models.py` | **substitui** o seu (é o mesmo arquivo, com o modelo `Grupo` no meio e a tela `grupos` na matriz de permissões) |
| `app.py` | **substitui** o seu (só ganhou 2 linhas: o import e o registro do módulo) |
| `routes/grupos.py` | arquivo **novo** — vai dentro da pasta `routes` |
| `templates/grupos.html` | arquivo **novo** — vai dentro da pasta `templates` |
| `migrar_grupos.py` | roda **uma vez** na raiz do projeto (mesma pasta do app.py) e pode apagar depois |

Ordem: subir os 4 arquivos → colocar o link no menu (item 1 abaixo) → rodar o
`migrar_grupos.py` → reiniciar.

---

## 1. O único ajuste manual: o link no menu (`templates/base.html`)

O `base.html` não veio nesta leva, então esse trechinho você cola.

Abra `templates/base.html`, procure a seção **Cadastros** do menu (onde estão
"Estoque de peças", "Funcionários", "Uniformes") e cole logo abaixo do item de
Estoque de peças:

```html
{% if pode('grupos') %}
<a class="item-menu {{ 'ativo' if tela == 'grupos' }}" href="/grupos">
  <i class="fa-solid fa-layer-group"></i> Grupos de peças
</a>
{% endif %}
```

Se as classes dos outros itens do seu menu forem diferentes, copie exatamente as
que estão no item "Estoque de peças" e troque só o `href`, o ícone e o texto.
O `href` é fixo (`/grupos`) de propósito: assim a página não quebra mesmo que
você suba o `base.html` antes dos outros arquivos.

---

## 2. Criar a tabela no banco

### No seu computador (Windows, banco SQLite)

1. Feche o sistema (Ctrl + C no terminal onde o Flask está rodando).
2. Abra o terminal na pasta do projeto:
   ```
   cd "C:\Users\asaph\OneDrive\Área de Trabalho\SGMF_Pro_DAC"
   ```
3. Rode:
   ```
   python migrar_grupos.py
   ```
4. Você vai ver algo assim:
   ```
   ✓ grupos: criada
   ✓ 6 grupo(s) trazido(s) das peças:
       - Arrefecimento
       - Elétrica
       - Freios
       ...
   Total de grupos cadastrados: 6
   ```
5. Suba o sistema de novo: `python app.py`

### No Render (banco PostgreSQL)

1. Suba os arquivos no GitHub e espere o deploy terminar.
2. No painel do Render, abra o serviço **SMG_PRO_DAC** → aba **Shell**.
3. Digite e dê Enter:
   ```
   python migrar_grupos.py
   ```
4. Confira a mesma saída acima. Depois é só atualizar a página do sistema.

> O script pode ser rodado de novo sem medo: se a tabela já existir, ele não
> mexe em nada; se você tiver criado peças com grupos novos, ele só acrescenta
> os que faltarem.

---

## 3. Como a tela funciona

Menu **Cadastros › Grupos de peças**:

- **Novo grupo** — digita o nome (ex.: `Arrefecimento`), uma descrição opcional
  e salva. É o cadastro manual que você pediu.
- **Trazer das peças** — botão de conveniência: varre as peças já cadastradas e
  cria automaticamente os grupos que ainda não estão na lista. Serve para não
  ter que redigitar o que já existe (o `migrar_grupos.py` já faz isso uma vez).
- **Editar** — muda o nome ou a descrição. Se você **renomear**, todas as peças
  que estavam no nome antigo são atualizadas junto, e o sistema avisa quantas
  foram. Ex.: corrigir `Eletrica` para `Elétrica` acerta as peças de uma vez.
- **Excluir** — só é permitido em grupo que **não tem nenhuma peça**. Se tiver,
  o sistema recusa e explica. Para tirar um grupo de circulação sem perder o
  histórico, use **Situação = Inativo**: ele some das opções, mas as peças
  antigas continuam com o nome gravado.
- A coluna **Peças** mostra quantas peças estão em cada grupo.

### Permissão

A tela nova é `grupos`. Quem tem **editar** cadastra e apaga; quem tem
**visualizar** só consulta. O cargo sugerido **Almoxarifado** já nasce com
`grupos: editar`. Se alguém não estiver enxergando a tela, ajuste em
**Cadastros › Usuários**.

> Atenção ao detalhe de sempre do sistema: perfil **Operador** recebe `editar`
> em toda tela nova por padrão. Se quiser que só o almoxarifado mexa nos
> grupos, grave `grupos: visualizar` na grade de quem só consulta.

---

## Decisão que ficou gravada no código (e por quê)

A peça continua guardando o grupo **pelo nome**, em texto, e não por um número
ligado a esta tabela nova.

Foi de propósito:

- nenhuma peça antiga precisa ser convertida;
- os relatórios que já filtram por grupo (inventário do estoque, por exemplo)
  continuam funcionando exatamente como estão;
- se um dia faltar cadastro, o campo ainda aceita um nome digitado à mão.

A tabela `grupos` é a **lista oficial** que alimenta as opções da tela. É por
isso que, ao renomear um grupo, o sistema atualiza as peças junto.

---

## O que ainda falta (me manda um arquivo e eu faço)

Hoje o campo **Grupo** dentro do cadastro da peça (tela Estoque) continua sendo
digitado livre. Para ele virar uma lista com os grupos cadastrados — podendo
escolher da lista **ou** digitar um novo na hora — preciso do arquivo:

- `templates/estoque.html`

Se quiser a mesma lista também no lançamento de OS ou nos filtros de relatório,
manda junto:

- `templates/manutencao.html`
- `templates/relatorios.html`
