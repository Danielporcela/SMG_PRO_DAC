"""Modelos de dados do SGMF Pro.

Cada módulo do sistema tem seu próprio conjunto de tabelas, mas todas
compartilham a mesma sessão do SQLAlchemy (extensions.db).
"""
import secrets
from datetime import date, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from services.tempo import agora as _agora
from services.tempo import hoje as _hoje


# ============================================================================
# Controle de acesso por tela
# ----------------------------------------------------------------------------
# Cada tela do sistema pode ser liberada, por usuário, em três níveis:
#   nenhum      -> a tela nem aparece no menu e a API recusa (403)
#   visualizar  -> lista e abre registros, mas não cria/edita/exclui
#   editar      -> acesso completo à tela (criar, editar, excluir)
#
# "usuarios", "auditoria" e "notificacoes" ficam de fora dessa matriz: são
# telas de administração do próprio sistema (login de outras pessoas, trilha
# de auditoria, configuração de e-mail) e continuam exclusivas de quem tem
# perfil "admin" — do contrário, um usuário comum poderia se auto-promover.
# ============================================================================
TELAS_SISTEMA = [
    ("dashboard", "Painel", "Operação"),
    ("alertas", "Alertas", "Operação"),
    ("manutencao", "Ordens de serviço", "Operação"),
    ("compras", "Ordens de compra", "Operação"),
    ("combustivel", "Abastecimentos", "Operação"),
    ("pneus", "Pneus", "Operação"),
    ("veiculos", "Veículos", "Cadastros"),
    ("motoristas", "Motoristas", "Cadastros"),
    ("fornecedores", "Oficinas e postos", "Cadastros"),
    ("estoque", "Estoque de peças", "Cadastros"),
    ("grupos", "Grupos de peças", "Cadastros"),
    ("importacao", "Importar planilha", "Cadastros"),
    ("orcamento", "Meta x realizado", "Gestão"),
    ("ranking", "Rankings", "Gestão"),
    ("relatorios", "Relatórios", "Gestão"),
    ("funcionarios", "Funcionários", "Cadastros"),
    ("uniformes", "Uniformes", "Cadastros"),
]
TELAS_VALIDAS = {chave for chave, _, _ in TELAS_SISTEMA}
TELAS_ROTULOS = {chave: rotulo for chave, rotulo, _ in TELAS_SISTEMA}

NIVEIS_ACESSO = ("nenhum", "visualizar", "editar")
PESO_NIVEL = {"nenhum": 0, "visualizar": 1, "editar": 2}

# Perfil-base: o que o usuário enxerga em qualquer tela que NÃO tenha uma
# linha própria em PermissaoAcesso. Ao gravar uma permissão específica para
# uma tela, ela passa a valer no lugar deste padrão só para aquela tela.
PADRAO_POR_PERFIL = {
    "admin": "editar",       # administrador nunca é restringido pela matriz
    "operador": "editar",    # padrão antigo do sistema: lança e edita tudo
    "consulta": "visualizar",  # padrão antigo do sistema: só visualiza
    "restrito": "nenhum",    # começa sem nada — libere tela por tela
}

# Sugestões prontas para o cargo mais comum de cada função. São só um ponto
# de partida: o administrador pode ajustar tela a tela antes de salvar.
CARGOS_SUGERIDOS = {
    "Administrador": {"perfil": "admin", "permissoes": {}},
    "Gerente operacional": {
        "perfil": "operador",  # acesso total às telas operacionais
        "permissoes": {},
    },
    "Almoxarifado": {
        "perfil": "restrito",
        "permissoes": {
            "dashboard": "visualizar", "estoque": "editar", "fornecedores": "editar",
            "manutencao": "visualizar", "pneus": "visualizar", "veiculos": "visualizar",
            "importacao": "editar", "relatorios": "visualizar", "compras": "editar",
            "grupos": "editar",
        },
    },
    # Quem aprova e efetiva a compra. 'compras' em nível 'editar' é o que
    # libera os botões Aprovar / Reprovar / Marcar como comprada.
    "Financeiro / compras": {
        "perfil": "restrito",
        "permissoes": {
            "dashboard": "visualizar", "compras": "editar", "estoque": "visualizar",
            "fornecedores": "visualizar", "relatorios": "visualizar",
            "orcamento": "visualizar",
        },
    },
    "Chefe de oficina": {
        "perfil": "restrito",
        "permissoes": {
            "dashboard": "visualizar", "alertas": "visualizar",
            "manutencao": "editar", "pneus": "editar",
        },
    },
    "Mecânico": {
        "perfil": "restrito",
        "permissoes": {"manutencao": "visualizar"},
    },
    "Motorista / consulta": {
        "perfil": "restrito",
        "permissoes": {"dashboard": "visualizar", "manutencao": "visualizar",
                       "pneus": "visualizar", "veiculos": "visualizar"},
    },
    "Personalizado": {"perfil": "restrito", "permissoes": {}},
}


class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(20), default="operador")  # admin | operador | consulta | restrito
    cargo = db.Column(db.String(60))  # rótulo livre: Mecânico, Chefe de oficina... (não afeta permissão)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=_agora)

    # --- recuperação de senha ("Esqueceu a senha?") ---------------------
    token_reset = db.Column(db.String(64), unique=True, nullable=True, index=True)
    token_reset_expira = db.Column(db.DateTime, nullable=True)

    # --- controle de acesso por tela --------------------------------------
    def permissoes_mapa(self):
        """Devolve {tela: nivel} já resolvido: linha específica > padrão do perfil."""
        padrao = PADRAO_POR_PERFIL.get(self.perfil, "nenhum")
        mapa = {chave: padrao for chave in TELAS_VALIDAS}
        if self.perfil != "admin":
            for p in self.permissoes:
                if p.tela in TELAS_VALIDAS:
                    mapa[p.tela] = p.nivel
        else:
            mapa = {chave: "editar" for chave in TELAS_VALIDAS}
        return mapa

    def nivel_em(self, tela):
        if self.perfil == "admin":
            return "editar"
        for p in self.permissoes:
            if p.tela == tela:
                return p.nivel
        return PADRAO_POR_PERFIL.get(self.perfil, "nenhum")

    def tem_acesso(self, tela, nivel_minimo="visualizar"):
        return PESO_NIVEL.get(self.nivel_em(tela), 0) >= PESO_NIVEL.get(nivel_minimo, 1)

    def primeira_tela_liberada(self):
        for chave, _, _ in TELAS_SISTEMA:
            if self.tem_acesso(chave, "visualizar"):
                return chave
        return None

    def definir_permissoes(self, lista):
        """Substitui todas as permissões do usuário pela lista informada.

        `lista` é [{"tela": ..., "nivel": ...}, ...]. Telas fora de
        TELAS_VALIDAS ou níveis inválidos são ignorados silenciosamente.
        """
        self.permissoes = []
        # As linhas antigas precisam ser removidas do banco ANTES de inserir
        # as novas: sem este flush, o SQLAlchemy pode tentar inserir a linha
        # nova (mesma tela) antes de apagar a antiga, o que viola a
        # restrição de unicidade (usuario_id, tela) — uq_permissao_usuario_tela
        # — e derruba a edição com IntegrityError.
        db.session.flush()
        for item in lista or []:
            tela = (item.get("tela") or "").strip()
            nivel = (item.get("nivel") or "nenhum").strip()
            if tela in TELAS_VALIDAS and nivel in NIVEIS_ACESSO and nivel != "nenhum":
                self.permissoes.append(PermissaoAcesso(tela=tela, nivel=nivel))

    def definir_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def conferir_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

    def gerar_token_reset(self):
        """Cria um token único válido por 1 hora e devolve o token puro."""
        token = secrets.token_urlsafe(32)
        self.token_reset = token
        self.token_reset_expira = _agora() + timedelta(hours=1)
        return token

    def token_reset_valido(self, token):
        if self.token_reset != token or self.token_reset_expira is None:
            return False
        expira = self.token_reset_expira
        agora = _agora()
        # O SQLite grava o horário sem timezone; ao reler do banco a
        # comparação direta com um datetime "aware" (agora()) quebra.
        # Os dois representam o mesmo horário local, então basta igualar
        # a presença (ou ausência) de timezone antes de comparar.
        if expira.tzinfo is None:
            agora = agora.replace(tzinfo=None)
        return expira > agora

    def limpar_token_reset(self):
        self.token_reset = None
        self.token_reset_expira = None

    def to_dict(self):
        return {"id": self.id, "nome": self.nome, "email": self.email,
                "perfil": self.perfil, "cargo": self.cargo, "ativo": self.ativo,
                "permissoes": self.permissoes_mapa()}


