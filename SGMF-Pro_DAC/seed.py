"""Popula o sistema com dados de demonstração.

Uso:  python seed.py
Serve para conhecer as telas com números reais. Antes de usar de verdade,
apague o banco (database/sgmf.db) e comece com seus próprios cadastros.
"""
import random
from datetime import date, timedelta

from app import app
from extensions import db
from models import (Abastecimento, Fornecedor, ItemOS, Motorista, Orcamento,
                    OrdemServico, Peca, Pneu, Usuario, Veiculo)
from services.calculos import movimentar_estoque, recalcular_abastecimento
from services.tempo import hoje as data_de_hoje

random.seed(7)

VEICULOS = [
    ("FR-101", "ABC1D23", "Mercedes-Benz", "OF-1721", 2019, "Ônibus", "Transporte escolar"),
    ("FR-102", "ABC2D34", "Volkswagen", "15.190", 2020, "Caminhão", "Obras"),
    ("FR-103", "ABC3D45", "Iveco", "Daily 45-170", 2021, "Van escolar", "Transporte escolar"),
    ("FR-104", "ABC4D56", "Fiat", "Ducato", 2022, "Van escolar", "Saúde"),
    ("FR-105", "ABC5D67", "Ford", "Ranger", 2023, "Utilitário", "Administrativo"),
    ("FR-106", "ABC6D78", "Volvo", "B270F", 2018, "Ônibus", "Transporte escolar"),
]

MOTORISTAS = [("Antônio Ribeiro", "D"), ("Marcos Vinícius Alves", "D"), ("Cláudia Menezes", "D"),
              ("José Carlos Farias", "E"), ("Rita de Cássia Lopes", "D")]

FORNECEDORES = [("Oficina Central Diesel", "Oficina"), ("Auto Mecânica Bandeira", "Oficina"),
                ("Posto Rodovia BR-101", "Posto"), ("Posto Cidade Alta", "Posto"),
                ("Distribuidora Peças Sul", "Fornecedor")]

PECAS = [
    ("FIL-001", "Filtro de óleo motor", "Motor", "UN", 40, 10, 48.90),
    ("FIL-002", "Filtro de combustível", "Motor", "UN", 25, 8, 62.00),
    ("FIL-003", "Filtro de ar", "Motor", "UN", 18, 6, 129.50),
    ("OLE-001", "Óleo motor 15W40 (litro)", "Motor", "L", 180, 60, 27.40),
    ("PAS-001", "Pastilha de freio dianteira", "Freios", "JG", 12, 4, 289.00),
    ("LON-001", "Lona de freio traseira", "Freios", "JG", 8, 3, 415.00),
    ("AMO-001", "Amortecedor dianteiro", "Suspensão", "UN", 6, 2, 512.00),
    ("COR-001", "Correia do alternador", "Motor", "UN", 9, 4, 98.70),
    ("BAT-001", "Bateria 150Ah", "Elétrica", "UN", 4, 2, 890.00),
    ("MAN-001", "Mangueira do radiador", "Arrefecimento", "UN", 7, 3, 145.00),
]

DEFEITOS = [
    ("Preventiva", "Motor", "Revisão preventiva: troca de óleo, filtros e verificação geral."),
    ("Corretiva", "Freios", "Freio traseiro com ruído. Substituição de lonas e regulagem."),
    ("Corretiva", "Elétrica", "Farol direito sem funcionar. Troca de chicote e lâmpada."),
    ("Corretiva", "Suspensão", "Barulho na suspensão dianteira. Amortecedores substituídos."),
    ("Emergencial", "Arrefecimento", "Superaquecimento na via. Mangueira rompida substituída."),
    ("Preventiva", "Pneus", "Rodízio e calibragem de pneus com medição de sulco."),
]


def limpar():
    for modelo in (ItemOS, OrdemServico, Abastecimento, Pneu, Orcamento):
        modelo.query.delete()
    db.session.query(Peca).delete()
    db.session.query(Veiculo).delete()
    db.session.query(Motorista).delete()
    db.session.query(Fornecedor).delete()
    db.session.commit()


