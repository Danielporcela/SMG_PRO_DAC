import os
import sys

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)

TAMANHOS = {
    "roupa": ["PP", "P", "M", "G", "GG", "XG"],
    "calcado": [str(n) for n in range(34, 47)],
    "luva": ["07", "08", "09", "10"],
    "unico": ["Único"],
}

EQUIVALENTES = {
    "roupa": "roupa",
    "vestuario": "roupa",
    "vestuário": "roupa",
    "calcado": "calcado",
    "calçado": "calcado",
    "sapato": "calcado",
    "luva": "luva",
    "luvas": "luva",
    "unico": "unico",
    "único": "unico",
    "sem tamanho": "unico",
}


def normalizar_tipo(valor):
    return EQUIVALENTES.get((valor or "").strip().lower(), "roupa")


def url_banco():
    valor = os.environ.get("DATABASE_URL", "").strip()
    if valor.startswith("postgres://"):
        valor = valor.replace("postgres://", "postgresql://", 1)
    if valor:
        return valor

    base = Path(__file__).resolve().parent
    return "sqlite:///" + str(base / "database" / "sgmf.db")


def coluna_existe(inspetor, tabela, coluna):
    return coluna in {c["name"] for c in inspetor.get_columns(tabela)}


def adicionar_coluna(conexao, inspetor, tabela, coluna, definicao):
    if coluna_existe(inspetor, tabela, coluna):
        print(f"OK {tabela}.{coluna} já existe")
        return

    conexao.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}"))
    print(f"OK {tabela}.{coluna} criada")


def criar_tabela_saldos(engine):
    inspetor = inspect(engine)
    if "saldos_uniforme" in inspetor.get_table_names():
        print("OK saldos_uniforme já existe")
        return

    metadata = MetaData()
    Table("itens_uniforme", metadata, autoload_with=engine)

    Table(
        "saldos_uniforme",
        metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "item_id",
            Integer,
            ForeignKey("itens_uniforme.id"),
            nullable=False,
        ),
        Column("tamanho", String(10), nullable=False),
        Column("quantidade", Float, default=0),
        Column("estoque_minimo", Float, default=0),
        UniqueConstraint(
            "item_id",
            "tamanho",
            name="uq_saldo_item_tamanho",
        ),
    )

    metadata.tables["saldos_uniforme"].create(engine, checkfirst=True)
    print("OK saldos_uniforme criada")


def preparar_estrutura(engine):
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())

    if "itens_uniforme" not in tabelas:
        raise RuntimeError(
            "A tabela itens_uniforme não existe. "
            "O módulo base de uniformes precisa estar instalado antes desta correção."
        )

    with engine.begin() as conexao:
        adicionar_coluna(
            conexao,
            inspetor,
            "itens_uniforme",
            "tipo_tamanho",
            "VARCHAR(12)",
        )

        if "movimentos_uniforme" in tabelas:
            adicionar_coluna(
                conexao,
                inspetor,
                "movimentos_uniforme",
                "tamanho",
                "VARCHAR(10)",
            )

        conexao.execute(
            text(
                "UPDATE itens_uniforme "
                "SET tipo_tamanho = 'roupa' "
                "WHERE tipo_tamanho IS NULL OR TRIM(tipo_tamanho) = ''"
            )
        )

    criar_tabela_saldos(engine)


def inserir_saldo(conexao, item_id, tamanho, quantidade, minimo):
    conexao.execute(
        text(
            "INSERT INTO saldos_uniforme "
            "(item_id, tamanho, quantidade, estoque_minimo) "
            "VALUES (:item_id, :tamanho, :quantidade, :estoque_minimo)"
        ),
        {
            "item_id": item_id,
            "tamanho": tamanho,
            "quantidade": quantidade,
            "estoque_minimo": minimo,
        },
    )