class PermissaoAcesso(db.Model):
    """Uma linha = 'este usuário tem este nível nesta tela'.

    Só existem linhas para exceções ao padrão do perfil (ver
    PADRAO_POR_PERFIL); telas sem linha própria usam o padrão do perfil.
    """
    __tablename__ = "permissoes_acesso"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    tela = db.Column(db.String(30), nullable=False)
    nivel = db.Column(db.String(12), nullable=False, default="nenhum")

    usuario = db.relationship(
        "Usuario",
        backref=db.backref("permissoes", cascade="all, delete-orphan", lazy="selectin"))

    __table_args__ = (db.UniqueConstraint("usuario_id", "tela", name="uq_permissao_usuario_tela"),)

    def to_dict(self):
        return {"tela": self.tela, "rotulo": TELAS_ROTULOS.get(self.tela, self.tela),
                "nivel": self.nivel}


class Veiculo(db.Model):
    __tablename__ = "veiculos"
    id = db.Column(db.Integer, primary_key=True)
    prefixo = db.Column(db.String(20), unique=True, nullable=False, index=True)
    placa = db.Column(db.String(10), unique=True, nullable=False, index=True)
    marca = db.Column(db.String(60))
    modelo = db.Column(db.String(60))
    ano = db.Column(db.Integer)
    tipo = db.Column(db.String(40))            # ônibus, caminhão, van, utilitário...
    combustivel = db.Column(db.String(30), default="Diesel S10")
    centro_custo = db.Column(db.String(60))
    setor = db.Column(db.String(60))
    hodometro = db.Column(db.Float, default=0)
    horimetro = db.Column(db.Float, default=0)
    situacao = db.Column(db.String(30), default="Disponível")  # Disponível | Em manutenção | Inativo
    km_ultima_troca_oleo = db.Column(db.Float, default=0)
    intervalo_troca_oleo = db.Column(db.Float, default=10000)
    data_ultima_preventiva = db.Column(db.Date)
    intervalo_preventiva_dias = db.Column(db.Integer, default=90)
    orcamento_mensal = db.Column(db.Float, default=0)
    observacao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)

    @property
    def km_proxima_troca_oleo(self):
        return (self.km_ultima_troca_oleo or 0) + (self.intervalo_troca_oleo or 0)

    def to_dict(self):
        return {
            "id": self.id, "prefixo": self.prefixo, "placa": self.placa,
            "marca": self.marca, "modelo": self.modelo, "ano": self.ano,
            "tipo": self.tipo, "combustivel": self.combustivel,
            "centro_custo": self.centro_custo, "setor": self.setor,
            "hodometro": self.hodometro, "horimetro": self.horimetro,
            "situacao": self.situacao,
            "km_ultima_troca_oleo": self.km_ultima_troca_oleo,
            "intervalo_troca_oleo": self.intervalo_troca_oleo,
            "km_proxima_troca_oleo": self.km_proxima_troca_oleo,
            "data_ultima_preventiva": self.data_ultima_preventiva.isoformat() if self.data_ultima_preventiva else None,
            "intervalo_preventiva_dias": self.intervalo_preventiva_dias,
            "orcamento_mensal": self.orcamento_mensal,
            "observacao": self.observacao, "ativo": self.ativo,
            "identificacao": f"{self.prefixo} · {self.placa}",
        }


class Motorista(db.Model):
    __tablename__ = "motoristas"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    matricula = db.Column(db.String(30))
    cnh = db.Column(db.String(20))
    categoria_cnh = db.Column(db.String(5))
    validade_cnh = db.Column(db.Date)
    telefone = db.Column(db.String(20))
    setor = db.Column(db.String(60))
    ativo = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {"id": self.id, "nome": self.nome, "matricula": self.matricula,
                "cnh": self.cnh, "categoria_cnh": self.categoria_cnh,
                "validade_cnh": self.validade_cnh.isoformat() if self.validade_cnh else None,
                "telefone": self.telefone, "setor": self.setor, "ativo": self.ativo,
                "identificacao": self.nome}


class Fornecedor(db.Model):
    __tablename__ = "fornecedores"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(30), default="Oficina")  # Oficina | Fornecedor | Posto
    cnpj = db.Column(db.String(20))
    telefone = db.Column(db.String(20))
    cidade = db.Column(db.String(60))
    contato = db.Column(db.String(80))
    ativo = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {"id": self.id, "nome": self.nome, "tipo": self.tipo, "cnpj": self.cnpj,
                "telefone": self.telefone, "cidade": self.cidade, "contato": self.contato,
                "ativo": self.ativo, "identificacao": f"{self.nome} ({self.tipo})"}


class Grupo(db.Model):
    """Cadastro manual dos grupos de peças (Elétrica, Arrefecimento, Motor...).

    Detalhe importante: a peça continua guardando o grupo pelo NOME
    (`Peca.grupo` é texto), e não pelo id desta tabela. Isso foi de propósito —
    nenhuma peça antiga precisa ser convertida, os relatórios que filtram por
    grupo continuam funcionando igual, e o campo segue aceitando um nome
    digitado à mão quando faltar cadastro. Esta tabela é a lista oficial que
    alimenta as opções da tela.

    Por isso, ao renomear um grupo aqui, as peças que usavam o nome antigo são
    atualizadas junto (ver routes/grupos.py) — do contrário elas ficariam
    apontando para um nome que não existe mais.
    """
    __tablename__ = "grupos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(60), unique=True, nullable=False, index=True)
    descricao = db.Column(db.String(200))
    ativo = db.Column(db.Boolean, default=True)

    def quantidade_pecas(self):
        return db.session.query(Peca.id).filter(Peca.grupo == self.nome).count()

    def to_dict(self, com_contagem=True):
        return {"id": self.id, "nome": self.nome, "descricao": self.descricao,
                "ativo": self.ativo,
                "qtd_pecas": self.quantidade_pecas() if com_contagem else None,
                "identificacao": self.nome}


def nomes_de_grupos(somente_ativos=True):
    """Lista de nomes para preencher as opções de grupo nas outras telas."""
    consulta = Grupo.query
    if somente_ativos:
        consulta = consulta.filter(Grupo.ativo.is_(True))
    return [g.nome for g in consulta.order_by(Grupo.nome).all()]


def importar_grupos_das_pecas():
    """Cadastra automaticamente os grupos que já aparecem nas peças.

    Usada na instalação do módulo (migrar_grupos.py) e no botão "Trazer das
    peças" da tela. Não duplica: compara ignorando maiúsculas e espaços.
    Devolve a lista de nomes que foram criados agora.
    """
    existentes = {(g.nome or "").strip().lower() for g in Grupo.query.all()}
    criados = []
    for (nome,) in db.session.query(Peca.grupo).distinct().all():
        nome = (nome or "").strip()
        if not nome or nome.lower() in existentes:
            continue
        db.session.add(Grupo(nome=nome, ativo=True))
        existentes.add(nome.lower())
        criados.append(nome)
    if criados:
        db.session.commit()
    return sorted(criados)


class Peca(db.Model):
    """Módulo 11 — estoque de peças."""
    __tablename__ = "pecas"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False, index=True)
    referencia = db.Column(db.String(60))  # número do fabricante/fornecedor, livre para ela digitar
    descricao = db.Column(db.String(160), nullable=False)
    grupo = db.Column(db.String(40))       # Motor, Suspensão, Freios, ...
    unidade = db.Column(db.String(10), default="UN")
    quantidade = db.Column(db.Float, default=0)
    estoque_minimo = db.Column(db.Float, default=0)
    custo_unitario = db.Column(db.Float, default=0)
    localizacao = db.Column(db.String(40))
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"))
    ncm = db.Column(db.String(8))
    cfop_entrada = db.Column(db.String(4))
    cst_icms = db.Column(db.String(3))
    cst_pis = db.Column(db.String(2))
    cst_cofins = db.Column(db.String(2))
    cst_ibs_cbs = db.Column(db.String(3))
    classificacao_tributaria = db.Column(db.String(6))
    fornecedor = db.relationship("Fornecedor")

    def to_dict(self):
        return {"id": self.id, "codigo": self.codigo, "referencia": self.referencia,
                "descricao": self.descricao,
                "grupo": self.grupo, "unidade": self.unidade, "quantidade": self.quantidade,
                "estoque_minimo": self.estoque_minimo, "custo_unitario": self.custo_unitario,
                "valor_total": round((self.quantidade or 0) * (self.custo_unitario or 0), 2),
                "localizacao": self.localizacao, "fornecedor_id": self.fornecedor_id,
                "fornecedor_nome": self.fornecedor.nome if self.fornecedor else None,
                "ncm": self.ncm, "cfop_entrada": self.cfop_entrada,
                "cst_icms": self.cst_icms, "cst_pis": self.cst_pis,
                "cst_cofins": self.cst_cofins, "cst_ibs_cbs": self.cst_ibs_cbs,
                "classificacao_tributaria": self.classificacao_tributaria,
                "abaixo_minimo": bool(self.estoque_minimo) and (self.quantidade or 0) <= (self.estoque_minimo or 0),
                "identificacao": f"{self.codigo} · {self.descricao}"}


