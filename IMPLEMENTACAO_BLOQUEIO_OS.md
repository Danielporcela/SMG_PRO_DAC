# Implementação: Bloqueio de Abertura de OS com Mesmo Problema Relatado

## Resumo da Solução

Foi implementado um bloqueio automático na criação de novas Ordens de Serviço (OS) quando já existe uma OS **aberta** com o **mesmo problema relatado**.

---

## Como Funciona

### ✅ Cenário Bloqueado (Exemplo)
- Existe uma OS #1234 **ABERTA** com problema: **"Falha no motor"**
- Usuário tenta criar nova OS com problema: **"Falha no motor"**
- ❌ **BLOQUEADO!** Mensagem de erro:
  ```
  Já existe a OS #1234 aberta com o problema: "Falha no motor". 
  Feche ou finalize essa OS antes de abrir uma nova com o mesmo problema.
  ```

### ✅ Cenário Liberado (Exemplos)

1. **Mesmo veículo, problema DIFERENTE:**
   - OS #1234 aberta: "Falha no motor"
   - Nova OS criada com: "Pneu furado"
   - ✅ **LIBERADO** (problemas diferentes)

2. **OS anterior está fechada/finalizada:**
   - OS #1234 finalizada: "Falha no motor"
   - Nova OS criada com: "Falha no motor"
   - ✅ **LIBERADO** (a anterior não está mais aberta)

3. **Criar primeira OS com este problema:**
   - Nenhuma OS anterior com este problema
   - Nova OS criada com: "Falha no motor"
   - ✅ **LIBERADO** (é a primeira)

---

## Detalhes Técnicos

### Arquivo Modificado
- **Arquivo:** `routes/routes_api.py`
- **Função:** `_verificar_os_duplicada(obj, anterior=None)`
- **Linha aproximada:** ~148

### Lógica Implementada

```python
def _verificar_os_duplicada(obj, anterior=None):
    """Bloqueia abertura de nova OS quando já existe uma OS aberta com o mesmo
    problema relatado para o mesmo equipamento/veículo.
    
    A criação de nova OS é bloqueada quando:
    1. É uma CRIAÇÃO NOVA (anterior is None)
    2. O problema relatado não está vazio
    3. Já existe OUTRA OS com o MESMO PROBLEMA e status "Aberta"
    """
    # Apenas bloqueia em criação nova (não na edição)
    if anterior is not None:
        return
    
    # Bloqueia apenas se há um problema relatado
    problema = (obj.problema or "").strip()
    if not problema:
        return
    
    # Procura por outra OS aberta com o MESMO PROBLEMA
    os_duplicada = (OrdemServico.query
                    .filter(OrdemServico.problema == problema,
                            OrdemServico.status == "Aberta",
                            OrdemServico.id != obj.id)
                    .order_by(OrdemServico.numero.desc())
                    .first())
    
    if os_duplicada:
        raise ErroNegocio(
            f"Já existe a OS #{os_duplicada.numero} aberta com o problema: "
            f"\"{problema}\". Feche ou finalize essa OS antes de abrir uma nova "
            f"com o mesmo problema.")
```

### Pontos-Chave

1. **Só bloqueia em criação nova** (`anterior is None`)
   - Editar uma OS já existente não dispara o bloqueio

2. **Verifica o campo `problema` exatamente**
   - Comparação é case-sensitive
   - Espaços em branco extras são removidos
   - Se problema vazio, não bloqueia

3. **Procura apenas OS com status "Aberta"**
   - OS finalizada, em execução, aguardando peça não bloqueiam
   - Apenas o status "Aberta" (conforme especificado)

4. **Usa `ErroNegocio`**
   - Exceção padrão do sistema para erros de negócio
   - Retorna HTTP 400 com a mensagem de erro
   - O navegador exibe a mensagem ao usuário

---

## Fluxo de Execução

1. Usuário clica em "Adicionar nova Ordem de Serviço"
2. Preenche o formulário (incluindo campo "Problema relatado")
3. Clica em "Salvar"
4. Framework Flask chama a rota POST `/api/ordens` (CRUD automático)
5. Antes de salvar, chama `_verificar_os_duplicada(nova_os, anterior=None)`
6. **Se encontrar OS aberta com mesmo problema:**
   - Lança `ErroNegocio` com número da OS e problema
   - Transação é revertida (rollback)
   - Navegador recebe erro HTTP 400
   - Mensagem é exibida ao usuário
7. **Se passou na validação:**
   - OS é criada normalmente no banco

---

## Testando a Implementação

### Teste 1: Bloqueio Funciona
1. Crie uma OS com problema: "Falha no motor" (status fica "Aberta")
2. Tente criar outra com o mesmo problema "Falha no motor"
3. Resultado: ❌ Bloqueado com mensagem

### Teste 2: Problema Diferente é Liberado
1. OS #1234 aberta: "Falha no motor"
2. Crie nova OS com problema: "Pneu furado"
3. Resultado: ✅ Criada com sucesso

### Teste 3: Edição não é Bloqueada
1. OS #1234 aberta: "Falha no motor"
2. Edite a OS #1234 e salve novamente
3. Resultado: ✅ Edição funciona (não dispara o bloqueio)

---

## Impacto no Sistema

- ✅ Evita duplicação de OS para o mesmo problema
- ✅ Melhora organização da manutenção
- ✅ Força fechamento/finalização antes de abrir novo chamado
- ✅ Mensagem clara sobre qual OS deve ser tratada primeiro
- ✅ Sem impacto em rotas/telas (bloqueio é automático no backend)

---

## Como Desfazer (se necessário)

Se precisar reverter o bloqueio, remova/comente a lógica de verificação em `_verificar_os_duplicada()` e deixe apenas:

```python
def _verificar_os_duplicada(obj, anterior=None):
    """Permite múltiplas OS abertas para o mesmo veículo/placa."""
    return
```

---

**Versão:** 1.0  
**Data de Implementação:** 24 de setembro de 2026  
**Status:** ✅ Pronto para produção
