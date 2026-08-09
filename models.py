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
    ("combustivel", "Abastecimentos", "Operação"),
    ("pneus", "Pneus", "Operação"),
    ("veiculos", "Veículos", "Cadastros"),
    ("motoristas", "Motoristas", "Cadastros"),
    ("fornecedores", "Oficinas e postos", "Cadastros"),
    ("estoque", "Estoque de peças", "Cadastros"),
    ("importacao", "Importar planilha", "Cadastros"),
    ("orcamento", "Meta x realizado", "Gestão"),
    ("ranking", "Rankings", "Gestão"),
    ("relatorios", "Relatórios", "Gestão"),
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
            "importacao": "editar", "relatorios": "visualizar",
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


class Peca(db.Model):
    """Módulo 11 — estoque de peças."""
    __tablename__ = "pecas"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False, index=True)
    descricao = db.Column(db.String(160), nullable=False)
    grupo = db.Column(db.String(40))       # Motor, Suspensão, Freios, ...
    unidade = db.Column(db.String(10), default="UN")
    quantidade = db.Column(db.Float, default=0)
    estoque_minimo = db.Column(db.Float, default=0)
    custo_unitario = db.Column(db.Float, default=0)
    localizacao = db.Column(db.String(40))
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"))
    fornecedor = db.relationship("Fornecedor")

    def to_dict(self):
        return {"id": self.id, "codigo": self.codigo, "descricao": self.descricao,
                "grupo": self.grupo, "unidade": self.unidade, "quantidade": self.quantidade,
                "estoque_minimo": self.estoque_minimo, "custo_unitario": self.custo_unitario,
                "valor_total": round((self.quantidade or 0) * (self.custo_unitario or 0), 2),
                "localizacao": self.localizacao, "fornecedor_id": self.fornecedor_id,
                "fornecedor_nome": self.fornecedor.nome if self.fornecedor else None,
                "abaixo_minimo": (self.quantidade or 0) <= (self.estoque_minimo or 0),
                "identificacao": f"{self.codigo} · {self.descricao}"}


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
    peca = db.relationship("Peca")

    def to_dict(self):
        return {"id": self.id, "data": self.data.isoformat() if self.data else None,
                "peca_id": self.peca_id,
                "peca_descricao": f"{self.peca.codigo} · {self.peca.descricao}" if self.peca else None,
                "tipo": self.tipo, "quantidade": self.quantidade,
                "custo_unitario": self.custo_unitario,
                "valor_total": round((self.quantidade or 0) * (self.custo_unitario or 0), 2),
                "documento": self.documento, "ordem_servico_id": self.ordem_servico_id,
                "observacao": self.observacao}


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
        return round(sum((i.quantidade or 0) * (i.valor_unitario or 0) for i in self.itens), 2)

    @property
    def custo_total(self):
        return round(self.custo_pecas + (self.custo_mao_obra or 0) + (self.custo_servicos or 0), 2)

    @property
    def dias_parado(self):
        fim = self.data_fechamento or _hoje()
        return max((fim - self.data_abertura).days, 0) if self.data_abertura else 0

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
            "descricao": self.descricao, "custo_mao_obra": self.custo_mao_obra,
            "custo_servicos": self.custo_servicos, "custo_pecas": self.custo_pecas,
            "custo_total": self.custo_total, "dias_parado": self.dias_parado,
            "avaliacao": self.avaliacao, "qtd_anexos": len(self.anexos),
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
    baixado_estoque = db.Column(db.Boolean, default=False)
    peca = db.relationship("Peca")

    def to_dict(self):
        return {"id": self.id, "ordem_servico_id": self.ordem_servico_id,
                "peca_id": self.peca_id, "descricao": self.descricao, "grupo": self.grupo,
                "quantidade": self.quantidade, "valor_unitario": self.valor_unitario,
                "valor_total": round((self.quantidade or 0) * (self.valor_unitario or 0), 2),
                "baixado_estoque": self.baixado_estoque}


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
