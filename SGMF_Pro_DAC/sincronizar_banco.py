# -*- coding: utf-8 -*-
"""
sincronizar_banco.py  -  SGMF Pro

O QUE ESTE SCRIPT FAZ:
  1. Faz backup do arquivo .db
  2. Descobre qual e a ultima migracao (head) do Alembic
  3. Marca o alembic_version como estando nessa ultima migracao
     (assim ele para de tentar recriar tabelas que ja existem)
  4. Compara o banco REAL com os modelos do codigo e cria/adiciona
     apenas o que estiver realmente faltando

COMO USAR:
  1. Feche o app (Ctrl + C no terminal onde o Flask esta rodando)
  2. Coloque este arquivo dentro da pasta SGMF_Pro_DAC
  3. No terminal:
         cd "C:\\Users\\asaph\\OneDrive\\Area de Trabalho\\SGMF_Pro_DAC"
         python sincronizar_banco.py
  4. Leia a saida ate o fim
  5. Suba o app:  python app.py
"""

import glob
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime

print("=" * 62)
print("SINCRONIZADOR DE BANCO - SGMF Pro")
print("=" * 62)

PASTA = os.getcwd()
sys.path.insert(0, PASTA)


# ------------------------------------------------------------------
# 1. LOCALIZAR O BANCO
# ------------------------------------------------------------------
def achar_banco():
    preferidos = [
        "instance/sgmf.db", "instance/database.db", "instance/app.db",
        "instance/sgmf_pro.db", "sgmf.db", "database.db", "app.db",
    ]
    for c in preferidos:
        if os.path.exists(c):
            return c
    encontrados = []
    for raiz, dirs, arquivos in os.walk("."):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "__pycache__", "venv", ".venv", "node_modules")]
        for arq in arquivos:
            if arq.endswith((".db", ".sqlite", ".sqlite3")) and ".backup_" not in arq:
                encontrados.append(os.path.join(raiz, arq))
    if len(encontrados) == 1:
        return encontrados[0]
    if len(encontrados) > 1:
        print("\nEncontrei mais de um banco:")
        for i, e in enumerate(encontrados, 1):
            print(f"  [{i}] {e}  ({os.path.getsize(e)} bytes)")
        escolha = input("Digite o numero do banco correto: ").strip()
        try:
            return encontrados[int(escolha) - 1]
        except Exception:
            return None
    return None


banco = achar_banco()
if not banco:
    print("\nERRO: nao encontrei o arquivo do banco (.db).")
    print("Rode o script de dentro da pasta SGMF_Pro_DAC.")
    sys.exit(1)

print(f"\n[1/4] Banco: {banco}")

carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = f"{banco}.backup_{carimbo}"
shutil.copy2(banco, backup)
print(f"      Backup: {backup}")

conn = sqlite3.connect(banco)
cur = conn.cursor()


def tabelas_do_banco():
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def colunas_de(tabela):
    cur.execute(f'PRAGMA table_info("{tabela}")')
    return {r[1] for r in cur.fetchall()}


# ------------------------------------------------------------------
# 2. DESCOBRIR A ULTIMA MIGRACAO (HEAD)
# ------------------------------------------------------------------
print("\n[2/4] Procurando as migracoes do Alembic...")

pasta_versions = None
for candidato in ("alembic/versions", "migrations/versions",
                  "alembic\\versions", "migrations\\versions"):
    if os.path.isdir(candidato):
        pasta_versions = candidato
        break

head = None
if pasta_versions:
    revisoes = {}
    downs = set()
    for arquivo in glob.glob(os.path.join(pasta_versions, "*.py")):
        try:
            texto = open(arquivo, encoding="utf-8").read()
        except UnicodeDecodeError:
            texto = open(arquivo, encoding="latin-1").read()

        m_rev = re.search(
            r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]", texto, re.M)
        m_down = re.search(
            r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]", texto, re.M)

        if m_rev:
            rev = m_rev.group(1)
            revisoes[rev] = os.path.basename(arquivo)
            if m_down:
                downs.add(m_down.group(1))

    candidatos_head = [r for r in revisoes if r not in downs]
    print(f"      {len(revisoes)} migracao(oes) encontrada(s) em {pasta_versions}")
    if len(candidatos_head) == 1:
        head = candidatos_head[0]
        print(f"      Ultima migracao (head): {head}  ->  {revisoes[head]}")
    elif len(candidatos_head) > 1:
        print(f"      ATENCAO: mais de um head: {candidatos_head}")
        print("      Nao vou mexer no alembic_version automaticamente.")
    else:
        print("      Nao consegui identificar o head.")
else:
    print("      Nao achei a pasta de migracoes (alembic/versions ou migrations/versions).")

