(() => {
  // Ciclo do pneu: Retirados da frota -> Recapagem (NF de retorno) -> Estoque ou Descarte.
  const el = id => document.getElementById(id);
  const esc = v => SGMF.esc(v == null ? '' : v);
  const somenteLeitura = () => SGMF.somenteLeitura('pneus');

  let retirados = [];
  let descartados = [];
  let fornecedores = null;

  const modal = id => bootstrap.Modal.getOrCreateInstance(el(id));
  const hojeISO = () => new Date().toISOString().slice(0, 10);

  async function carregarFornecedores(select) {
    if (fornecedores === null) {
      try { fornecedores = await SGMF.get('/api/fornecedores'); }
      catch (e) { fornecedores = []; }
    }
    select.innerHTML = '<option value="">— não informar —</option>' +
      fornecedores.map(f => `<option value="${esc(f.id)}">${esc(f.nome)}</option>`).join('');
  }

  // ------------------------------------------------------------ retirados
  function renderRetirados() {
    const termo = el('retBusca').value.trim().toLowerCase();
    const lista = retirados.filter(l => !termo || [l.numero_fogo, l.marca, l.medida,
      l.veiculo_rotulo, l.os_numero, l.vida].join(' ').toLowerCase().includes(termo));
    const corpo = el('retCorpo');
    if (!lista.length) {
      corpo.innerHTML = '<tr><td colspan="11" class="cp-vazio">' +
        (retirados.length ? 'Nenhum pneu para esta busca.' :
          'Nenhum pneu retirado. Os pneus que saem da frota numa troca de pneu da OS aparecem aqui.') +
        '</td></tr>';
    } else {
      corpo.innerHTML = lista.map(l => {
        const naRecap = l.status === 'Em recapagem';
        const marcar = (!somenteLeitura() && !naRecap)
          ? `<input type="checkbox" class="form-check-input" data-sel="${esc(l.id)}">` : '';
        const descartar = somenteLeitura() ? '' :
          `<button class="btn btn-sm btn-contorno" data-descartar="${esc(l.id)}" title="Descartar sem recapar">` +
          '<i class="fa-solid fa-trash-can"></i></button>';
        const situacao = naRecap
          ? SGMF.etiqueta('Em recapagem' + (l.envio_fornecedor ? ' · ' + l.envio_fornecedor : ''), 'ambar')
          : SGMF.etiqueta('Retirado', 'ambar');
        return '<tr>' +
          `<td>${marcar}</td>` +
          `<td><strong>${esc(l.numero_fogo)}</strong></td>` +
          `<td>${esc(l.marca || '—')}</td>` +
          `<td>${esc(l.medida || '—')}</td>` +
          `<td>${esc(l.vida || 'Novo')}</td>` +
          `<td>${esc(l.veiculo_rotulo || '—')}</td>` +
          `<td>${esc(l.posicao || '—')}</td>` +
          `<td>${esc(l.os_numero || '—')}</td>` +
          `<td>${esc(SGMF.data(l.retirada_data))}</td>` +
          `<td>${situacao}</td>` +
          `<td>${descartar}</td>` +
          '</tr>';
      }).join('');
    }
    el('retRodape').textContent = `${lista.length} de ${retirados.length} pneu(s) na lista de retirados.`;
  }

  async function carregarRetirados() {
    try { retirados = await SGMF.get('/api/pneus-retirados'); renderRetirados(); }
    catch (e) { SGMF.falha(e.message); }
  }

  function selecionados() {
    return [...document.querySelectorAll('#retCorpo [data-sel]:checked')].map(c => Number(c.dataset.sel));
  }

  async function abrirEnvio() {
    const ids = selecionados();
    if (!ids.length) return SGMF.aviso('Marque ao menos um pneu retirado para enviar à recapagem.');
    el('erResumo').textContent = `${ids.length} pneu(s) selecionado(s).`;
    el('erData').value = hojeISO();
    await carregarFornecedores(el('erFornecedor'));
    modal('modalEnviarRecap').show();
  }

  async function confirmarEnvio() {
    const btn = el('erConfirmar');
    btn.disabled = true;
    try {
      await SGMF.post('/api/pneus-retirados/enviar-recapagem', {
        pneu_ids: selecionados(), data: el('erData').value,
        fornecedor_id: el('erFornecedor').value || null
      });
      modal('modalEnviarRecap').hide();
      SGMF.sucesso('Pneus enviados para recapagem');
      await carregarRetirados();
    } catch (e) { SGMF.falha(e.message); }
    finally { btn.disabled = false; }
  }

  async function descartar(id) {
    const l = retirados.find(x => x.id === id);
    if (!l) return;
    const r = await Swal.fire({
      icon: 'warning', title: `Descartar o pneu ${l.numero_fogo}?`,
      input: 'text', inputLabel: 'Motivo (opcional)', showCancelButton: true,
      confirmButtonText: 'Descartar', cancelButtonText: 'Cancelar'
    });
    if (!r.isConfirmed) return;
    try {
      await SGMF.post(`/api/pneus-retirados/${id}/descartar`, { motivo: r.value || '' });
      SGMF.sucesso('Pneu enviado para a lista de descarte');
      await carregarRetirados();
    } catch (e) { SGMF.falha(e.message); }
  }

  // ------------------------------------------------------------ NF de retorno
  function linhaItem(fogo = '') {
    const div = document.createElement('div');
    div.className = 'row g-2 align-items-end mb-2 nr-item';
    const opcoes = retirados.map(p =>
      `<option value="${esc(p.numero_fogo)}"${p.numero_fogo === fogo ? ' selected' : ''}>` +
      `${esc(p.numero_fogo)} · ${esc(p.vida || 'Novo')}${p.status === 'Em recapagem' ? ' (na recapadora)' : ''}</option>`).join('');
    div.innerHTML =
      '<div class="col-md-4"><label class="form-label small mb-0">Nº de fogo</label>' +
      `<select class="form-select form-select-sm nr-fogo"><option value="">— selecione —</option>${opcoes}</select></div>` +
      '<div class="col-md-3"><label class="form-label small mb-0">Resultado</label>' +
      '<select class="form-select form-select-sm nr-resultado">' +
      '<option value="Recapado">Recapado (volta ao Estoque)</option><option value="Descartado">Descartado</option></select></div>' +
      '<div class="col-md-2"><label class="form-label small mb-0">Valor (R$)</label>' +
      '<input class="form-control form-control-sm nr-valor" inputmode="decimal"></div>' +
      '<div class="col-md-2"><label class="form-label small mb-0">Motivo</label>' +
      '<input class="form-control form-control-sm nr-motivo" maxlength="300" placeholder="se descartado"></div>' +
      '<div class="col-md-1"><button type="button" class="btn btn-sm btn-contorno nr-remover" title="Remover"><i class="fa-solid fa-xmark"></i></button></div>';
    div.querySelector('.nr-remover').onclick = () => div.remove();
    return div;
  }

  async function abrirNota() {
    await carregarRetirados();
    ['nrNumero', 'nrSerie', 'nrObs'].forEach(i => { el(i).value = ''; });
    el('nrEmissao').value = hojeISO();
    await carregarFornecedores(el('nrFornecedor'));
    el('nrItens').innerHTML = '';
    // Pré-carrega os pneus marcados na lista (ou uma linha em branco).
    const marcados = selecionados().map(id => (retirados.find(r => r.id === id) || {}).numero_fogo).filter(Boolean);
    (marcados.length ? marcados : ['']).forEach(f => el('nrItens').appendChild(linhaItem(f)));
    modal('modalNotaRecap').show();
  }

  async function salvarNota() {
    const itens = [...document.querySelectorAll('#nrItens .nr-item')].map(d => ({
      numero_fogo: d.querySelector('.nr-fogo').value,
      resultado: d.querySelector('.nr-resultado').value,
      valor: d.querySelector('.nr-valor').value,
      motivo: d.querySelector('.nr-motivo').value
    })).filter(i => i.numero_fogo);
    const btn = el('nrSalvar');
    btn.disabled = true;
    try {
      await SGMF.post('/api/recapagem/notas', {
        numero: el('nrNumero').value, serie: el('nrSerie').value,
        data_emissao: el('nrEmissao').value, fornecedor_id: el('nrFornecedor').value || null,
        observacao: el('nrObs').value, itens
      });
      modal('modalNotaRecap').hide();
      SGMF.sucesso('Nota lançada: pneus recapados voltaram ao Estoque');
      await Promise.all([carregarRetirados(), carregarNotas(), carregarDescartados()]);
    } catch (e) { SGMF.falha(e.message); }
    finally { btn.disabled = false; }
  }

  async function carregarNotas() {
    const corpo = el('notasRecapCorpo');
    try {
      const notas = await SGMF.get('/api/recapagem/notas');
      if (!notas.length) {
        corpo.innerHTML = '<tr><td colspan="6" class="cp-vazio">Nenhuma nota de recapagem lançada.</td></tr>';
        return;
      }
      corpo.innerHTML = notas.map(n => {
        const fogos = (n.itens || []).map(i => i.evento === 'Descarte'
          ? `${esc(i.numero_fogo)} <span class="text-muted">(descartado)</span>`
          : `${esc(i.numero_fogo)} <span class="text-muted">(${esc(i.vida)})</span>`).join(', ');
        return '<tr>' +
          `<td><strong>${esc(n.identificacao)}</strong></td>` +
          `<td>${esc(n.fornecedor_nome || '—')}</td>` +
          `<td>${esc(SGMF.data(n.data_emissao))}</td>` +
          `<td>${fogos}</td>` +
          `<td class="cp-num">${esc(SGMF.moeda(n.valor_total))}</td>` +
          `<td>${esc(n.usuario || '—')}</td></tr>`;
      }).join('');
    } catch (e) { SGMF.falha(e.message); }
  }

  // ------------------------------------------------------------ descartados
  function renderDescartados() {
    const termo = el('descBusca').value.trim().toLowerCase();
    const lista = descartados.filter(l => !termo || [l.numero_fogo, l.marca, l.medida,
      l.descarte_motivo, l.descarte_nota].join(' ').toLowerCase().includes(termo));
    const corpo = el('descCorpo');
    if (!lista.length) {
      corpo.innerHTML = '<tr><td colspan="9" class="cp-vazio">Nenhum pneu descartado.</td></tr>';
    } else {
      corpo.innerHTML = lista.map(l => '<tr>' +
        `<td><strong>${esc(l.numero_fogo)}</strong></td>` +
        `<td>${esc(l.marca || '—')}</td>` +
        `<td>${esc(l.medida || '—')}</td>` +
        `<td>${esc(l.vida || 'Novo')}</td>` +
        `<td>${esc(SGMF.data(l.descarte_data))}</td>` +
        `<td>${esc(l.descarte_origem || '—')}</td>` +
        `<td>${esc(l.descarte_nota || '—')}</td>` +
        `<td>${esc(l.veiculo_rotulo || '—')}</td>` +
        `<td>${esc(l.descarte_motivo || '—')}</td></tr>`).join('');
    }
    el('descRodape').textContent = `${lista.length} de ${descartados.length} pneu(s) descartado(s).`;
  }

  async function carregarDescartados() {
    try { descartados = await SGMF.get('/api/pneus-descartados'); renderDescartados(); }
    catch (e) { SGMF.falha(e.message); }
  }

  // ------------------------------------------------------------ início
  document.addEventListener('DOMContentLoaded', () => {
    if (!el('tabRetirados')) return;
    el('tabRetirados').addEventListener('shown.bs.tab', carregarRetirados);
    el('tabNotasRecap').addEventListener('shown.bs.tab', carregarNotas);
    el('tabDescartados').addEventListener('shown.bs.tab', carregarDescartados);
    el('retBusca').addEventListener('input', renderRetirados);
    el('descBusca').addEventListener('input', renderDescartados);
    el('btnEnviarRecap').addEventListener('click', abrirEnvio);
    el('btnNotaRecap').addEventListener('click', abrirNota);
    el('erConfirmar').addEventListener('click', confirmarEnvio);
    el('nrSalvar').addEventListener('click', salvarNota);
    el('nrAddItem').addEventListener('click', () => el('nrItens').appendChild(linhaItem('')));
    el('retCorpo').addEventListener('click', e => {
      const b = e.target.closest('[data-descartar]');
      if (b) descartar(Number(b.dataset.descartar));
    });
    if (somenteLeitura()) {
      ['btnEnviarRecap', 'btnNotaRecap'].forEach(i => el(i).classList.add('d-none'));
    }
  });
})();