def proximo_codigo_peca():
    """Próximo código sequencial (0001, 0002...), sem repetir nem mexer nos
    códigos manuais já usados (ex.: 'FIL-001'). Continua a partir do maior
    número puro já cadastrado — se não houver nenhum, começa em 0001.
    """
    maior = 0
    for (codigo,) in db.session.query(Peca.codigo).all():
        if codigo and codigo.strip().isdigit():
            maior = max(maior, int(codigo))
    return f"{maior + 1:04d}"


class MovimentoEstoque(db.Model):
    __tablename__ = "movimentos_estoque"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, default=_hoje)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    tipo = db.Column(db.String(10), default="entrada")  # entrada | saida | ajuste
    quantidade = db.Column(db.Float, default=0)
    custo_unitario = db.Column(db.Float, default=0)
    documento = db.Column(db.String(60))
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey("ordens_servico.id"))
    observacao = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer)
    usuario_nome = db.Column(db.String(120))
    peca = db.relationship("Peca")

    def to_dict(self):
        return {"id": self.id, "data": self.data.isoformat() if self.data else None,
                "peca_id": self.peca_id,
                "peca_descricao": f"{self.peca.codigo} · {self.peca.descricao}" if self.peca else None,
                "tipo": self.tipo, "quantidade": self.quantidade,
                "custo_unitario": self.custo_unitario,
                "valor_total": round((self.quantidade or 0) * (self.custo_unitario or 0), 2),
                "documento": self.documento, "ordem_servico_id": self.ordem_servico_id,
                "observacao": self.observacao, "usuario_id": self.usuario_id,
                "usuario_nome": self.usuario_nome}


class PecaSerial(db.Model):
    """Estrutura legada de rastreio individual.

    Mantida somente para preservar dados de instalações anteriores. Novos
    produtos, entradas e ordens de serviço são controlados por quantidade e
    não exigem número de série.
    """
    __tablename__ = "pecas_serial"
    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    numero_serie = db.Column(db.String(60), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default="Estoque")  # Estoque | Em uso | Descartado
    veiculo_atual_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"))
    ordem_servico_atual_id = db.Column(db.Integer, db.ForeignKey("ordens_servico.id"))
    data_entrada = db.Column(db.Date, default=_hoje)
    custo_unitario = db.Column(db.Float, default=0)
    # De onde a unidade entrou: "Cadastro manual" ou "Nota fiscal".
    origem = db.Column(db.String(30))
    documento_origem = db.Column(db.String(60))
    peca = db.relationship("Peca")
    veiculo_atual = db.relationship("Veiculo")
    ordem_servico_atual = db.relationship("OrdemServico")

    def to_dict(self):
        return {
            "id": self.id, "peca_id": self.peca_id,
            "peca_codigo": self.peca.codigo if self.peca else None,
            "peca_descricao": self.peca.descricao if self.peca else None,
            "numero_serie": self.numero_serie, "status": self.status,
            "veiculo_atual_id": self.veiculo_atual_id,
            "veiculo_atual_nome": (f"{self.veiculo_atual.prefixo} · {self.veiculo_atual.placa}"
                                   if self.veiculo_atual else None),
            "ordem_servico_atual_id": self.ordem_servico_atual_id,
            "ordem_servico_atual_numero": (self.ordem_servico_atual.numero
                                           if self.ordem_servico_atual else None),
            "data_entrada": self.data_entrada.isoformat() if self.data_entrada else None,
            "custo_unitario": self.custo_unitario, "origem": self.origem,
            "documento_origem": self.documento_origem,
            "identificacao": f"{self.numero_serie}" + (f" · {self.peca.descricao}" if self.peca else ""),
        }


class MovimentoPecaSerial(db.Model):
    """Histórico completo de uma unidade de peça — é aqui que mora o
    rastreio: quando entrou, em qual OS/veículo foi instalada, quando foi
    removida, se voltou ao estoque e foi reinstalada em outro lugar, ou se
    foi descartada.
    """
    __tablename__ = "movimentos_peca_serial"
    id = db.Column(db.Integer, primary_key=True)
    peca_serial_id = db.Column(db.Integer, db.ForeignKey("pecas_serial.id"), nullable=False)
    data = db.Column(db.Date, default=_hoje)
    tipo = db.Column(db.String(20))  # Entrada | Instalação | Remoção | Descarte
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"))
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey("ordens_servico.id"))
    km_veiculo = db.Column(db.Float)
    usuario = db.Column(db.String(80))
    observacao = db.Column(db.String(200))
    peca_serial = db.relationship("PecaSerial", backref=db.backref(
        "movimentos", cascade="all, delete-orphan", lazy="selectin",
        order_by="MovimentoPecaSerial.id"))
    veiculo = db.relationship("Veiculo")
    ordem_servico = db.relationship("OrdemServico")

    def to_dict(self):
        return {
            "id": self.id, "peca_serial_id": self.peca_serial_id,
            "data": self.data.isoformat() if self.data else None,
            "tipo": self.tipo,
            "veiculo_id": self.veiculo_id,
            "veiculo_nome": (f"{self.veiculo.prefixo} · {self.veiculo.placa}"
                             if self.veiculo else None),
            "ordem_servico_id": self.ordem_servico_id,
            "ordem_servico_numero": self.ordem_servico.numero if self.ordem_servico else None,
            "km_veiculo": self.km_veiculo, "usuario": self.usuario,
            "observacao": self.observacao,
        }


class ItemOSPecaSerial(db.Model):
    """Vínculo legado entre item da OS e unidade rastreada individualmente.

    Mantido para que ordens antigas continuem podendo ser removidas sem
    corromper o estoque. Novos itens não criam este vínculo.
    """
    __tablename__ = "itens_os_pecas_serial"
    id = db.Column(db.Integer, primary_key=True)
    item_os_id = db.Column(db.Integer, db.ForeignKey("itens_os.id"), nullable=False)
    peca_serial_id = db.Column(db.Integer, db.ForeignKey("pecas_serial.id"), nullable=False)
    item_os = db.relationship("ItemOS", backref=db.backref(
        "pecas_serial", cascade="all, delete-orphan", lazy="selectin"))
    peca_serial = db.relationship("PecaSerial")

    def to_dict(self):
        return {"id": self.id, "item_os_id": self.item_os_id,
                "peca_serial_id": self.peca_serial_id,
                "numero_serie": self.peca_serial.numero_serie if self.peca_serial else None}


class NotaFiscal(db.Model):
    """Módulo 11 — lançamento de notas fiscais de entrada de peças.

    A nota nasce em status 'Aberta': dá para lançar e remover itens à
    vontade, sem afetar o estoque. Só ao finalizar (ação explícita) é que
    cada item vira uma entrada em MovimentoEstoque e o saldo da peça sobe —
    do jeito que acontece na prática, quando a nota chega e é conferida no
    almoxarifado antes de dar entrada.
    """
    __tablename__ = "notas_fiscais"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), nullable=False, index=True)
    serie = db.Column(db.String(10))
    data_emissao = db.Column(db.Date, default=_hoje)
    data_entrada = db.Column(db.Date)      # preenchida ao finalizar
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"), nullable=False)
    status = db.Column(db.String(20), default="Aberta")  # Aberta | Finalizada | Cancelada
    observacao = db.Column(db.String(200))
    fornecedor = db.relationship("Fornecedor")
    itens = db.relationship("ItemNotaFiscal", backref="nota", cascade="all, delete-orphan",
                            lazy="selectin")

    @property
    def valor_total(self):
        return round(sum((i.quantidade or 0) * (i.valor_unitario or 0) for i in self.itens), 2)

    def _total_fiscal(self, campo):
        return round(sum(getattr(i, campo, 0) or 0 for i in self.itens), 2)

    def to_dict(self, com_itens=False):
        valor_icms = self._total_fiscal("valor_icms")
        valor_pis = self._total_fiscal("valor_pis")
        valor_cofins = self._total_fiscal("valor_cofins")
        valor_ibs = self._total_fiscal("valor_ibs")
        valor_cbs = self._total_fiscal("valor_cbs")
        d = {
            "id": self.id, "numero": self.numero, "serie": self.serie,
            "data_emissao": self.data_emissao.isoformat() if self.data_emissao else None,
            "data_entrada": self.data_entrada.isoformat() if self.data_entrada else None,
            "fornecedor_id": self.fornecedor_id,
            "fornecedor_nome": self.fornecedor.nome if self.fornecedor else None,
            "status": self.status, "observacao": self.observacao,
            "valor_total": self.valor_total, "qtd_itens": len(self.itens),
            "valor_icms": valor_icms, "valor_pis": valor_pis, "valor_cofins": valor_cofins,
            "valor_ibs": valor_ibs, "valor_cbs": valor_cbs,
            "valor_tributos": round(valor_icms + valor_pis + valor_cofins + valor_ibs + valor_cbs, 2),
            "identificacao": f"NF {self.numero}" + (f"/{self.serie}" if self.serie else ""),
        }
        if com_itens:
            d["itens"] = [i.to_dict() for i in self.itens]
        return d


