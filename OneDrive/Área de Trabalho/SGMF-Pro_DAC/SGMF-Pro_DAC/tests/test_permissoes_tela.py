"""Controle de acesso por tela: perfil 'restrito', matriz de permissões
e os cargos de exemplo (mecânico, chefe de oficina, almoxarifado)."""
import pytest


def _criar(logado, email, perfil, senha, permissoes=None, cargo=None):
    dados = {"nome": email.split("@")[0].title(), "email": email,
             "perfil": perfil, "senha": senha}
    if permissoes is not None:
        dados["permissoes"] = permissoes
    if cargo:
        dados["cargo"] = cargo
    r = logado.post("/api/usuarios", json=dados)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _login(cliente, email, senha):
    r = cliente.post("/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.get_json()
    return r


# --------------------------------------------------------- perfil restrito
def test_restrito_sem_permissao_nao_ve_nada(logado, cliente):
    _criar(logado, "vazio@teste.local", "restrito", "senha123")
    logado.get("/logout")
    _login(cliente, "vazio@teste.local", "senha123")
    assert cliente.get("/api/veiculos").status_code == 403
    # a página principal também não abre — mostra o aviso, não quebra
    assert cliente.get("/").status_code == 403


def test_mecanico_so_visualiza_ordens_de_servico(logado, cliente, base):
    _criar(logado, "mecanico2@teste.local", "restrito", "senha123",
           permissoes=[{"tela": "manutencao", "nivel": "visualizar"}],
           cargo="Mecânico")
    logado.get("/logout")
    _login(cliente, "mecanico2@teste.local", "senha123")

    # vê a lista de OS
    assert cliente.get("/api/ordens").status_code == 200
    assert cliente.get("/manutencao").status_code == 200
    # não cria, edita nem exclui OS
    assert cliente.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).status_code == 403
    # não tem nenhuma outra tela liberada
    assert cliente.get("/api/veiculos").status_code == 403
    assert cliente.get("/veiculos").status_code in (403, 302)
    assert cliente.get("/api/pneus").status_code == 403


def test_chefe_de_oficina_edita_os_e_pneus_mas_nao_ve_veiculos(logado, cliente, base):
    _criar(logado, "chefe2@teste.local", "restrito", "senha123", permissoes=[
        {"tela": "dashboard", "nivel": "visualizar"},
        {"tela": "alertas", "nivel": "visualizar"},
        {"tela": "manutencao", "nivel": "editar"},
        {"tela": "pneus", "nivel": "editar"},
    ], cargo="Chefe de oficina")
    logado.get("/logout")
    _login(cliente, "chefe2@teste.local", "senha123")

    assert cliente.get("/").status_code == 200
    r = cliente.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]})
    assert r.status_code == 201
    assert cliente.post("/api/pneus", json={"numero_fogo": "PN-001"}).status_code == 201
    # cadastros de veículos/motoristas continuam fora do seu alcance
    assert cliente.get("/api/veiculos").status_code == 403
    assert cliente.get("/api/motoristas").status_code == 403


def test_almoxarifado_edita_estoque_mas_so_visualiza_manutencao(logado, cliente, base):
    _criar(logado, "almox2@teste.local", "restrito", "senha123", permissoes=[
        {"tela": "estoque", "nivel": "editar"},
        {"tela": "manutencao", "nivel": "visualizar"},
    ], cargo="Almoxarifado")
    logado.get("/logout")
    _login(cliente, "almox2@teste.local", "senha123")

    assert cliente.post("/api/pecas", json={"codigo": "X1", "descricao": "Peça teste"}).status_code == 201
    assert cliente.get("/api/ordens").status_code == 200
    assert cliente.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).status_code == 403


# ------------------------------------------------------ histórico imutável
def test_historico_de_movimentos_nunca_pode_ser_editado_ou_excluido(logado, base):
    """Nenhum perfil — nem administrador — tem como alterar um movimento já
    lançado: só existem rotas para listar e criar (entrada/saída/ajuste)."""
    logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"],
                                         "tipo": "entrada", "quantidade": 5})
    movimento = logado.get("/api/movimentos").get_json()[0]
    assert logado.put(f"/api/movimentos/{movimento['id']}", json={"quantidade": 999}).status_code == 404
    assert logado.delete(f"/api/movimentos/{movimento['id']}").status_code == 404


# --------------------------------------------------------------- redirecionamento
def test_usuario_sem_acesso_ao_dashboard_e_levado_para_a_primeira_tela_liberada(logado, cliente):
    _criar(logado, "somente_pneus@teste.local", "restrito", "senha123",
           permissoes=[{"tela": "pneus", "nivel": "visualizar"}])
    logado.get("/logout")
    _login(cliente, "somente_pneus@teste.local", "senha123")
    r = cliente.get("/", follow_redirects=True)
    assert r.status_code == 200
    assert b"Pneus" in r.data


# --------------------------------------------------------- matriz no cadastro
def test_admin_le_a_matriz_de_permissoes_do_usuario_criado(logado):
    criado = _criar(logado, "consulta_matriz@teste.local", "restrito", "senha123",
                    permissoes=[{"tela": "veiculos", "nivel": "editar"},
                                {"tela": "pneus", "nivel": "visualizar"}])
    assert criado["permissoes"]["veiculos"] == "editar"
    assert criado["permissoes"]["pneus"] == "visualizar"
    assert criado["permissoes"]["motoristas"] == "nenhum"

    relido = logado.get(f"/api/usuarios/{criado['id']}").get_json()
    assert relido["permissoes"]["veiculos"] == "editar"


def test_operador_sem_matriz_explicita_continua_com_acesso_total(logado):
    """Compatibilidade: criar um 'operador' sem enviar `permissoes` continua
    liberando tudo, como acontecia antes desta funcionalidade existir."""
    criado = _criar(logado, "operador_legado@teste.local", "operador", "senha123")
    assert criado["permissoes"]["veiculos"] == "editar"
    assert criado["permissoes"]["manutencao"] == "editar"


def test_lista_de_telas_e_cargos_sugeridos(logado):
    r = logado.get("/api/telas")
    assert r.status_code == 200
    dados = r.get_json()
    chaves = {t["chave"] for t in dados["telas"]}
    assert "manutencao" in chaves and "usuarios" not in chaves
    assert "Mecânico" in dados["cargos_sugeridos"]
    assert "Chefe de oficina" in dados["cargos_sugeridos"]


def test_apenas_admin_consulta_a_lista_de_telas(logado, cliente):
    _criar(logado, "naoadmin@teste.local", "operador", "senha123")
    logado.get("/logout")
    _login(cliente, "naoadmin@teste.local", "senha123")
    assert cliente.get("/api/telas").status_code == 403
