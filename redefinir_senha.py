# -*- coding: utf-8 -*-
"""
redefinir_senha.py  -  SGMF Pro (banco LOCAL)

O QUE FAZ:
  1. Mostra os usuarios cadastrados no banco local
  2. Deixa voce escolher um deles (ou criar o admin, se nao existir nenhum)
  3. Redefine a senha e garante que o usuario esteja ATIVO e como ADMIN

COMO USAR:
  1. FECHE o app (Ctrl + C no terminal onde o Flask esta rodando)
  2. Coloque este arquivo dentro da pasta SGMF_Pro_DAC
  3. No terminal:
         cd "C:\\Users\\asaph\\OneDrive\\Area de Trabalho\\SGMF_Pro_DAC"
         python redefinir_senha.py
  4. Siga as perguntas na tela
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime

print("=" * 62)
print("REDEFINIR SENHA - SGMF Pro (banco local)")
print("=" * 62)

sys.path.insert(0, os.getcwd())


# ==================================================================
# CAMINHO 1 - PELO PROPRIO SISTEMA (preferido)
# ==================================================================
def tentar_pelo_orm():
    """Usa os models do projeto - o jeito mais seguro, pois usa
    exatamente a mesma funcao de senha que o login usa."""

    # --- achar o app Flask ---
    app = None
    try:
        import app as modulo_app
        app = getattr(modulo_app, "app", None)
        if app is None:
            criar = getattr(modulo_app, "create_app", None) or \
                    getattr(modulo_app, "criar_app", None)
            if criar:
                app = criar()
    except Exception as e:
        print(f"      (nao consegui importar app.py: {e})")
        return False

    if app is None:
        print("      (nao achei o objeto 'app' dentro de app.py)")
        return False

    # --- achar db e Usuario ---
    db = None
    Usuario = None
    for modulo in ("models", "extensions", "app", "database"):
        try:
            m = __import__(modulo, fromlist=["db", "Usuario"])
            db = db or getattr(m, "db", None)
            Usuario = Usuario or getattr(m, "Usuario", None)
        except Exception:
            continue

    if db is None or Usuario is None:
        print("      (nao achei 'db' ou o model 'Usuario')")
        return False

    ctx = app.app_context()
    ctx.push()

    usuarios = Usuario.query.all()
    print(f"\n      Usuarios encontrados: {len(usuarios)}")

    def rotulo(u):
        email = getattr(u, "email", "") or ""
        nome = getattr(u, "nome", "") or ""
        perfil = getattr(u, "perfil", "") or ""
        ativo = getattr(u, "ativo", True)
        return f"{email:32} | {nome:22} | {perfil:10} | {'ativo' if ativo else 'INATIVO'}"

    if usuarios:
        print()
        for i, u in enumerate(usuarios, 1):
            print(f"  [{i}] {rotulo(u)}")
        print(f"  [0] criar um usuario admin novo")
        escolha = input("\nDigite o numero do usuario: ").strip()
    else:
        print("      Nenhum usuario cadastrado - vou criar o admin.")
        escolha = "0"

    if escolha == "0":
        email = input("E-mail do novo admin [admin@sgmf.local]: ").strip() \
                or "admin@sgmf.local"
        existente = Usuario.query.filter_by(email=email).first()
        if existente:
            print("      Esse e-mail ja existe - vou apenas redefinir a senha dele.")
            usuario = existente
        else:
            usuario = Usuario(email=email)
            for campo, valor in (("nome", "Administrador"),
                                 ("perfil", "Admin"),
                                 ("ativo", True)):
                if hasattr(usuario, campo):
                    setattr(usuario, campo, valor)
            db.session.add(usuario)
    else:
        try:
            usuario = usuarios[int(escolha) - 1]
        except Exception:
            print("      Opcao invalida.")
            return False

    nova = input("Nova senha [admin123]: ").strip() or "admin123"

    # --- aplicar a senha usando o metodo do proprio model ---
    aplicada = False
    for metodo in ("set_senha", "definir_senha", "set_password",
                   "gerar_senha", "senha_hash_set"):
        if hasattr(usuario, metodo):
            getattr(usuario, metodo)(nova)
            aplicada = True
            print(f"      Senha aplicada via {metodo}()")
            break

    if not aplicada and hasattr(usuario, "senha"):
        try:
            usuario.senha = nova          # property com setter
            aplicada = True
            print("      Senha aplicada via propriedade .senha")
        except Exception:
            aplicada = False

    if not aplicada:
        from werkzeug.security import generate_password_hash
        for campo in ("senha_hash", "password_hash", "hash_senha", "senha"):
            if hasattr(usuario, campo):
                setattr(usuario, campo, generate_password_hash(nova))
                aplicada = True
                print(f"      Senha aplicada direto no campo {campo}")
                break

    if not aplicada:
        print("      NAO consegui identificar o campo de senha do model.")
        return False

    # garantir acesso
    if hasattr(usuario, "ativo"):
        usuario.ativo = True
    if hasattr(usuario, "perfil") and not getattr(usuario, "perfil", None):
        usuario.perfil = "Admin"

    db.session.commit()

    print("\n" + "-" * 62)
    print("PRONTO - senha redefinida")
    print(f"  E-mail: {getattr(usuario, 'email', '?')}")
    print(f"  Senha : {nova}")
    print(f"  Perfil: {getattr(usuario, 'perfil', '?')}")
    print("-" * 62)
    return True


# ==================================================================
# CAMINHO 2 - DIRETO NO ARQUIVO .DB (reserva)
# ==================================================================
def tentar_pelo_sqlite():
    caminhos = ["database/sgmf.db", "instance/sgmf.db", "sgmf.db"]
    banco = next((c for c in caminhos if os.path.exists(c)), None)
    if not banco:
        for raiz, dirs, arqs in os.walk("."):
            dirs[:] = [d for d in dirs if d not in
                       (".git", "__pycache__", "venv", ".venv", "node_modules")]
            for a in arqs:
                if a.endswith((".db", ".sqlite", ".sqlite3")) and ".backup_" not in a:
                    banco = os.path.join(raiz, a)
                    break
            if banco:
                break

    if not banco:
        print("      Nao achei o arquivo do banco.")
        return False

    print(f"      Banco: {banco}")
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{banco}.backup_{carimbo}"
    shutil.copy2(banco, backup)
    print(f"      Backup: {backup}")

    conn = sqlite3.connect(banco)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelas = [r[0] for r in cur.fetchall()]
    tabela = next((t for t in ("usuarios", "usuario", "users", "user")
                   if t in tabelas), None)
    if not tabela:
        print(f"      Nao achei a tabela de usuarios. Tabelas: {tabelas}")
        conn.close()
        return False

    cur.execute(f'PRAGMA table_info("{tabela}")')
    colunas = [r[1] for r in cur.fetchall()]
    col_senha = next((c for c in colunas
                      if "senha" in c.lower() or "password" in c.lower()), None)
    col_email = next((c for c in colunas
                      if "email" in c.lower() or "login" in c.lower()), None)

    if not col_senha or not col_email:
        print(f"      Colunas da tabela {tabela}: {colunas}")
        print("      Nao identifiquei as colunas de e-mail/senha.")
        conn.close()
        return False

    cur.execute(f'SELECT rowid, "{col_email}" FROM "{tabela}"')
    linhas = cur.fetchall()

    if linhas:
        print(f"\n      Usuarios na tabela '{tabela}':")
        for i, (rid, email) in enumerate(linhas, 1):
            print(f"  [{i}] {email}")
        escolha = input("\nDigite o numero do usuario: ").strip()
        try:
            rowid = linhas[int(escolha) - 1][0]
            email_alvo = linhas[int(escolha) - 1][1]
        except Exception:
            print("      Opcao invalida.")
            conn.close()
            return False
    else:
        print("      Tabela de usuarios vazia - crie o admin pelo seed do projeto.")
        conn.close()
        return False

    nova = input("Nova senha [admin123]: ").strip() or "admin123"

    from werkzeug.security import generate_password_hash
    novo_hash = generate_password_hash(nova)

    cur.execute(f'UPDATE "{tabela}" SET "{col_senha}"=? WHERE rowid=?',
                (novo_hash, rowid))

    if "ativo" in colunas:
        cur.execute(f'UPDATE "{tabela}" SET ativo=1 WHERE rowid=?', (rowid,))

    conn.commit()
    conn.close()

    print("\n" + "-" * 62)
    print("PRONTO - senha redefinida")
    print(f"  E-mail: {email_alvo}")
    print(f"  Senha : {nova}")
    print("-" * 62)
    print(f"\nSe der errado, restaure o backup:\n  {backup}")
    return True


# ==================================================================
print("\n[1/2] Tentando pelo proprio sistema (models)...")
ok = False
try:
    ok = tentar_pelo_orm()
except Exception as e:
    print(f"      Falhou: {type(e).__name__}: {e}")

if not ok:
    print("\n[2/2] Tentando direto no arquivo do banco...")
    try:
        ok = tentar_pelo_sqlite()
    except Exception as e:
        print(f"      Falhou: {type(e).__name__}: {e}")

print("\n" + "=" * 62)
if ok:
    print("Agora rode:  python app.py")
    print("e faca login com o e-mail e a senha mostrados acima.")
else:
    print("Nao consegui redefinir. Me mande esta saida inteira.")
print("=" * 62)