class ItemNotaFiscal(db.Model):
    __tablename__ = "itens_nota_fiscal"
    id = db.Column(db.Integer, primary_key=True)
    nota_fiscal_id = db.Column(db.Integer, db.ForeignKey("notas_fiscais.id"), nullable=False)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    descricao = db.Column(db.String(160))
    quantidade = db.Column(db.Float, default=1)
    valor_unitario = db.Column(db.Float, default=0)
    ncm = db.Column(db.String(8))
    cfop = db.Column(db.String(4))
    cst_icms = db.Column(db.String(3))
    base_icms = db.Column(db.Float)
    aliquota_icms = db.Column(db.Float)
    valor_icms = db.Column(db.Float)
    cst_pis = db.Column(db.String(2))
    base_pis = db.Column(db.Float)
    aliquota_pis = db.Column(db.Float)
    valor_pis = db.Column(db.Float)
    cst_cofins = db.Column(db.String(2))
    base_cofins = db.Column(db.Float)
    aliquota_cofins = db.Column(db.Float)
    valor_cofins = db.Column(db.Float)
    cst_ibs_cbs = db.Column(db.String(3))
    classificacao_tributaria = db.Column(db.String(6))
    base_ibs_cbs = db.Column(db.Float)
    aliquota_ibs = db.Column(db.Float)
    valor_ibs = db.Column(db.Float)
    aliquota_cbs = db.Column(db.Float)
    valor_cbs = db.Column(db.Float)
    baixado_estoque = db.Column(db.Boolean, default=False)
    # Campo legado mantido apenas para compatibilidade com bancos antigos.
    # Novos lançamentos são controlados exclusivamente por quantidade.
    numeros_serie = db.Column(db.Text)
    peca = db.relationship("Peca")

    @property
    def subtotal(self):
        return round((self.quantidade or 0) * (self.valor_unitario or 0), 2)

    @property
    def valor_tributos(self):
        return round(sum((v or 0) for v in (self.valor_icms, self.valor_pis, self.valor_cofins,
                                             self.valor_ibs, self.valor_cbs)), 2)

    def to_dict(self):
        return {"id": self.id, "nota_fiscal_id": self.nota_fiscal_id,
                "peca_id": self.peca_id,
                "peca_descricao": f"{self.peca.codigo} · {self.peca.descricao}" if self.peca else None,
                "descricao": self.descricao, "quantidade": self.quantidade,
                "valor_unitario": self.valor_unitario, "valor_total": self.subtotal,
                "ncm": self.ncm, "cfop": self.cfop,
                "cst_icms": self.cst_icms, "base_icms": self.base_icms or 0,
                "aliquota_icms": self.aliquota_icms or 0, "valor_icms": self.valor_icms or 0,
                "cst_pis": self.cst_pis, "base_pis": self.base_pis or 0,
                "aliquota_pis": self.aliquota_pis or 0, "valor_pis": self.valor_pis or 0,
                "cst_cofins": self.cst_cofins, "base_cofins": self.base_cofins or 0,
                "aliquota_cofins": self.aliquota_cofins or 0, "valor_cofins": self.valor_cofins or 0,
                "cst_ibs_cbs": self.cst_ibs_cbs,
                "classificacao_tributaria": self.classificacao_tributaria,
                "base_ibs_cbs": self.base_ibs_cbs or 0,
                "aliquota_ibs": self.aliquota_ibs or 0, "valor_ibs": self.valor_ibs or 0,
                "aliquota_cbs": self.aliquota_cbs or 0, "valor_cbs": self.valor_cbs or 0,
                "valor_tributos": self.valor_tributos,
                "baixado_estoque": self.baixado_estoque}


class OrdemServico(db.Model):
    """Módulo 3 — manutenção."""
    __tablename__ = "ordens_servico"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, index=True)
    data_abertura = db.Column(db.Date, default=_hoje)
    data_fechamento = db.Column(db.Date)
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey("motoristas.id"))
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"))
    mecanico = db.Column(db.String(80))
    tipo = db.Column(db.String(20), default="Preventiva")   # Preventiva | Corretiva | Emergencial
    prioridade = db.Column(db.String(20), default="Média")  # Baixa | Média | Alta | Crítica
    status = db.Column(db.String(30), default="Aberta")     # Aberta | Em execução | Aguardando peça | Finalizada
    grupo = db.Column(db.String(40))                        # Motor, Freios, Pneus, ...
    hora_inicio = db.Column(db.Time)
    hora_fim = db.Column(db.Time)
    cco = db.Column(db.String(40))
    solicitante = db.Column(db.String(120))
    setor = db.Column(db.String(60))
    problema = db.Column(db.Text)
    local_execucao = db.Column(db.String(20))               # Interno | Externo
    km_veiculo = db.Column(db.Float, default=0)
    descricao = db.Column(db.Text)
    custo_mao_obra = db.Column(db.Float, default=0)
    custo_servicos = db.Column(db.Float, default=0)
    avaliacao = db.Column(db.Integer)  # 1 a 5
    veiculo = db.relationship("Veiculo")
    motorista = db.relationship("Motorista")
    fornecedor = db.relationship("Fornecedor")
    itens = db.relationship("ItemOS", backref="ordem", cascade="all, delete-orphan",
                            lazy="selectin")
    anexos = db.relationship("Anexo", cascade="all, delete-orphan", lazy="selectin")

    @property
    def custo_pecas(self):
        return round(sum((i.quantidade or 0) * (i.valor_unitario or 0)
                         for i in self.itens if i.eh_peca), 2)

    @property
    def custo_servicos_lancados(self):
        """Serviços lançados como itens da OS, inclusive serviços de terceiros."""
        return round(sum((i.quantidade or 0) * (i.valor_unitario or 0)
                         for i in self.itens if not i.eh_peca), 2)

    @property
    def custo_servicos_total(self):
        # custo_servicos é o campo legado/manual já existente nas OS antigas.
        return round((self.custo_servicos or 0) + self.custo_servicos_lancados, 2)

    @property
    def custo_total(self):
        return round(self.custo_pecas + (self.custo_mao_obra or 0) + self.custo_servicos_total, 2)

    @property
    def dias_parado(self):
        fim = self.data_fechamento or _hoje()
        return max((fim - self.data_abertura).days, 0) if self.data_abertura else 0

    @property
    def duracao_minutos(self):
        """Minutos entre hora_inicio e hora_fim, quando os dois estão
        preenchidos e o serviço não passou da meia-noite."""
        if not (self.hora_inicio and self.hora_fim):
            return None
        inicio = self.hora_inicio.hour * 60 + self.hora_inicio.minute
        fim = self.hora_fim.hour * 60 + self.hora_fim.minute
        return fim - inicio if fim >= inicio else None

    def to_dict(self, com_itens=False):
        d = {
            "id": self.id, "numero": self.numero,
            "data_abertura": self.data_abertura.isoformat() if self.data_abertura else None,
            "data_fechamento": self.data_fechamento.isoformat() if self.data_fechamento else None,
            "veiculo_id": self.veiculo_id,
            "veiculo_nome": f"{self.veiculo.prefixo} · {self.veiculo.placa}" if self.veiculo else None,
            "motorista_id": self.motorista_id,
            "motorista_nome": self.motorista.nome if self.motorista else None,
            "fornecedor_id": self.fornecedor_id,
            "fornecedor_nome": self.fornecedor.nome if self.fornecedor else None,
            "mecanico": self.mecanico, "tipo": self.tipo, "prioridade": self.prioridade,
            "status": self.status, "grupo": self.grupo, "km_veiculo": self.km_veiculo,
            "hora_inicio": self.hora_inicio.strftime("%H:%M") if self.hora_inicio else None,
            "hora_fim": self.hora_fim.strftime("%H:%M") if self.hora_fim else None,
            "duracao_minutos": self.duracao_minutos,
            "cco": self.cco, "solicitante": self.solicitante, "setor": self.setor,
            "problema": self.problema, "local_execucao": self.local_execucao,
            "descricao": self.descricao, "custo_mao_obra": self.custo_mao_obra,
            "custo_servicos": self.custo_servicos,
            "custo_servicos_lancados": self.custo_servicos_lancados,
            "custo_servicos_total": self.custo_servicos_total,
            "custo_pecas": self.custo_pecas,
            "custo_total": self.custo_total, "dias_parado": self.dias_parado,
            "avaliacao": self.avaliacao, "qtd_anexos": len(self.anexos),
            "identificacao": f"{self.numero or 'OS'} · {self.veiculo.prefixo if self.veiculo else 'sem veículo'}",
        }
        if com_itens:
            d["itens"] = [i.to_dict() for i in self.itens]
        return d


