"""Rotas incrementais para posição de pneus e atualização imediata dos alertas.

Atualizado: as posições de services/correcoes_os.py agora incluem o EIXO TRUCK
(2º eixo traseiro) e o número de fogo do pneu no lançamento da OS.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request, session

from extensions import db
from models import ItemOS, OrdemServico
from services.alertas import listar_alertas_ativos, sincronizar_estados
from services.correcoes_os import (
    aplicar_posicao_pneu,
    eh_item_pneu,
    listar_posicoes,
    posicoes_do_veiculo,
)

bp_correcao_os = Blueprint("correcao_os", __name__)


def _pode_editar():
    if not session.get("usuario_id"):
        return False
    if session.get("perfil") == "admin":
        return True
    permissoes = session.get("permissoes") or {}
    return permissoes.get("manutencao") == "editar"


def _nao_autorizado():
    return jsonify({"erro": "Acesso não autorizado."}), 403


@bp_correcao_os.get("/api/correcao_os/posicoes")
def posicoes():
    """Lista completa das posições disponíveis para um veículo."""
    if not session.get("usuario_id"):
        return _nao_autorizado()
    return jsonify({"posicoes": listar_posicoes()})


@bp_correcao_os.get("/api/correcao_os/pneus_pendentes")
def pneus_pendentes():
    if not session.get("usuario_id"):
        return _nao_autorizado()

    itens = (ItemOS.query
             .join(OrdemServico, ItemOS.ordem_servico_id == OrdemServico.id)
             .filter(ItemOS.posicao_pneu.is_(None))
             .order_by(ItemOS.id.desc()).limit(100).all())

    dados = []
    for item in itens:
        if not eh_item_pneu(item):
            continue
        os_obj = item.ordem
        dados.append({
            "item_id": item.id,
            "ordem_servico_id": item.ordem_servico_id,
            "ordem_numero": os_obj.numero if os_obj else None,
            "ordem_status": os_obj.status if os_obj else None,
            "veiculo_id": os_obj.veiculo_id if os_obj else None,
            "veiculo": os_obj.veiculo.to_dict().get("identificacao") if os_obj and os_obj.veiculo else None,
            "descricao": item.descricao or (item.peca.descricao if item.peca else "Pneu"),
            "peca_id": item.peca_id,
            "posicoes": posicoes_do_veiculo(os_obj.veiculo_id if os_obj else None),
        })
    return jsonify({"itens": dados, "total": len(dados)})


@bp_correcao_os.post("/api/correcao_os/pneu/<int:item_id>/posicao")
def definir_posicao(item_id):
    if not _pode_editar():
        return _nao_autorizado()

    item = db.session.get(ItemOS, item_id)
    if item is None:
        return jsonify({"erro": "Item da ordem de serviço não encontrado."}), 404

    dados = request.get_json(silent=True) or request.form
    posicao = str(dados.get("posicao") or "").strip()
    numero_fogo = str(dados.get("numero_fogo") or "").strip()
    try:
        resultado = aplicar_posicao_pneu(item, posicao, numero_fogo)
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:  # número de fogo repetido, por exemplo
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível registrar o pneu: {exc}"}), 400

    # A troca do pneu pode sanar imediatamente um alerta de sulco mínimo.
    estados = sincronizar_estados()
    return jsonify({
        "ok": True,
        "resultado": resultado,
        "sanados": estados.get("sanados", []),
        "alertas_ativos": len(listar_alertas_ativos()),
    })


@bp_correcao_os.post("/api/correcao_os/recalcular_alertas")
def recalcular_alertas():
    if not session.get("usuario_id"):
        return _nao_autorizado()
    estados = sincronizar_estados()
    return jsonify({
        "ok": True,
        "ativos": len(listar_alertas_ativos()),
        "abertos": estados.get("abertos", []),
        "sanados": estados.get("sanados", []),
    })


PATCH_JS = r'''
(() => {
  if (window.__sgmfCorrecaoOsCarregada) return;
  window.__sgmfCorrecaoOsCarregada = true;

  /* Este script só é incluído por templates/manutencao.html — antes ele
     era injetado em TODAS as páginas do sistema (ver app.py), o que
     causava dois problemas: 1) na tela de Pneus, ele reescrevia o select
     de posição do formulário a cada 1,2s, atrapalhando o preenchimento
     (inclusive o campo "Número de fogo"); 2) o modal aqui embaixo era um
     <div> avulso, fora do controle de foco/aria do Bootstrap, então
     disputava foco com o modal oficial da tela (modalPecas) e gerava o
     aviso "Blocked aria-hidden ... descendant retained focus" no
     console. Agora o modal usa bootstrap.Modal normalmente, como
     qualquer outro modal do sistema. */

  const idModal = 'sgmfModalPosicaoPneu';
  const fetchOriginal = window.fetch.bind(window);
  let pendentes = [];
  let idsConhecidos = new Set();
  let inicializado = false;

  function escapar(t) { return String(t == null ? '' : t).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }

  function opcoesAgrupadas(posicoes) {
    const eixos = [];
    (posicoes || []).forEach(p => {
      const nome = p.eixo || 'Posições';
      let grupo = eixos.find(g => g.nome === nome);
      if (!grupo) { grupo = {nome, itens: []}; eixos.push(grupo); }
      grupo.itens.push(p);
    });
    return eixos.map(g => {
      const opts = g.itens.map(p => {
        const atual = p.ocupada ? ` · atual ${p.pneu_atual || ''}${p.sulco_mm != null ? ` · ${p.sulco_mm} mm` : ''}` : '';
        return `<option value="${escapar(p.valor)}">${escapar(p.valor)}${escapar(atual)}</option>`;
      }).join('');
      return `<optgroup label="${escapar(g.nome)}">${opts}</optgroup>`;
    }).join('');
  }

  function botao() {
    let b = document.getElementById('sgmf-pneu-btn');
    if (!b) {
      b = document.createElement('button');
      b.id = 'sgmf-pneu-btn';
      b.type = 'button';
      b.className = 'btn btn-primario';
      b.style.cssText = 'position:fixed;right:22px;bottom:22px;z-index:1030;border-radius:12px;padding:12px 16px;font-weight:700;box-shadow:0 8px 30px rgba(0,0,0,.22);display:none';
      b.addEventListener('click', () => { montarConteudoModal(); bootstrap.Modal.getOrCreateInstance(document.getElementById(idModal)).show(); });
      document.body.appendChild(b);
    }
    return b;
  }

  function atualizarBotao() {
    const b = botao();
    if (pendentes.length) {
      b.style.display = 'block';
      b.textContent = `Definir posição do pneu (${pendentes.length})`;
    } else {
      b.style.display = 'none';
    }
  }

  function montarModalBase() {
    if (document.getElementById(idModal)) return;
    const html = `
    <div class="modal fade" id="${idModal}" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content" style="border-radius:6px">
          <div class="modal-header" style="background:var(--petroleo);color:#fff">
            <h5 class="modal-title display" style="font-size:18px">Posição do pneu na OS</h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Fechar"></button>
          </div>
          <div class="modal-body">
            <p style="font-size:13px;color:var(--texto-suave)" class="mb-3">
              Escolha o eixo e a posição em que o pneu foi instalado e informe o número de fogo.
              O pneu que estava nessa posição fica preservado no histórico como descartado.
            </p>
            <div id="${idModal}_lista"></div>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  function montarConteudoModal() {
    montarModalBase();
    const lista = document.getElementById(`${idModal}_lista`);
    lista.innerHTML = '';

    if (!pendentes.length) {
      lista.innerHTML = '<div class="text-muted">Não existem pneus sem posição neste momento.</div>';
      return;
    }

    pendentes.forEach(reg => {
      const box = document.createElement('div');
      box.className = 'border rounded p-3 mb-3';

      const titulo = document.createElement('strong');
      titulo.textContent = `${reg.ordem_numero || 'OS'} · ${reg.veiculo || 'Veículo'} · ${reg.descricao || 'Pneu'}`;
      box.appendChild(titulo);

      const linha = document.createElement('div');
      linha.className = 'row g-2 mt-1 align-items-end';

      const colPos = document.createElement('div'); colPos.className = 'col-md-6';
      colPos.innerHTML = '<label class="form-label" style="font-size:12px">Posição no veículo</label>';
      const sel = document.createElement('select');
      sel.className = 'form-select';
      sel.innerHTML = '<option value="">Selecione a posição</option>' + opcoesAgrupadas(reg.posicoes);
      colPos.appendChild(sel);

      const colFogo = document.createElement('div'); colFogo.className = 'col-md-4';
      colFogo.innerHTML = '<label class="form-label" style="font-size:12px">Nº de fogo do pneu</label>';
      const fogo = document.createElement('input');
      fogo.type = 'text'; fogo.className = 'form-control'; fogo.placeholder = 'ex.: 3456'; fogo.maxLength = 30;
      colFogo.appendChild(fogo);

      const colBotao = document.createElement('div'); colBotao.className = 'col-md-2';
      const aplicar = document.createElement('button');
      aplicar.type = 'button'; aplicar.className = 'btn btn-primario w-100'; aplicar.textContent = 'Aplicar';
      colBotao.appendChild(aplicar);

      const previa = document.createElement('div');
      previa.className = 'mt-2'; previa.style.cssText = 'font-size:13px;color:var(--petroleo-claro);font-weight:600;min-height:18px';
      const msg = document.createElement('div');
      msg.style.fontSize = '13px';

      function atualizarPrevia() {
        if (!sel.value) { previa.textContent = ''; return; }
        const numero = fogo.value.trim();
        previa.textContent = 'Pneu ' + sel.value.toLowerCase() + (numero ? ' — nº ' + numero : '');
      }
      sel.addEventListener('change', () => { msg.textContent = ''; atualizarPrevia(); });
      fogo.addEventListener('input', () => { msg.textContent = ''; atualizarPrevia(); });

      aplicar.onclick = async () => {
        if (!sel.value) { msg.style.color = '#b91c1c'; msg.textContent = 'Selecione uma posição.'; return; }
        aplicar.disabled = true;
        try {
          const r = await fetchOriginal(`/api/correcao_os/pneu/${reg.item_id}/posicao`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ posicao: sel.value, numero_fogo: fogo.value.trim() })
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.erro || 'Falha ao registrar a posição.');
          const ident = d.resultado?.identificacao || 'Posição registrada.';
          msg.style.color = '#166534';
          msg.textContent = d.resultado?.pneu_substituido
            ? `${ident} · pneu ${d.resultado.pneu_substituido} retirado e mantido no histórico.`
            : `${ident} · registrado com sucesso.`;
          await carregarPendentes(false);
          setTimeout(() => {
            box.remove();
            if (!pendentes.length) bootstrap.Modal.getInstance(document.getElementById(idModal))?.hide();
          }, 900);
        } catch (e) { msg.style.color = '#b91c1c'; msg.textContent = e.message || String(e); }
        finally { aplicar.disabled = false; }
      };

      linha.append(colPos, colFogo, colBotao);
      box.append(linha, previa, msg);
      lista.appendChild(box);
    });
  }

  async function recalcular() {
    try {
      const r = await fetchOriginal('/api/correcao_os/recalcular_alertas', { method: 'POST' });
      if (r.ok) document.dispatchEvent(new CustomEvent('sgmf:alertas-atualizados', { detail: await r.json() }));
    } catch (_) {}
  }

  async function carregarPendentes(abrirNovos = true) {
    try {
      const r = await fetchOriginal('/api/correcao_os/pneus_pendentes', { credentials: 'same-origin' });
      if (!r.ok) return;
      const d = await r.json(); pendentes = d.itens || [];
      const atuais = new Set(pendentes.map(x => x.item_id));
      const novos = pendentes.filter(x => !idsConhecidos.has(x.item_id));
      atualizarBotao();
      if (inicializado && abrirNovos && novos.length) {
        montarConteudoModal();
        bootstrap.Modal.getOrCreateInstance(document.getElementById(idModal)).show();
      }
      idsConhecidos = atuais; inicializado = true;
    } catch (_) {}
  }

  function iniciar() { montarModalBase(); carregarPendentes(false); recalcular(); }

  document.addEventListener('DOMContentLoaded', iniciar);
  if (document.readyState !== 'loading') iniciar();

  window.fetch = async (...args) => {
    const resp = await fetchOriginal(...args);
    try {
      const init = args[1] || {}; const metodo = String(init.method || 'GET').toUpperCase();
      const url = String(typeof args[0] === 'string' ? args[0] : args[0]?.url || '');
      if (resp.ok && metodo !== 'GET' && !url.includes('/api/correcao_os/')) {
        setTimeout(() => { recalcular(); carregarPendentes(true); }, 350);
      }
    } catch (_) {}
    return resp;
  };

  const openOriginal = XMLHttpRequest.prototype.open;
  const sendOriginal = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) { this.__sgmfMethod = String(method || 'GET').toUpperCase(); this.__sgmfUrl = String(url || ''); return openOriginal.call(this, method, url, ...rest); };
  XMLHttpRequest.prototype.send = function(...args) { this.addEventListener('load', () => { if (this.status >= 200 && this.status < 400 && this.__sgmfMethod !== 'GET' && !this.__sgmfUrl.includes('/api/correcao_os/')) setTimeout(() => { recalcular(); carregarPendentes(true); }, 350); }); return sendOriginal.apply(this, args); };
})();
'''


@bp_correcao_os.get("/correcao_os/patch.js")
def patch_js():
    return Response(PATCH_JS, mimetype="application/javascript")
