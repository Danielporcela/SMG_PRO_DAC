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
    """Lista completa das posições, usada também pela tela de Pneus."""
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

  const caminho = (location.pathname || '').toLowerCase();
  const ehTelaManutencao = caminho.includes('manutenc') || caminho.includes('ordem') || caminho.includes('/os');
  const ehTelaPneus = caminho.includes('pneu');
  const fetchOriginal = window.fetch.bind(window);
  let pendentes = [];
  let idsConhecidos = new Set();
  let inicializado = false;
  let catalogoPosicoes = null;

  function escapar(t) { return String(t == null ? '' : t).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }

  function estilo() {
    if (document.getElementById('sgmf-correcao-style')) return;
    const s = document.createElement('style');
    s.id = 'sgmf-correcao-style';
    s.textContent = `
      #sgmf-pneu-btn{position:fixed;right:22px;bottom:22px;z-index:2147483000;border:0;border-radius:12px;padding:12px 16px;font-weight:700;cursor:pointer;box-shadow:0 8px 30px rgba(0,0,0,.22);background:#0f766e;color:#fff;display:none}
      #sgmf-pneu-btn.tem-pendente{display:block;animation:sgmfPulse 1.4s infinite}
      @keyframes sgmfPulse{50%{transform:scale(1.035)}}
      #sgmf-modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.48);z-index:2147483001;display:flex;align-items:center;justify-content:center;padding:18px}
      #sgmf-modal{width:min(760px,96vw);max-height:88vh;overflow:auto;background:#fff;color:#111;border-radius:16px;padding:22px;box-shadow:0 20px 70px rgba(0,0,0,.35)}
      #sgmf-modal h3{margin:0 0 8px;font-size:22px} #sgmf-modal p{margin:0 0 16px;color:#555}
      .sgmf-item{border:1px solid #ddd;border-radius:12px;padding:14px;margin:10px 0}
      .sgmf-linha{display:grid;grid-template-columns:1fr 180px auto;gap:10px;align-items:end}
      @media(max-width:640px){.sgmf-linha{grid-template-columns:1fr}}
      .sgmf-campo label{display:block;font-size:12px;color:#555;margin:8px 0 4px;font-weight:600}
      .sgmf-item select,.sgmf-item input{width:100%;padding:10px;border:1px solid #bbb;border-radius:8px;font-size:14px;box-sizing:border-box}
      .sgmf-item button{padding:10px 14px;border:0;border-radius:8px;background:#0f766e;color:#fff;font-weight:700;cursor:pointer;height:42px}
      .sgmf-fechar{float:right;border:0;background:transparent;font-size:26px;cursor:pointer}
      .sgmf-ok{font-size:13px;color:#166534;margin-top:8px}.sgmf-erro{font-size:13px;color:#b91c1c;margin-top:8px}
      .sgmf-previa{font-size:13px;color:#0f766e;margin-top:8px;font-weight:600;min-height:18px}
    `;
    document.head.appendChild(s);
  }

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
    if (!ehTelaManutencao) return null;
    let b = document.getElementById('sgmf-pneu-btn');
    if (!b) {
      b = document.createElement('button');
      b.id = 'sgmf-pneu-btn';
      b.type = 'button';
      b.addEventListener('click', abrirModal);
      document.body.appendChild(b);
    }
    return b;
  }

  function atualizarBotao() {
    const b = botao(); if (!b) return;
    if (pendentes.length) {
      b.classList.add('tem-pendente');
      b.textContent = `Definir posição do pneu (${pendentes.length})`;
    } else {
      b.classList.remove('tem-pendente');
      b.style.display = 'none';
    }
  }

  function abrirModal() {
    document.getElementById('sgmf-modal-bg')?.remove();
    const bg = document.createElement('div'); bg.id = 'sgmf-modal-bg';
    const modal = document.createElement('div'); modal.id = 'sgmf-modal';
    modal.innerHTML = `<button class="sgmf-fechar" type="button">×</button><h3>Posição do pneu na OS</h3><p>Escolha o eixo e a posição em que o pneu foi instalado e informe o número de fogo. O pneu que estava nessa posição fica preservado no histórico como descartado.</p>`;
    modal.querySelector('.sgmf-fechar').onclick = () => bg.remove();
    bg.onclick = e => { if (e.target === bg) bg.remove(); };

    if (!pendentes.length) {
      const vazio = document.createElement('div'); vazio.textContent = 'Não existem pneus sem posição neste momento.'; modal.appendChild(vazio);
    }

    pendentes.forEach(reg => {
      const box = document.createElement('div'); box.className = 'sgmf-item';
      const titulo = document.createElement('strong');
      titulo.textContent = `${reg.ordem_numero || 'OS'} · ${reg.veiculo || 'Veículo'} · ${reg.descricao || 'Pneu'}`;
      box.appendChild(titulo);

      const linha = document.createElement('div'); linha.className = 'sgmf-linha';

      const campoPos = document.createElement('div'); campoPos.className = 'sgmf-campo';
      const sel = document.createElement('select');
      sel.innerHTML = '<option value="">Selecione a posição</option>' + opcoesAgrupadas(reg.posicoes);
      campoPos.innerHTML = '<label>Posição no veículo</label>';
      campoPos.appendChild(sel);

      const campoFogo = document.createElement('div'); campoFogo.className = 'sgmf-campo';
      const fogo = document.createElement('input');
      fogo.type = 'text'; fogo.placeholder = 'ex.: 3456'; fogo.maxLength = 30;
      campoFogo.innerHTML = '<label>Nº de fogo do pneu</label>';
      campoFogo.appendChild(fogo);

      const aplicar = document.createElement('button'); aplicar.type = 'button'; aplicar.textContent = 'Aplicar';

      const previa = document.createElement('div'); previa.className = 'sgmf-previa';
      const msg = document.createElement('div');

      function atualizarPrevia() {
        if (!sel.value) { previa.textContent = ''; return; }
        const numero = fogo.value.trim();
        previa.textContent = 'Pneu ' + sel.value.toLowerCase() + (numero ? ' — nº ' + numero : '');
      }
      sel.addEventListener('change', () => { msg.textContent = ''; msg.className = ''; atualizarPrevia(); });
      fogo.addEventListener('input', () => { msg.textContent = ''; msg.className = ''; atualizarPrevia(); });

      aplicar.onclick = async () => {
        if (!sel.value) { msg.className='sgmf-erro'; msg.textContent='Selecione uma posição.'; return; }
        aplicar.disabled = true;
        try {
          const r = await fetchOriginal(`/api/correcao_os/pneu/${reg.item_id}/posicao`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({posicao: sel.value, numero_fogo: fogo.value.trim()})
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.erro || 'Falha ao registrar a posição.');
          const ident = d.resultado?.identificacao || 'Posição registrada.';
          msg.className='sgmf-ok';
          msg.textContent = d.resultado?.pneu_substituido
            ? `${ident} · pneu ${d.resultado.pneu_substituido} retirado e mantido no histórico.`
            : `${ident} · registrado com sucesso.`;
          await carregarPendentes(false);
          setTimeout(() => { box.remove(); if (!pendentes.length) bg.remove(); }, 900);
        } catch (e) { msg.className='sgmf-erro'; msg.textContent=e.message || String(e); }
        finally { aplicar.disabled=false; }
      };

      linha.append(campoPos, campoFogo, aplicar);
      box.append(linha, previa, msg);
      modal.appendChild(box);
    });
    bg.appendChild(modal); document.body.appendChild(bg);
  }

  async function carregarCatalogo() {
    if (catalogoPosicoes) return catalogoPosicoes;
    try {
      const r = await fetchOriginal('/api/correcao_os/posicoes', {credentials:'same-origin'});
      if (!r.ok) return null;
      const d = await r.json();
      catalogoPosicoes = d.posicoes || [];
      return catalogoPosicoes;
    } catch (_) { return null; }
  }

  // Na tela de Pneus, atualiza os campos de posição com os eixos novos.
  async function ajustarSelectsDePosicao() {
    if (!ehTelaPneus) return;
    const lista = await carregarCatalogo();
    if (!lista || !lista.length) return;
    const alvos = document.querySelectorAll('select[name="posicao"],select#posicao,select[data-campo="posicao"]');
    alvos.forEach(sel => {
      if (sel.dataset.sgmfPosicoes === '1') return;
      const atual = sel.value;
      sel.innerHTML = '<option value="">Selecione a posição</option>' + opcoesAgrupadas(lista);
      if (atual) {
        const existe = Array.from(sel.options).some(o => o.value === atual);
        if (!existe) sel.insertAdjacentHTML('beforeend', `<option value="${escapar(atual)}">${escapar(atual)}</option>`);
        sel.value = atual;
      }
      sel.dataset.sgmfPosicoes = '1';
    });
  }

  async function recalcular() {
    try {
      const r = await fetchOriginal('/api/correcao_os/recalcular_alertas', {method:'POST'});
      if (r.ok) document.dispatchEvent(new CustomEvent('sgmf:alertas-atualizados', {detail: await r.json()}));
    } catch (_) {}
  }

  async function carregarPendentes(abrirNovos=true) {
    if (!ehTelaManutencao) return;
    try {
      const r = await fetchOriginal('/api/correcao_os/pneus_pendentes', {credentials:'same-origin'});
      if (!r.ok) return;
      const d = await r.json(); pendentes = d.itens || [];
      const atuais = new Set(pendentes.map(x => x.item_id));
      const novos = pendentes.filter(x => !idsConhecidos.has(x.item_id));
      atualizarBotao();
      if (inicializado && abrirNovos && novos.length) abrirModal();
      idsConhecidos = atuais; inicializado = true;
    } catch (_) {}
  }

  function iniciar() { carregarPendentes(false); recalcular(); ajustarSelectsDePosicao(); }

  estilo();
  document.addEventListener('DOMContentLoaded', iniciar);
  if (document.readyState !== 'loading') iniciar();
  if (ehTelaPneus) setInterval(ajustarSelectsDePosicao, 1200);

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