def popular():
    hoje = data_de_hoje()
    limpar()

    fornecedores = []
    for nome, tipo in FORNECEDORES:
        f = Fornecedor(nome=nome, tipo=tipo, cidade="Sua Cidade",
                       telefone="(00) 0000-0000", ativo=True)
        db.session.add(f)
        fornecedores.append(f)

    motoristas = []
    for nome, cat in MOTORISTAS:
        m = Motorista(nome=nome, categoria_cnh=cat, cnh=str(random.randint(10**9, 10**10 - 1)),
                      validade_cnh=hoje + timedelta(days=random.randint(-20, 900)),
                      setor="Operacional", ativo=True)
        db.session.add(m)
        motoristas.append(m)

    veiculos = []
    for prefixo, placa, marca, modelo, ano, tipo, centro in VEICULOS:
        hodometro = random.randint(45_000, 320_000)
        v = Veiculo(prefixo=prefixo, placa=placa, marca=marca, modelo=modelo, ano=ano,
                    tipo=tipo, centro_custo=centro, setor=centro, hodometro=hodometro,
                    situacao="Disponível", km_ultima_troca_oleo=hodometro - random.randint(2000, 11000),
                    intervalo_troca_oleo=10000,
                    data_ultima_preventiva=hoje - timedelta(days=random.randint(20, 140)),
                    intervalo_preventiva_dias=90,
                    orcamento_mensal=random.choice([3500, 4200, 5000, 6000]), ativo=True)
        db.session.add(v)
        veiculos.append(v)
    db.session.flush()

    for codigo, desc, grupo, un, qtd, minimo, custo in PECAS:
        p = Peca(codigo=codigo, descricao=desc, grupo=grupo, unidade=un,
                 estoque_minimo=minimo, custo_unitario=custo,
                 localizacao=f"Prateleira {random.choice('ABC')}{random.randint(1, 5)}",
                 fornecedor_id=fornecedores[-1].id)
        db.session.add(p)
        db.session.flush()
        movimentar_estoque(p.id, "entrada", qtd * 4, custo, documento="Saldo inicial")
    db.session.commit()

    # --- abastecimentos dos últimos 6 meses ---------------------------------
    for v in veiculos:
        km = v.hodometro - random.randint(9000, 15000)
        consumo_base = {"Ônibus": 2.6, "Caminhão": 3.4, "Van escolar": 8.5,
                        "Utilitário": 9.5}.get(v.tipo, 6.0)
        for semana in range(24, -1, -1):
            litros = round(random.uniform(45, 130), 1)
            consumo = consumo_base * random.uniform(0.85, 1.12)
            km += litros * consumo
            preco = round(random.uniform(5.75, 6.45), 2)
            a = Abastecimento(data=hoje - timedelta(days=semana * 6),
                              veiculo_id=v.id, motorista_id=random.choice(motoristas).id,
                              fornecedor_id=random.choice(fornecedores[2:4]).id,
                              combustivel="Diesel S10" if v.tipo != "Utilitário" else "Gasolina",
                              km_atual=round(km), litros=litros, valor_litro=preco,
                              valor_total=round(litros * preco, 2), tanque_cheio=True)
            db.session.add(a)
            db.session.flush()
            recalcular_abastecimento(a)
        v.hodometro = round(km)
    db.session.commit()

    # --- ordens de serviço ---------------------------------------------------
    pecas = Peca.query.all()
    numero = 1
    for v in veiculos:
        for _ in range(random.randint(2, 5)):
            tipo, grupo, descricao = random.choice(DEFEITOS)
            abertura = hoje - timedelta(days=random.randint(1, 165))
            finalizada = random.random() > 0.22
            os_obj = OrdemServico(
                numero=f"OS{hoje.year}{numero:05d}", data_abertura=abertura,
                data_fechamento=abertura + timedelta(days=random.randint(1, 6)) if finalizada else None,
                veiculo_id=v.id, motorista_id=random.choice(motoristas).id,
                fornecedor_id=random.choice(fornecedores[:2]).id,
                mecanico=random.choice(["Paulo Souza", "Edinaldo Lima", "Fábio Nunes"]),
                tipo=tipo, grupo=grupo,
                prioridade=random.choice(["Baixa", "Média", "Alta", "Crítica"]),
                status="Finalizada" if finalizada else
                       random.choice(["Aberta", "Em execução", "Aguardando peça"]),
                km_veiculo=v.hodometro - random.randint(0, 6000), descricao=descricao,
                custo_mao_obra=round(random.uniform(120, 850), 2),
                custo_servicos=round(random.choice([0, 0, 180, 420, 700]), 2),
                avaliacao=random.randint(3, 5) if finalizada else None)
            db.session.add(os_obj)
            db.session.flush()
            numero += 1

            for peca in random.sample(pecas, random.randint(1, 3)):
                qtd = min(random.randint(1, 4), int(peca.quantidade or 0))
                if qtd <= 0:
                    continue
                item = ItemOS(ordem_servico_id=os_obj.id, peca_id=peca.id,
                              descricao=peca.descricao, grupo=peca.grupo,
                              quantidade=qtd, valor_unitario=peca.custo_unitario,
                              baixado_estoque=True)
                db.session.add(item)
                movimentar_estoque(peca.id, "saida", qtd, peca.custo_unitario,
                                   os_id=os_obj.id, observacao="Aplicada na OS")
            if os_obj.status != "Finalizada":
                v.situacao = "Em manutenção"
    db.session.commit()

    # --- pneus ---------------------------------------------------------------
    posicoes = ["Dianteiro Esquerdo", "Dianteiro Direito",
                "Traseiro Esquerdo Externo", "Traseiro Esquerdo Interno",
                "Traseiro Direito Externo", "Traseiro Direito Interno"]
    fogo = 1000
    for v in veiculos:
        for posicao in posicoes:
            fogo += 1
            db.session.add(Pneu(
                numero_fogo=f"P{fogo}", veiculo_id=v.id, posicao=posicao,
                marca=random.choice(["Pirelli", "Michelin", "Goodyear", "Firestone"]),
                medida="275/80 R22.5" if v.tipo in ("Ônibus", "Caminhão") else "225/70 R15",
                sulco_mm=round(random.uniform(2.8, 14.0), 1),
                vida=random.choice(["Novo", "Novo", "1ª recapagem", "2ª recapagem"]),
                km_instalacao=v.hodometro - random.randint(8000, 60000),
                data_instalacao=hoje - timedelta(days=random.randint(60, 700)),
                data_medicao=hoje - timedelta(days=random.randint(0, 25)),
                status="Em uso", custo=round(random.uniform(900, 2400), 2)))

    # --- metas mensais -------------------------------------------------------
    for i in range(6):
        ref = (hoje.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        db.session.add(Orcamento(ano=ref.year, mes=ref.month, categoria="Geral",
                                 meta_valor=random.choice([28000, 30000, 32000])))
    db.session.commit()

    if Usuario.query.count() <= 1:
        operador = Usuario(nome="Operador da garagem", email="operador@sgmf.local",
                           perfil="operador", cargo="Gerente operacional")
        operador.definir_senha("operador123")
        db.session.add(operador)

        # --- exemplos do controle de acesso por tela --------------------
        mecanico = Usuario(nome="Mecânico de plantão", email="mecanico@sgmf.local",
                           perfil="restrito", cargo="Mecânico")
        mecanico.definir_senha("mecanico123")
        mecanico.definir_permissoes([{"tela": "manutencao", "nivel": "visualizar"}])
        db.session.add(mecanico)

        chefe = Usuario(nome="Chefe de oficina", email="chefeoficina@sgmf.local",
                        perfil="restrito", cargo="Chefe de oficina")
        chefe.definir_senha("chefe123")
        chefe.definir_permissoes([
            {"tela": "dashboard", "nivel": "visualizar"},
            {"tela": "alertas", "nivel": "visualizar"},
            {"tela": "manutencao", "nivel": "editar"},
            {"tela": "pneus", "nivel": "editar"},
        ])
        db.session.add(chefe)

        almoxarifado = Usuario(nome="Almoxarifado", email="almoxarifado@sgmf.local",
                               perfil="restrito", cargo="Almoxarifado")
        almoxarifado.definir_senha("almoxarifado123")
        almoxarifado.definir_permissoes([
            {"tela": "dashboard", "nivel": "visualizar"},
            {"tela": "estoque", "nivel": "editar"},
            {"tela": "fornecedores", "nivel": "editar"},
            {"tela": "manutencao", "nivel": "visualizar"},
            {"tela": "pneus", "nivel": "visualizar"},
            {"tela": "veiculos", "nivel": "visualizar"},
            {"tela": "importacao", "nivel": "editar"},
            {"tela": "relatorios", "nivel": "visualizar"},
        ])
        db.session.add(almoxarifado)

        db.session.commit()

    print("Dados de demonstração criados:")
    print(f"  {Veiculo.query.count()} veículos · {Motorista.query.count()} motoristas")
    print(f"  {OrdemServico.query.count()} ordens de serviço · "
          f"{Abastecimento.query.count()} abastecimentos")
    print(f"  {Pneu.query.count()} pneus · {Peca.query.count()} peças em estoque")
    print("\n  Acesso: admin@sgmf.local / admin123  (administrador — acesso total)")
    print("  Acesso: operador@sgmf.local / operador123  (gerente operacional — edita tudo)")
    print("  Acesso: mecanico@sgmf.local / mecanico123  (só visualiza ordens de serviço)")
    print("  Acesso: chefeoficina@sgmf.local / chefe123  (painel, alertas, OS e pneus)")
    print("  Acesso: almoxarifado@sgmf.local / almoxarifado123  (estoque e cadastros)")


if __name__ == "__main__":
    with app.app_context():
        popular()
