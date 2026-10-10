# corrigir_banco.py
# Adiciona as colunas que faltam na tabela 'pecas' e acerta o alembic_version.

import os
import shutil
import sqlite3
import sys
from datetime import datetime

# ---------------------------------------------------------------
# 1. Localizar o arquivo do banco
# ---------------------------------------------------------------
CANDIDATOS = [
    "instance/sgmf.db",
    "instance/database.db",
    "instance/app.db",
    "sgmf.db",
    "database.db",
    "app.db",
]


def achar_banco():
    for caminho in CANDIDATOS:
        if os.path.exists(caminho):
            return caminho
    # varre a pasta procurando qualquer .db / .sqlite
    for raiz, _, arquivos in os.walk("."):
        if "site-packages" in raiz or ".git" in raiz:
            continue
        for arq in arquivos:
            if arq.endswith((".db", ".sqlite", ".sqlite3")):
                return os.path.join(raiz, arq)
    return None


banco = achar_banco()
if not banco:
    print("ERRO: nao encontrei nenhum arquivo de banco (.db) nesta pasta.")
    print("Rode o script de dentro da pasta SGMF_Pro_DAC.")
    sys.exit(1)

print(f"Banco encontrado: {banco}")

# ---------------------------------------------------------------
# 2. Backup
# ---------------------------------------------------------------
carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = f"{banco}.backup_{carimbo}"
shutil.copy2(banco, backup)
print(f"Backup criado: {backup}")

conn = sqlite3.connect(banco)
cur = conn.cursor()

# ---------------------------------------------------------------
# 3. Colunas que o codigo espera em 'pecas'
#    (extraidas do SELECT que aparece no seu erro)
# ---------------------------------------------------------------
COLUNAS_PECAS = {
    "codigo": "VARCHAR(60)",
    "referencia": "VARCHAR(60)",
    "descricao": "VARCHAR(200)",
    "grupo": "VARCHAR(60)",
    "unidade": "VARCHAR(10)",
    "quantidade": "FLOAT DEFAULT 0",
    "estoque_minimo": "FLOAT DEFAULT 0",
    "custo_unitario": "FLOAT DEFAULT 0",
    "localizacao": "VARCHAR(60)",
    "fornecedor_id": "INTEGER",
    "ncm": "VARCHAR(10)",
    "cfop_entrada": "VARCHAR(10)",
    "cst_icms": "VARCHAR(10)",
    "cst_pis": "VARCHAR(10)",
    "cst_cofins": "VARCHAR(10)",
    "cst_ibs_cbs": "VARCHAR(10)",
    "classificacao_tributaria": "VARCHAR(60)",
}


def tabela_existe(nome):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nome,))
    return cur.fetchone() is not None


def colunas_de(tabela):
    cur.execute(f"PRAGMA table_info({tabela})")
    return {linha[1] for linha in cur.fetchall()}


if not tabela_existe("pecas"):
    print("ERRO: a tabela 'pecas' nao existe neste banco.")
    print("Nesse caso o banco esta vazio - apague o .db e deixe o app recriar.")
    conn.close()
    sys.exit(1)

existentes = colunas_de("pecas")
print(f"\nColunas atuais em 'pecas': {sorted(existentes)}")

adicionadas = []
for coluna, tipo in COLUNAS_PECAS.items():
    if coluna not in existentes:
        try:
            cur.execute(f"ALTER TABLE pecas ADD COLUMN {coluna} {tipo}")
            adicionadas.append(coluna)
            print(f"  + adicionada: {coluna} ({tipo})")
        except sqlite3.OperationalError as e:
            print(f"  ! falhou em {coluna}: {e}")

if not adicionadas:
    print("  (nenhuma coluna faltando em 'pecas')")

# ---------------------------------------------------------------
# 4. Acertar o alembic_version
#    O erro mostra que ele tenta rodar a revisao inicial 4fb38b1f9382
#    num banco que ja existe. Marcamos como aplicada.
# ---------------------------------------------------------------
REVISAO_INICIAL = "4fb38b1f9382"

if not tabela_existe("alembic_version"):
    cur.execute(
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    print("\nTabela alembic_version criada.")

cur.execute("SELECT version_num FROM alembic_version")
versao = cur.fetchall()
print(f"alembic_version antes: {versao}")

if not versao:
    cur.execute(
        "INSERT INTO alembic_version (version_num) VALUES (?)", (REVISAO_INICIAL,)
    )
    print(f"alembic_version definido como: {REVISAO_INICIAL}")
else:
    print("alembic_version ja preenchido - mantido como esta.")

conn.commit()

# ---------------------------------------------------------------
# 5. Conferencia final
# ---------------------------------------------------------------
print("\n--- CONFERENCIA ---")
finais = colunas_de("pecas")
faltando = [c for c in COLUNAS_PECAS if c not in finais]
if faltando:
    print(f"AINDA FALTAM: {faltando}")
else:
    print("Todas as colunas esperadas existem em 'pecas'. OK.")

cur.execute("SELECT version_num FROM alembic_version")
print(f"alembic_version depois: {cur.fetchall()}")

conn.close()
print(f"\nPronto. Se algo der errado, restaure o backup:\n  {backup}")