class ItemOS(db.Model):
    __tablename__ = "itens_os"
    id = db.Column(db.Integer, primary_key=True)
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey("ordens_servico.id"), nullable=False)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"))
    descricao = db.Column(db.String(160))
    grupo = db.Column(db.String(40))
    quantidade = db.Column(db.Float, default=1)
    valor_unitario = db.Column(db.Float, default=0)
    # peça | servico_avulso | servico_terceiro. Registros antigos podem ficar
    # nulos e são classificados automaticamente pela propriedade abaixo.
    tipo_item = db.Column(db.String(24))
    prestador_servico = db.Column(db.String(120))
    baixado_estoque = db.Column(db.Boolean, default=False)
    # Posição no caminhão em que o pneu foi instalado nesta OS
    # (Dianteiro Direito, Traseiro Esquerdo Interno...) — ver SGMF.POSICOES.
    posicao_pneu = db.Column(db.String(40))
    # Pneu (Módulo 7) que estava "Em uso" naquela posição e foi marcado como
    # "Descartado" quando este item foi lançado. Guardamos a referência para
    # poder devolver o pneu a "Em uso" se este item for removido da OS.
    pneu_substituido_id = db.Column(db.Integer, db.ForeignKey("pneus.id"))
    peca = db.relationship("Peca")

    @property
    def tipo_item_resolvido(self):
        if self.peca_id:
            return "peca"
        return self.tipo_item or "servico_avulso"

    @property
    def eh_peca(self):
        return bool(self.peca_id) or self.tipo_item_resolvido == "peca"

    def to_dict(self):
        return {"id": self.id, "ordem_servico_id": self.ordem_servico_id,
                "peca_id": self.peca_id, "descricao": self.descricao, "grupo": self.grupo,
                "tipo_item": self.tipo_item_resolvido,
                "prestador_servico": self.prestador_servico,
                "quantidade": self.quantidade, "valor_unitario": self.valor_unitario,
                "valor_total": round((self.quantidade or 0) * (self.valor_unitario or 0), 2),
                "baixado_estoque": self.baixado_estoque,
                "posicao_pneu": self.posicao_pneu,
                "pneu_substituido_id": self.pneu_substituido_id}


class ServicoTerceiro(db.Model):
    """Despesa de serviço executado por prestador externo.

    É um lançamento financeiro independente da OS: a ordem pode ser vinculada
    apenas para referência, enquanto o gasto entra no painel pela data deste
    registro. Isso evita deslocar despesas para o mês de abertura da OS.
    """
    __tablename__ = "servicos_terceiros"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, default=_hoje, nullable=False, index=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"), nullable=False, index=True)
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey("ordens_servico.id"), index=True)
    prestador = db.Column(db.String(120), nullable=False)
    tipo_servico = db.Column(db.String(80))
    descricao = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Float, default=0, nullable=False)
    documento = db.Column(db.String(80))
    observacao = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, default=_agora)

    veiculo = db.relationship("Veiculo")
    ordem = db.relationship("OrdemServico")

    def to_dict(self):
        return {
            "id": self.id,
            "data": self.data.isoformat() if self.data else None,
            "veiculo_id": self.veiculo_id,
            "veiculo_nome": (f"{self.veiculo.prefixo} · {self.veiculo.placa}"
                              if self.veiculo else None),
            "ordem_servico_id": self.ordem_servico_id,
            "ordem_numero": self.ordem.numero if self.ordem else None,
            "prestador": self.prestador,
            "tipo_servico": self.tipo_servico,
            "descricao": self.descricao,
            "valor": round(self.valor or 0, 2),
            "documento": self.documento,
            "observacao": self.observacao,
            "identificacao": f"{self.descricao} · {self.prestador}",
        }


class Abastecimento(db.Model):
    """Módulo 5 — combustível."""
    __tablename__ = "abastecimentos"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, default=_hoje, index=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey("motoristas.id"))
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"))
    combustivel = db.Column(db.String(30), default="Diesel S10")
    km_atual = db.Column(db.Float, default=0)
    litros = db.Column(db.Float, default=0)
    valor_litro = db.Column(db.Float, default=0)
    valor_total = db.Column(db.Float, default=0)
    tanque_cheio = db.Column(db.Boolean, default=True)
    # calculados automaticamente ao salvar
    km_percorridos = db.Column(db.Float, default=0)
    km_por_litro = db.Column(db.Float, default=0)
    custo_por_km = db.Column(db.Float, default=0)
    veiculo = db.relationship("Veiculo")
    motorista = db.relationship("Motorista")
    fornecedor = db.relationship("Fornecedor")
    anexos = db.relationship("Anexo", cascade="all, delete-orphan", lazy="selectin")

    def to_dict(self):
        return {"id": self.id, "data": self.data.isoformat() if self.data else None,
                "veiculo_id": self.veiculo_id,
                "veiculo_nome": f"{self.veiculo.prefixo} · {self.veiculo.placa}" if self.veiculo else None,
                "motorista_id": self.motorista_id,
                "motorista_nome": self.motorista.nome if self.motorista else None,
                "fornecedor_id": self.fornecedor_id,
                "fornecedor_nome": self.fornecedor.nome if self.fornecedor else None,
                "combustivel": self.combustivel, "km_atual": self.km_atual,
                "litros": self.litros, "valor_litro": self.valor_litro,
                "valor_total": self.valor_total, "tanque_cheio": self.tanque_cheio,
                "km_percorridos": self.km_percorridos, "km_por_litro": self.km_por_litro,
                "custo_por_km": self.custo_por_km, "qtd_anexos": len(self.anexos)}


class Pneu(db.Model):
    """Módulo 7 — pneus."""
    __tablename__ = "pneus"
    id = db.Column(db.Integer, primary_key=True)
    numero_fogo = db.Column(db.String(30), unique=True, nullable=False)
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"))
    posicao = db.Column(db.String(40))     # Dianteiro Direito, Traseiro Esquerdo Interno...
    marca = db.Column(db.String(40))
    medida = db.Column(db.String(30))      # 275/80 R22.5
    sulco_mm = db.Column(db.Float, default=0)
    vida = db.Column(db.String(20), default="Novo")  # Novo | 1ª recapagem | 2ª recapagem
    km_instalacao = db.Column(db.Float, default=0)
    data_instalacao = db.Column(db.Date, default=_hoje)
    data_medicao = db.Column(db.Date, default=_hoje)
    status = db.Column(db.String(20), default="Em uso")  # Em uso | Estoque | Descartado
    custo = db.Column(db.Float, default=0)
    veiculo = db.relationship("Veiculo")

    def to_dict(self, sulco_minimo=4.0):
        km_rodados = 0
        if self.veiculo and self.km_instalacao:
            km_rodados = max((self.veiculo.hodometro or 0) - self.km_instalacao, 0)
        return {"id": self.id, "numero_fogo": self.numero_fogo, "veiculo_id": self.veiculo_id,
                "veiculo_nome": f"{self.veiculo.prefixo} · {self.veiculo.placa}" if self.veiculo else None,
                "posicao": self.posicao, "marca": self.marca, "medida": self.medida,
                "sulco_mm": self.sulco_mm, "vida": self.vida,
                "km_instalacao": self.km_instalacao, "km_rodados": round(km_rodados),
                "data_instalacao": self.data_instalacao.isoformat() if self.data_instalacao else None,
                "data_medicao": self.data_medicao.isoformat() if self.data_medicao else None,
                "status": self.status, "custo": self.custo,
                "trocar": (self.sulco_mm or 0) < sulco_minimo and self.status == "Em uso",
                "identificacao": f"{self.numero_fogo} · {self.posicao or ''}".strip()}


