# -*- coding: utf-8 -*-
"""
desbloquear_login.py  -  SGMF Pro

Por que existe: o bloqueio automático de login (4 tentativas erradas
seguidas por e-mail ou por IP) é liberado, normalmente, pela tela de
Usuários/Auditoria -- mas isso exige estar logado como admin. Se o
PRÓPRIO admin ficar bloqueado, ninguém consegue liberar pela tela. Este
script libera direto no banco, sem precisar logar.

COMO USAR (local, com SQLite):
    cd SGMF_Pro_DAC
    python desbloquear_login.py

COMO USAR (produção, Render):
    1. Abra a aba "Shell" do serviço no painel do Render
       (ela já roda com o DATABASE_URL de produção configurado)
    2. Rode:  python desbloquear_login.py
"""
import os
import sys

sys.path.insert(0, os.getcwd())

print("=" * 62)
print("DESBLOQUEAR LOGIN - SGMF Pro")
print("=" * 62)

try:
    from app import app
    from extensions import db
    from models import BloqueioAcesso
    from services.tempo import agora
except Exception as e:
    print(f"\nNão consegui importar o projeto: {e}")
    print("Rode este script de dentro da pasta do SGMF_Pro_DAC.")
    sys.exit(1)

with app.app_context():
    ativos = (BloqueioAcesso.query.filter_by(liberado=False)
              .order_by(BloqueioAcesso.criado_em.desc()).all())

    if not ativos:
        print("\nNenhum bloqueio ativo no momento. Não há nada para liberar.")
        sys.exit(0)

    print(f"\nBloqueios ativos encontrados: {len(ativos)}\n")
    for i, b in enumerate(ativos, 1):
        print(f"  [{i}] {b.tipo:6} | {b.valor:30} | bloqueado em {b.criado_em}")
    print(f"  [0] liberar TODOS")

    escolha = input("\nDigite o número do bloqueio a liberar: ").strip()

    if escolha == "0":
        alvo = ativos
    else:
        try:
            alvo = [ativos[int(escolha) - 1]]
        except Exception:
            print("Opção inválida.")
            sys.exit(1)

    for b in alvo:
        b.liberado = True
        b.liberado_por = "desbloqueio manual (script)"
        b.liberado_em = agora()

    db.session.commit()
    print(f"\n{len(alvo)} bloqueio(s) liberado(s). Já pode tentar entrar de novo.")