# ------------------------------------------------------------------
# 3. MARCAR O ALEMBIC COMO ATUALIZADO
# ------------------------------------------------------------------
if "alembic_version" not in tabelas_do_banco():
    cur.execute(
        "CREATE TABLE alembic_version ("
        "version_num VARCHAR(32) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    print("      Tabela alembic_version criada.")

cur.execute("SELECT version_num FROM alembic_version")
antes = [r[0] for r in cur.fetchall()]
print(f"      alembic_version ANTES:  {antes if antes else '(vazio)'}")

if head:
    cur.execute("DELETE FROM alembic_version")
    cur.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (head,))
    conn.commit()
    print(f"      alembic_version DEPOIS: ['{head}']")
else:
    print("      alembic_version mantido como estava.")

# ------------------------------------------------------------------
# 4. COMPARAR O BANCO COM OS MODELOS DO CODIGO
# ------------------------------------------------------------------
print("\n[3/4] Lendo os modelos do codigo...")

metadata = None
origem = None

tentativas = [
    ("models", "db"), ("models", "Base"),
    ("extensions", "db"), ("database", "db"),
    ("app", "db"), ("models.base", "db"),
]

for modulo, atributo in tentativas:
    try:
        mod = __import__(modulo, fromlist=[atributo])
        obj = getattr(mod, atributo, None)
        if obj is not None and hasattr(obj, "metadata"):
            if obj.metadata.tables:
                metadata = obj.metadata
                origem = f"{modulo}.{atributo}"
                break
    except Exception:
        continue

if metadata is None:
    print("      Nao consegui importar os modelos automaticamente.")
    print("      A parte 1 (alembic) ja foi feita - isso costuma resolver.")
    print("      Rode 'python app.py' e veja se sobe.")
else:
    print(f"      Modelos carregados de: {origem}")
    print(f"      {len(metadata.tables)} tabela(s) definida(s) no codigo")

    from sqlalchemy.dialects import sqlite as dialeto_sqlite
    from sqlalchemy.schema import CreateTable

    dialeto = dialeto_sqlite.dialect()
    no_banco = tabelas_do_banco()

    print("\n[4/4] Comparando e corrigindo...")
    tabelas_criadas = []
    colunas_add = []
    avisos = []

    for nome_tabela, tabela in metadata.tables.items():

        # --- tabela inteira faltando ---
        if nome_tabela not in no_banco:
            try:
                sql = str(CreateTable(tabela).compile(dialect=dialeto))
                cur.execute(sql)
                tabelas_criadas.append(nome_tabela)
                print(f"      + TABELA criada: {nome_tabela}")
            except Exception as e:
                avisos.append(f"tabela {nome_tabela}: {e}")
            continue

        # --- colunas faltando ---
        existentes = colunas_de(nome_tabela)
        for coluna in tabela.columns:
            if coluna.name in existentes:
                continue
            try:
                tipo = coluna.type.compile(dialect=dialeto)
            except Exception:
                tipo = "VARCHAR"

            ddl = f'ALTER TABLE "{nome_tabela}" ADD COLUMN "{coluna.name}" {tipo}'

            if coluna.server_default is not None:
                try:
                    ddl += f" DEFAULT {coluna.server_default.arg.text}"
                except Exception:
                    pass
            elif not coluna.nullable:
                # SQLite nao aceita NOT NULL sem default em coluna nova
                avisos.append(
                    f"{nome_tabela}.{coluna.name} era NOT NULL - "
                    f"criada como opcional (preencha os registros antigos)"
                )

            try:
                cur.execute(ddl)
                colunas_add.append(f"{nome_tabela}.{coluna.name}")
                print(f"      + coluna: {nome_tabela}.{coluna.name} ({tipo})")
            except Exception as e:
                avisos.append(f"{nome_tabela}.{coluna.name}: {e}")

    conn.commit()

    print("\n" + "-" * 62)
    print("RESUMO")
    print("-" * 62)
    print(f"Tabelas criadas ..... {len(tabelas_criadas)}")
    print(f"Colunas adicionadas . {len(colunas_add)}")
    if not tabelas_criadas and not colunas_add:
        print("Nada faltava - a estrutura ja batia com o codigo.")
    if avisos:
        print(f"\nAvisos ({len(avisos)}):")
        for a in avisos:
            print(f"  ! {a}")

    # conferencia final
    print("\nConferencia final:")
    no_banco = tabelas_do_banco()
    pendencias = 0
    for nome_tabela, tabela in metadata.tables.items():
        if nome_tabela not in no_banco:
            print(f"  X tabela ainda faltando: {nome_tabela}")
            pendencias += 1
            continue
        existentes = colunas_de(nome_tabela)
        for coluna in tabela.columns:
            if coluna.name not in existentes:
                print(f"  X coluna ainda faltando: {nome_tabela}.{coluna.name}")
                pendencias += 1
    if pendencias == 0:
        print("  OK - banco e codigo estao batendo.")

conn.close()

print("\n" + "=" * 62)
print("PRONTO.")
print("Agora rode:  python app.py")
print(f"\nSe algo der errado, apague o arquivo:\n  {banco}")
print(f"e renomeie este backup de volta:\n  {backup}")
print("=" * 62)