class Orcamento(db.Model):
    """Módulo 8 — meta x realizado."""
    __tablename__ = "orcamentos"
    id = db.Column(db.Integer, primary_key=True)
    ano = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(20), default="Manutenção")  # Manutenção | Combustível | Pneus
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"))
    centro_custo = db.Column(db.String(60))
    meta_valor = db.Column(db.Float, default=0)
    veiculo = db.relationship("Veiculo")

    def to_dict(self):
        return {"id": self.id, "ano": self.ano, "mes": self.mes, "categoria": self.categoria,
                "veiculo_id": self.veiculo_id,
                "veiculo_nome": f"{self.veiculo.prefixo} · {self.veiculo.placa}" if self.veiculo else None,
                "centro_custo": self.centro_custo, "meta_valor": self.meta_valor}


class Anexo(db.Model):
    """Arquivos das ordens de serviço e dos abastecimentos.

    O conteúdo fica no próprio banco. No Render o disco é temporário: um
    arquivo salvo em pasta some no próximo deploy, então guardar no banco é
    o que mantém a nota fiscal disponível meses depois.
    """
    __tablename__ = "anexos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    tipo_mime = db.Column(db.String(80))
    tamanho = db.Column(db.Integer, default=0)
    conteudo = db.Column(db.LargeBinary, nullable=False)
    descricao = db.Column(db.String(200))
    enviado_por = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=_agora)
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey("ordens_servico.id"))
    abastecimento_id = db.Column(db.Integer, db.ForeignKey("abastecimentos.id"))

    def to_dict(self):
        return {"id": self.id, "nome": self.nome, "tipo_mime": self.tipo_mime,
                "tamanho": self.tamanho,
                "tamanho_legivel": f"{(self.tamanho or 0) / 1024:.0f} KB"
                if (self.tamanho or 0) < 1024 * 1024
                else f"{(self.tamanho or 0) / 1048576:.1f} MB",
                "descricao": self.descricao, "enviado_por": self.enviado_por,
                "criado_em": self.criado_em.isoformat() if self.criado_em else None,
                "ordem_servico_id": self.ordem_servico_id,
                "abastecimento_id": self.abastecimento_id,
                "imagem": (self.tipo_mime or "").startswith("image/")}


class ControleTarefa(db.Model):
    """Marca quando cada tarefa automática rodou pela última vez.

    Como o sistema sobe com mais de um processo, é este registro que impede
    dois deles de enviarem o mesmo aviso no mesmo dia.
    """
    __tablename__ = "controle_tarefas"
    id = db.Column(db.Integer, primary_key=True)
    tarefa = db.Column(db.String(60), unique=True, nullable=False)
    ultima_execucao = db.Column(db.Date)
    ultimo_resultado = db.Column(db.String(300))
    atualizado_em = db.Column(db.DateTime, default=_agora)


class LogAuditoria(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    momento = db.Column(db.DateTime, default=_agora)
    usuario = db.Column(db.String(120))
    acao = db.Column(db.String(20))
    entidade = db.Column(db.String(60))
    registro_id = db.Column(db.Integer)
    detalhe = db.Column(db.Text)

    def to_dict(self):
        return {"id": self.id, "momento": self.momento.isoformat(), "usuario": self.usuario,
                "acao": self.acao, "entidade": self.entidade, "registro_id": self.registro_id,
                "detalhe": self.detalhe}


# ============================================================================
# Sincronização automática da manutenção concluída
# ============================================================================
# Alertas de preventiva e troca de óleo são calculados a partir do cadastro do
# veículo. Se uma OS for finalizada sem atualizar esses marcos, a causa continua
# verdadeira e o alerta permanece. Este evento mantém os marcos sincronizados
# independentemente da tela, API ou rotina usada para finalizar a OS.
from sqlalchemy import event as _sa_event, inspect as _sa_inspect
from sqlalchemy.orm import Session as _SASession


def _texto_os(obj):
    return " ".join(str(v or "") for v in (obj.tipo, obj.grupo, obj.descricao)).casefold()


def _os_indica_troca_oleo(obj):
    texto = _texto_os(obj)
    return "troca de óleo" in texto or "troca de oleo" in texto or "óleo motor" in texto or "oleo motor" in texto


@_sa_event.listens_for(_SASession, "before_flush")
def _sincronizar_os_finalizada(session, _flush_context, _instances):
    candidatos = list(session.new) + list(session.dirty)
    for obj in candidatos:
        if not isinstance(obj, OrdemServico) or obj.status != "Finalizada":
            continue

        estado = _sa_inspect(obj)
        historico = estado.attrs.status.history
        acabou_de_finalizar = obj in session.new or (
            historico.has_changes() and "Finalizada" in historico.added
        )
        if not acabou_de_finalizar:
            continue

        if obj.data_fechamento is None:
            obj.data_fechamento = _hoje()

        veiculo = obj.veiculo
        if veiculo is None and obj.veiculo_id:
            veiculo = session.get(Veiculo, obj.veiculo_id)
        if veiculo is None:
            continue

        if (obj.tipo or "").casefold() == "preventiva":
            atual = veiculo.data_ultima_preventiva
            referencia = obj.data_fechamento or _hoje()
            if atual is None or referencia >= atual:
                veiculo.data_ultima_preventiva = referencia

        if _os_indica_troca_oleo(obj):
            km_referencia = float(obj.km_veiculo or veiculo.hodometro or 0)
            if km_referencia > float(veiculo.km_ultima_troca_oleo or 0):
                veiculo.km_ultima_troca_oleo = km_referencia

        # Se não existir outra OS aberta para o veículo, ele volta a ficar
        # disponível. A própria OS em finalização é excluída da consulta.
        outras_abertas = (session.query(OrdemServico.id)
                           .filter(OrdemServico.veiculo_id == veiculo.id,
                                   OrdemServico.status != "Finalizada",
                                   OrdemServico.id != obj.id)
                           .first())
        if outras_abertas is None and veiculo.situacao == "Em manutenção":
            veiculo.situacao = "Disponível"


# ============================================================================
# Troca de óleo aplicada por item da OS
# ============================================================================
# Se o item efetivamente aplicado for óleo de motor ou filtro de óleo, o marco
# de quilometragem é atualizado no veículo. Isso evita manter um alerta de óleo
# mesmo depois da aplicação da peça na ordem de serviço.
def _item_os_indica_troca_oleo(item):
    valores = [item.grupo, item.descricao]
    if item.peca is not None:
        valores.extend([item.peca.grupo, item.peca.descricao, item.peca.codigo])
    texto = " ".join(str(v or "") for v in valores).casefold()
    termos = (
        "filtro de óleo", "filtro de oleo", "óleo motor", "oleo motor",
        "óleo do motor", "oleo do motor", "troca de óleo", "troca de oleo",
    )
    return any(termo in texto for termo in termos)


@_sa_event.listens_for(_SASession, "before_flush")
def _sincronizar_oleo_ao_aplicar_item(session, _flush_context, _instances):
    candidatos = list(session.new) + list(session.dirty)
    for item in candidatos:
        if not isinstance(item, ItemOS) or not item.baixado_estoque:
            continue

        estado = _sa_inspect(item)
        hist = estado.attrs.baixado_estoque.history
        aplicado_agora = item in session.new or (hist.has_changes() and True in hist.added)
        if not aplicado_agora or not _item_os_indica_troca_oleo(item):
            continue

        os_obj = item.ordem
        if os_obj is None and item.ordem_servico_id:
            os_obj = session.get(OrdemServico, item.ordem_servico_id)
        if os_obj is None:
            continue

        veiculo = os_obj.veiculo
        if veiculo is None and os_obj.veiculo_id:
            veiculo = session.get(Veiculo, os_obj.veiculo_id)
        if veiculo is None:
            continue

        km_referencia = float(os_obj.km_veiculo or veiculo.hodometro or 0)
        if km_referencia > float(veiculo.km_ultima_troca_oleo or 0):
            veiculo.km_ultima_troca_oleo = km_referencia


# ============================================================================
# Módulo — Uniformes: cadastro de funcionários, estoque próprio de itens de
# uniforme e entregas (baixas) desse estoque.
#
# Regra atual: o saldo é SEPARADO POR TAMANHO. "Sapato" não tem um saldo só —
# tem um saldo para o 40, outro para o 42, outro para o 43 (tabela
# saldos_uniforme). Ao entregar, o tamanho escolhido decide de qual saldo sai a
# baixa: se o 42 está zerado, a entrega do 42 é recusada mesmo que sobrem pares
# de outros números.
#
# ItemUniforme.quantidade continua existindo, mas passou a ser só o TOTAL —
# a soma dos tamanhos, recalculada a cada movimento. Não se escreve nele
# direto; quem manda é a linha do tamanho.
# ============================================================================
TAMANHOS_UNIFORME = {
    "roupa": ["PP", "P", "M", "G", "GG", "XG"],
    "calcado": [str(n) for n in range(34, 47)],   # 34 a 46
    "luva": ["07", "08", "09", "10"],
    "unico": ["Único"],
}
ROTULOS_TIPO_TAMANHO = {"roupa": "Roupa", "calcado": "Calçado", "luva": "Luva", "unico": "Único"}


def normalizar_tipo_tamanho(valor):
    """Aceita 'Calçado', 'calcado', 'CALÇADO'... e devolve a chave interna."""
    texto = (valor or "").strip().lower()
    equivalentes = {
        "roupa": "roupa", "vestuario": "roupa", "vestuário": "roupa",
        "calcado": "calcado", "calçado": "calcado", "sapato": "calcado",
        "luva": "luva", "luvas": "luva",
        "unico": "unico", "único": "unico", "sem tamanho": "unico",
    }
    return equivalentes.get(texto, "roupa")


def tamanhos_do_tipo(tipo):
    return list(TAMANHOS_UNIFORME.get(normalizar_tipo_tamanho(tipo), []))


class Funcionario(db.Model):
    __tablename__ = "funcionarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    matricula = db.Column(db.String(30))
    cargo = db.Column(db.String(60))
    setor = db.Column(db.String(60))
    telefone = db.Column(db.String(20))
    ativo = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {"id": self.id, "nome": self.nome, "matricula": self.matricula,
                "cargo": self.cargo, "setor": self.setor, "telefone": self.telefone,
                "ativo": self.ativo, "identificacao": self.nome}


class ItemUniforme(db.Model):
    """Estoque próprio de uniformes — separado do estoque de peças.

    O saldo real mora em SaldoUniforme (uma linha por tamanho). O campo
    `quantidade` aqui é só o total somado, mantido para as telas e relatórios
    que já liam esse número.
    """
    __tablename__ = "itens_uniforme"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False, index=True)
    descricao = db.Column(db.String(80), nullable=False)   # Calça, Camisa, Meia, Moletom, Luva, Sapato...
    tipo_tamanho = db.Column(db.String(12), default="roupa")   # roupa | calcado | unico
    unidade = db.Column(db.String(10), default="UN")
    quantidade = db.Column(db.Float, default=0)            # total = soma dos tamanhos
    estoque_minimo = db.Column(db.Float, default=0)        # mínimo padrão de cada tamanho novo
    ativo = db.Column(db.Boolean, default=True)
    saldos = db.relationship("SaldoUniforme", back_populates="item",
                             cascade="all, delete-orphan", lazy="selectin")

    def tamanhos_previstos(self):
        return tamanhos_do_tipo(self.tipo_tamanho)

    def saldos_ordenados(self):
        """Na ordem do tipo (PP→XG, 34→46), com qualquer tamanho estranho no fim."""
        ordem = {t: i for i, t in enumerate(self.tamanhos_previstos())}
        return sorted(self.saldos or [],
                      key=lambda s: (ordem.get(s.tamanho, 999), s.tamanho or ""))

    def total(self):
        return round(sum((s.quantidade or 0) for s in (self.saldos or [])), 3)

    def to_dict(self):
        linhas = [s.to_dict() for s in self.saldos_ordenados()]
        return {"id": self.id, "codigo": self.codigo, "descricao": self.descricao,
                "tipo_tamanho": normalizar_tipo_tamanho(self.tipo_tamanho),
                "tipo_tamanho_rotulo": ROTULOS_TIPO_TAMANHO.get(
                    normalizar_tipo_tamanho(self.tipo_tamanho), "Roupa"),
                "tamanhos_previstos": self.tamanhos_previstos(),
                "unidade": self.unidade, "quantidade": self.total(),
                "estoque_minimo": self.estoque_minimo, "ativo": self.ativo,
                "saldos": linhas,
                "abaixo_minimo": any(l["abaixo_minimo"] for l in linhas),
                "identificacao": f"{self.codigo} · {self.descricao}"}