def preparar_saldos(engine):
    itens_processados = 0
    legados_criados = 0

    with engine.begin() as conexao:
        itens = conexao.execute(
            text(
                "SELECT id, codigo, descricao, tipo_tamanho, quantidade, estoque_minimo "
                "FROM itens_uniforme ORDER BY id"
            )
        ).mappings().all()

        for item in itens:
            item_id = item["id"]
            tipo = normalizar_tipo(item["tipo_tamanho"])
            minimo = float(item["estoque_minimo"] or 0)
            total_antigo = float(item["quantidade"] or 0)

            conexao.execute(
                text(
                    "UPDATE itens_uniforme "
                    "SET tipo_tamanho = :tipo "
                    "WHERE id = :item_id"
                ),
                {"tipo": tipo, "item_id": item_id},
            )

            saldos = conexao.execute(
                text(
                    "SELECT id, tamanho, quantidade, estoque_minimo "
                    "FROM saldos_uniforme "
                    "WHERE item_id = :item_id"
                ),
                {"item_id": item_id},
            ).mappings().all()

            existentes = {str(s["tamanho"] or "") for s in saldos}

            for tamanho in TAMANHOS[tipo]:
                if tamanho not in existentes:
                    inserir_saldo(
                        conexao,
                        item_id,
                        tamanho,
                        0,
                        minimo,
                    )

            saldos = conexao.execute(
                text(
                    "SELECT id, tamanho, quantidade "
                    "FROM saldos_uniforme "
                    "WHERE item_id = :item_id"
                ),
                {"item_id": item_id},
            ).mappings().all()

            ha_saldo_detalhado = any(
                abs(float(s["quantidade"] or 0)) > 0.000001
                for s in saldos
            )

            if not ha_saldo_detalhado and abs(total_antigo) > 0.000001:
                legado = next(
                    (
                        s
                        for s in saldos
                        if str(s["tamanho"] or "").strip().upper() == "LEGADO"
                    ),
                    None,
                )

                if legado is None:
                    inserir_saldo(
                        conexao,
                        item_id,
                        "LEGADO",
                        total_antigo,
                        0,
                    )
                else:
                    conexao.execute(
                        text(
                            "UPDATE saldos_uniforme "
                            "SET quantidade = :quantidade "
                            "WHERE id = :saldo_id"
                        ),
                        {
                            "quantidade": total_antigo,
                            "saldo_id": legado["id"],
                        },
                    )

                legados_criados += 1

            total_novo = conexao.execute(
                text(
                    "SELECT COALESCE(SUM(quantidade), 0) "
                    "FROM saldos_uniforme "
                    "WHERE item_id = :item_id"
                ),
                {"item_id": item_id},
            ).scalar_one()

            conexao.execute(
                text(
                    "UPDATE itens_uniforme "
                    "SET quantidade = :quantidade "
                    "WHERE id = :item_id"
                ),
                {
                    "quantidade": float(total_novo or 0),
                    "item_id": item_id,
                },
            )

            itens_processados += 1

    print(f"OK {itens_processados} item ou itens processados")
    print(f"OK {legados_criados} saldo ou saldos antigos preservados como LEGADO")


def conferir(engine):
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())

    obrigatorias = {
        "itens_uniforme",
        "saldos_uniforme",
    }
    faltando_tabelas = sorted(obrigatorias.difference(tabelas))

    if faltando_tabelas:
        raise RuntimeError(
            "Ainda faltam tabelas: " + ", ".join(faltando_tabelas)
        )

    colunas_itens = {c["name"] for c in inspetor.get_columns("itens_uniforme")}
    if "tipo_tamanho" not in colunas_itens:
        raise RuntimeError("Ainda falta itens_uniforme.tipo_tamanho")

    if "movimentos_uniforme" in tabelas:
        colunas_mov = {
            c["name"]
            for c in inspetor.get_columns("movimentos_uniforme")
        }
        if "tamanho" not in colunas_mov:
            raise RuntimeError("Ainda falta movimentos_uniforme.tamanho")

    with engine.connect() as conexao:
        itens = conexao.execute(
            text("SELECT COUNT(*) FROM itens_uniforme")
        ).scalar_one()

        saldos = conexao.execute(
            text("SELECT COUNT(*) FROM saldos_uniforme")
        ).scalar_one()

    print(f"OK conferência final com {itens} item ou itens e {saldos} saldo ou saldos")


def main():
    try:
        engine = create_engine(url_banco(), pool_pre_ping=True)
        preparar_estrutura(engine)
        preparar_saldos(engine)
        conferir(engine)
        print("CORREÇÃO CONCLUÍDA")
        return 0
    except Exception as erro:
        print(f"ERRO {type(erro).__name__}: {erro}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