class SaldoUniforme(db.Model):
    """Saldo de UM tamanho de UM item — é aqui que a baixa acontece."""
    __tablename__ = "saldos_uniforme"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("itens_uniforme.id"), nullable=False)
    tamanho = db.Column(db.String(10), nullable=False)
    quantidade = db.Column(db.Float, default=0)
    estoque_minimo = db.Column(db.Float, default=0)
    item = db.relationship("ItemUniforme", back_populates="saldos")

    __table_args__ = (db.UniqueConstraint("item_id", "tamanho",
                                          name="uq_saldo_item_tamanho"),)

    @property
    def falta_comprar(self):
        """Quanto falta para chegar ao mínimo — é o número da lista de compra."""
        if not self.estoque_minimo:
            return 0
        return max(0, round((self.estoque_minimo or 0) - (self.quantidade or 0), 3))

    def to_dict(self):
        return {"id": self.id, "item_id": self.item_id, "tamanho": self.tamanho,
                "quantidade": self.quantidade or 0,
                "estoque_minimo": self.estoque_minimo or 0,
                "falta_comprar": self.falta_comprar,
                "abaixo_minimo": bool(self.estoque_minimo)
                                 and (self.quantidade or 0) <= (self.estoque_minimo or 0)}


def proximo_codigo_item_uniforme():
    """Mesmo esquema sequencial (0001, 0002...) usado no estoque de peças."""
    maior = 0
    for (codigo,) in db.session.query(ItemUniforme.codigo).all():
        if codigo and codigo.strip().isdigit():
            maior = max(maior, int(codigo))
    return f"{maior + 1:04d}"


class MovimentoUniforme(db.Model):
    """Histórico de entradas/saídas do estoque de uniformes — mesmo espírito
    do MovimentoEstoque de peças: o saldo nunca muda sem deixar rastro."""
    __tablename__ = "movimentos_uniforme"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, default=_hoje)
    item_id = db.Column(db.Integer, db.ForeignKey("itens_uniforme.id"), nullable=False)
    tamanho = db.Column(db.String(10))   # de qual tamanho entrou/saiu
    tipo = db.Column(db.String(10))   # entrada | saida | ajuste
    quantidade = db.Column(db.Float, default=0)
    documento = db.Column(db.String(60))
    entrega_id = db.Column(db.Integer, db.ForeignKey("entregas_uniforme.id"))
    observacao = db.Column(db.String(200))
    item = db.relationship("ItemUniforme")

    def to_dict(self):
        return {"id": self.id, "data": self.data.isoformat() if self.data else None,
                "item_id": self.item_id,
                "item_descricao": f"{self.item.codigo} · {self.item.descricao}" if self.item else None,
                "tamanho": self.tamanho,
                "tipo": self.tipo, "quantidade": self.quantidade,
                "documento": self.documento, "observacao": self.observacao}


class EntregaUniforme(db.Model):
    """Entrega (baixa) de um item de uniforme para um funcionário.

    O tamanho é obrigatório e decide de qual saldo sai a baixa — ver
    SaldoUniforme. Entregas antigas (antes desta regra) podem estar sem
    tamanho: elas ficam no histórico como estão.
    """
    __tablename__ = "entregas_uniforme"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, default=_hoje)
    funcionario_id = db.Column(db.Integer, db.ForeignKey("funcionarios.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("itens_uniforme.id"), nullable=False)
    tamanho = db.Column(db.String(10))                 # P, M, G, GG, 38, 40...
    tipo_entrega = db.Column(db.String(15), default="Novo")  # Novo | Emergencial
    quantidade = db.Column(db.Float, default=1)
    observacao = db.Column(db.String(200))
    funcionario = db.relationship("Funcionario")
    item = db.relationship("ItemUniforme")

    def to_dict(self):
        return {"id": self.id, "data": self.data.isoformat() if self.data else None,
                "funcionario_id": self.funcionario_id,
                "funcionario_nome": self.funcionario.nome if self.funcionario else None,
                "item_id": self.item_id,
                "item_descricao": f"{self.item.codigo} · {self.item.descricao}" if self.item else None,
                "tamanho": self.tamanho, "tipo_entrega": self.tipo_entrega,
                "quantidade": self.quantidade, "observacao": self.observacao,
                "identificacao": f"Entrega #{self.id}"}


def garantir_saldos(item):
    """Cria as linhas de saldo que faltarem para os tamanhos do tipo do item.

    Chamada antes de qualquer leitura ou movimento — assim um item recém
    cadastrado (ou que mudou de tipo) já aparece com todos os tamanhos
    zerados, e a lista de compra consegue enxergar o que falta comprar.
    O mínimo de cada tamanho novo começa igual ao mínimo padrão do item.
    """
    previstos = item.tamanhos_previstos()

    # Item que trocou de tipo (era roupa, virou calçado) fica com as linhas
    # antigas penduradas. As que estão zeradas saem daqui — não servem para
    # nada e só atrapalham na hora de escolher o tamanho. As que têm saldo
    # ficam: nada some do estoque sem passar por um movimento.
    for sobra in list(item.saldos or []):
        if sobra.tamanho not in previstos and not (sobra.quantidade or 0):
            item.saldos.remove(sobra)

    existentes = {s.tamanho for s in (item.saldos or [])}
    criados = 0
    for tamanho in previstos:
        if tamanho in existentes:
            continue
        # append na relação (e não db.session.add avulso): assim a linha nova
        # já aparece em item.saldos na mesma requisição, sem esperar o próximo
        # carregamento — senão a função abaixo criaria uma segunda linha do
        # mesmo tamanho e esbarraria na trava de unicidade.
        item.saldos.append(SaldoUniforme(tamanho=tamanho, quantidade=0,
                                         estoque_minimo=item.estoque_minimo or 0))
        criados += 1
    if criados:
        db.session.flush()
    return criados


def saldo_do_tamanho(item, tamanho, criar=True):
    """Devolve a linha de saldo daquele tamanho (criando se necessário)."""
    alvo = (tamanho or "").strip()
    for s in (item.saldos or []):
        if (s.tamanho or "").strip().lower() == alvo.lower():
            return s
    if not criar:
        return None
    novo = SaldoUniforme(tamanho=alvo, quantidade=0,
                         estoque_minimo=item.estoque_minimo or 0)
    item.saldos.append(novo)
    db.session.flush()
    return novo


def recalcular_total_uniforme(item):
    """Mantém ItemUniforme.quantidade como a soma dos tamanhos."""
    item.quantidade = item.total()
    return item.quantidade


# ============================================================================
# Módulo — Ordens de compra: a solicitação de material que sai da operação,
# vai para o financeiro aprovar e volta marcada como comprada.
#
# Regra pedida: a ordem de compra NÃO movimenta estoque em nenhum momento.
# Ela é só o documento do pedido. A entrada continua acontecendo pelo caminho
# de sempre — nota fiscal (NotaFiscal/ItemNotaFiscal) ou movimento manual.
#
# Cada item pode vir de duas formas, igual ao ItemOS: escolhido no estoque
# (peca_id preenchido) ou escrito à mão (só a descrição). Por isso `peca_id`
# é opcional e `descricao` é sempre gravada — inclusive quando a peça vem do
# estoque, para o documento continuar legível se a peça for renomeada depois.
# ============================================================================
STATUS_ORDEM_COMPRA = ("Pendente", "Aprovada", "Reprovada", "Comprada")


class OrdemCompra(db.Model):
    __tablename__ = "ordens_compra"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, index=True)
    data_solicitacao = db.Column(db.Date, default=_hoje, index=True)
    solicitante = db.Column(db.String(120))     # preenchido com o usuário logado
    setor = db.Column(db.String(60))
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"))
    prioridade = db.Column(db.String(20), default="Média")   # Baixa | Média | Alta | Urgente
    status = db.Column(db.String(20), default="Pendente")    # ver STATUS_ORDEM_COMPRA
    justificativa = db.Column(db.Text)
    observacao = db.Column(db.String(200))

    # --- trilha da aprovação (quem decidiu o quê, e quando) ---------------
    aprovado_por = db.Column(db.String(120))
    data_aprovacao = db.Column(db.Date)
    motivo_reprovacao = db.Column(db.String(200))
    comprado_por = db.Column(db.String(120))
    data_compra = db.Column(db.Date)

    fornecedor = db.relationship("Fornecedor")
    itens = db.relationship("ItemOrdemCompra", backref="ordem_compra",
                            cascade="all, delete-orphan", lazy="selectin")

    @property
    def valor_total(self):
        """Valor estimado: é o que a operação previu, não o que foi pago."""
        return round(sum((i.quantidade or 0) * (i.valor_unitario or 0) for i in self.itens), 2)

    @property
    def editavel(self):
        """Só a ordem ainda Pendente aceita mudança de cabeçalho e de itens."""
        return self.status == "Pendente"

    def to_dict(self, com_itens=False):
        d = {
            "id": self.id, "numero": self.numero,
            "data_solicitacao": self.data_solicitacao.isoformat() if self.data_solicitacao else None,
            "solicitante": self.solicitante, "setor": self.setor,
            "fornecedor_id": self.fornecedor_id,
            "fornecedor_nome": self.fornecedor.nome if self.fornecedor else None,
            "prioridade": self.prioridade, "status": self.status,
            "justificativa": self.justificativa, "observacao": self.observacao,
            "aprovado_por": self.aprovado_por,
            "data_aprovacao": self.data_aprovacao.isoformat() if self.data_aprovacao else None,
            "motivo_reprovacao": self.motivo_reprovacao,
            "comprado_por": self.comprado_por,
            "data_compra": self.data_compra.isoformat() if self.data_compra else None,
            "valor_total": self.valor_total, "qtd_itens": len(self.itens),
            "editavel": self.editavel,
            "identificacao": f"OC {self.numero}" if self.numero else f"OC #{self.id}",
        }
        if com_itens:
            d["itens"] = [i.to_dict() for i in self.itens]
        return d


class ItemOrdemCompra(db.Model):
    __tablename__ = "itens_ordem_compra"
    id = db.Column(db.Integer, primary_key=True)
    ordem_compra_id = db.Column(db.Integer, db.ForeignKey("ordens_compra.id"), nullable=False)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"))   # vazio = item escrito à mão
    descricao = db.Column(db.String(160), nullable=False)
    unidade = db.Column(db.String(10), default="UN")
    quantidade = db.Column(db.Float, default=1)
    valor_unitario = db.Column(db.Float, default=0)   # preço estimado, opcional
    observacao = db.Column(db.String(200))
    peca = db.relationship("Peca")

    @property
    def subtotal(self):
        return round((self.quantidade or 0) * (self.valor_unitario or 0), 2)

    def to_dict(self):
        return {"id": self.id, "ordem_compra_id": self.ordem_compra_id,
                "peca_id": self.peca_id,
                "peca_descricao": f"{self.peca.codigo} · {self.peca.descricao}" if self.peca else None,
                "peca_saldo": self.peca.quantidade if self.peca else None,
                "descricao": self.descricao, "unidade": self.unidade,
                "quantidade": self.quantidade, "valor_unitario": self.valor_unitario,
                "valor_total": self.subtotal,
                "origem": "estoque" if self.peca_id else "livre",
                "observacao": self.observacao}


def proximo_numero_ordem_compra():
    """Numeração sequencial própria (OC-0001, OC-0002...).

    Continua a partir do maior número já usado, ignorando qualquer numeração
    manual que não siga o formato — mesma ideia de proximo_codigo_peca().
    """
    maior = 0
    for (numero,) in db.session.query(OrdemCompra.numero).all():
        if not numero:
            continue
        digitos = str(numero).split("-")[-1].strip()
        if digitos.isdigit():
            maior = max(maior, int(digitos))
    return f"OC-{maior + 1:04d}"


# ============================================================================
# Segurança do login — tentativas de acesso e bloqueio manual
# ============================================================================
class TentativaLogin(db.Model):
    """Histórico de tentativas de login — usado pelo bloqueio automático
    após 4 falhas e pela tela de Auditoria (relatório de acessos)."""
    __tablename__ = "tentativas_login"
    id = db.Column(db.Integer, primary_key=True)
    momento = db.Column(db.DateTime, default=_agora)
    email_tentado = db.Column(db.String(120))
    ip = db.Column(db.String(45))       # IPv4 ou IPv6
    sucesso = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {"id": self.id, "momento": self.momento.isoformat() if self.momento else None,
                "email_tentado": self.email_tentado, "ip": self.ip, "sucesso": self.sucesso}


class BloqueioAcesso(db.Model):
    """IP ou e-mail bloqueado depois de 4 tentativas erradas seguidas.

    A liberação é sempre manual (feita pelo administrador em Auditoria) —
    não existe expiração automática por tempo.
    """
    __tablename__ = "bloqueios_acesso"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)   # ip | email
    valor = db.Column(db.String(120), nullable=False)
    criado_em = db.Column(db.DateTime, default=_agora)
    liberado = db.Column(db.Boolean, default=False)
    liberado_por = db.Column(db.String(120))
    liberado_em = db.Column(db.DateTime)

    def to_dict(self):
        return {"id": self.id, "tipo": self.tipo, "valor": self.valor,
                "criado_em": self.criado_em.isoformat() if self.criado_em else None,
                "liberado": self.liberado, "liberado_por": self.liberado_por,
                "liberado_em": self.liberado_em.isoformat() if self.liberado_em else None}
