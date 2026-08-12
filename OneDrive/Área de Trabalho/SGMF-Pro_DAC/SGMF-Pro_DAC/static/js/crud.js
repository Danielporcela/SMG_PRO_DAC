/* SGMF Pro — motor das telas de cadastro.
   Cada tela declara seus campos e colunas; a listagem, o formulário,
   a validação e as mensagens são iguais em todo o sistema. */

SGMF.tela = function (config) {
  const {
    recurso, titulo, campos, colunas, tela = recurso,
    ordem = [[0, 'asc']], filtroPeriodo = false, acoesLinha = null,
    aoRenderizar = null, aoAbrirFormulario = null, aoColetar = null, podeExcluir = true
  } = config;

  const idModal = `modal_${recurso}`;
  let tabela = null;
  let registros = [];

  /* ------------------------------------------------------------- formulário */
  function campoHtml(c) {
    const col = c.col || 6;
    const obrig = c.obrigatorio ? '<span style="color:var(--alerta)">*</span>' : '';
    const nome = `campo_${c.nome}`;
    let entrada;

    if (c.tipo === 'select' || c.tipo === 'ref') {
      entrada = `<select class="form-select" id="${nome}" data-campo="${c.nome}">
                   <option value="">${c.vazio || '— selecione —'}</option></select>`;
    } else if (c.tipo === 'textarea') {
      entrada = `<textarea class="form-control" id="${nome}" data-campo="${c.nome}" rows="${c.linhas || 3}"></textarea>`;
    } else if (c.tipo === 'checkbox') {
      return `<div class="col-md-${col}"><div class="form-check mt-4 pt-1">
                <input class="form-check-input" type="checkbox" id="${nome}" data-campo="${c.nome}">
                <label class="form-check-label" for="${nome}">${c.rotulo}</label></div></div>`;
    } else if (c.tipo === 'personalizado') {
      /* Campo cujo HTML e coleta são totalmente controlados pela própria tela
         (ex.: a grade de permissões de Usuários). O framework só reserva o
         espaço; quem preenche e lê o valor é o `aoAbrirFormulario`/`aoColetar`
         que a tela registrou. */
      return `<div class="col-md-${col}">
                ${c.rotulo ? `<label class="form-label">${c.rotulo}</label>` : ''}
                <div id="${nome}"></div>
              </div>`;
    } else {
      const passo = c.tipo === 'number' ? `step="${c.passo || 'any'}"` : '';
      entrada = `<input type="${c.tipo || 'text'}" class="form-control" id="${nome}"
                   data-campo="${c.nome}" ${passo} ${c.maiuscula ? 'style="text-transform:uppercase"' : ''}
                   placeholder="${c.exemplo || ''}">`;
    }
    return `<div class="col-md-${col}">
              <label class="form-label" for="${nome}">${c.rotulo} ${obrig}</label>
              ${entrada}
              ${c.ajuda ? `<div class="form-text" style="font-size:11.5px">${c.ajuda}</div>` : ''}
            </div>`;
  }

  function montarModal() {
    const html = `
    <div class="modal fade" id="${idModal}" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content" style="border-radius:6px">
          <div class="modal-header" style="background:var(--petroleo);color:#fff">
            <h5 class="modal-title display" id="${idModal}_titulo">Novo ${titulo}</h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Fechar"></button>
          </div>
          <div class="modal-body">
            <input type="hidden" id="${idModal}_id">
            <div class="row g-3" id="${idModal}_campos">${campos.map(campoHtml).join('')}</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-contorno" data-bs-dismiss="modal">Cancelar</button>
            <button class="btn btn-primario" id="${idModal}_salvar">Salvar ${titulo}</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    document.getElementById(`${idModal}_salvar`).addEventListener('click', salvar);
  }

  async function preencherSelects() {
    for (const c of campos.filter(x => x.tipo === 'select' || x.tipo === 'ref')) {
      const el = document.getElementById(`campo_${c.nome}`);
      const lista = c.tipo === 'ref'
        ? await SGMF.opcoes(c.recurso, c.rotuloOpcao || 'identificacao')
        : c.opcoes.map(o => typeof o === 'string' ? { valor: o, texto: o } : o);
      el.innerHTML = `<option value="">${SGMF.esc(c.vazio || '— selecione —')}</option>` +
        lista.map(o => `<option value="${SGMF.esc(o.valor)}">${SGMF.esc(o.texto)}</option>`).join('');
    }
  }

  function abrir(registro = null) {
    document.getElementById(`${idModal}_id`).value = registro ? registro.id : '';
    document.getElementById(`${idModal}_titulo`).textContent =
      registro ? `Editar ${titulo}` : `Novo ${titulo}`;

    campos.forEach(c => {
      const el = document.getElementById(`campo_${c.nome}`);
      if (!el) return;
      if (c.tipo === 'personalizado') return;  // preenchido pelo aoAbrirFormulario da própria tela
      let valor = registro ? registro[c.nome] : (typeof c.padrao === 'function' ? c.padrao() : c.padrao);
      if (c.tipo === 'checkbox') el.checked = registro ? !!valor : (valor !== false);
      else el.value = (valor === null || valor === undefined) ? '' : valor;
      el.disabled = !!(c.somenteNovo && registro);
    });
    if (aoAbrirFormulario) aoAbrirFormulario(registro);
    bootstrap.Modal.getOrCreateInstance(document.getElementById(idModal)).show();
  }

  function coletar() {
    const dados = {};
    campos.forEach(c => {
      const el = document.getElementById(`campo_${c.nome}`);
      if (!el || c.tipo === 'personalizado') return;
      if (c.tipo === 'checkbox') dados[c.nome] = el.checked;
      else if (c.tipo === 'number' || c.tipo === 'ref') dados[c.nome] = el.value === '' ? null : Number(el.value);
      else dados[c.nome] = el.value.trim() === '' ? null : (c.maiuscula ? el.value.toUpperCase().trim() : el.value.trim());
    });
    if (aoColetar) aoColetar(dados);
    return dados;
  }

  async function salvar() {
    const id = document.getElementById(`${idModal}_id`).value;
    const dados = coletar();
    const faltando = campos.filter(c => c.obrigatorio && !dados[c.nome]).map(c => c.rotulo);
    if (faltando.length) {
      return SGMF.aviso(`Preencha: ${faltando.join(', ')}.`);
    }
    const botao = document.getElementById(`${idModal}_salvar`);
    botao.disabled = true;
    try {
      if (id) await SGMF.put(`/api/${recurso}/${id}`, dados);
      else await SGMF.post(`/api/${recurso}`, dados);
      bootstrap.Modal.getInstance(document.getElementById(idModal)).hide();
      SGMF.sucesso(id ? `${titulo} atualizado` : `${titulo} cadastrado`);
      SGMF.limparCache(recurso);
      await carregar();
    } catch (e) {
      SGMF.falha(e.message);
    } finally {
      botao.disabled = false;
    }
  }

  async function excluir(id, descricao) {
    const ok = await SGMF.confirmar('Excluir registro?',
      `${descricao} será removido definitivamente.`, 'Excluir');
    if (!ok) return;
    try {
      await SGMF.del(`/api/${recurso}/${id}`);
      SGMF.sucesso('Registro excluído');
      SGMF.limparCache(recurso);
      await carregar();
    } catch (e) { SGMF.falha(e.message); }
  }

  /* ---------------------------------------------------------------- tabela */
  function montarTabela() {
    const cabecalho = colunas.map(c => `<th>${c.rotulo}</th>`).join('') +
      (bloqueado() ? '<th></th>' : '<th style="width:96px">Ações</th>');
    document.getElementById('areaTabela').innerHTML =
      `<table id="tabelaDados" class="table table-hover align-middle" style="width:100%">
         <thead><tr>${cabecalho}</tr></thead><tbody></tbody></table>`;
  }

  const bloqueado = () => SGMF.somenteLeitura(tela);

  function linhaHtml(item) {
    const seguro = SGMF.escObjeto(item);   // nada digitado pelo usuário vira HTML
    const celulas = colunas.map(c => {
      const bruto = seguro[c.campo];
      const conteudo = c.render ? c.render(bruto, seguro)
        : (bruto === null || bruto === undefined || bruto === '' ? '—' : bruto);
      return `<td class="${c.classe || ''}">${conteudo}</td>`;
    });
    if (bloqueado()) {
      celulas.push('<td class="text-muted" style="font-size:11.5px">somente leitura</td>');
      return `<tr>${celulas.join('')}</tr>`;
    }
    const extras = acoesLinha ? acoesLinha(seguro) : '';
    celulas.push(`<td class="text-nowrap">
      ${extras}
      <button class="btn btn-contorno btn-icone" data-editar="${item.id}" title="Editar"><i class="fa-solid fa-pen"></i></button>
      ${podeExcluir ? `<button class="btn btn-contorno btn-icone" data-excluir="${item.id}" title="Excluir"><i class="fa-solid fa-trash"></i></button>` : ''}
    </td>`);
    return `<tr>${celulas.join('')}</tr>`;
  }

  async function carregar() {
    let url = `/api/${recurso}`;
    if (filtroPeriodo) {
      const i = document.getElementById('filtroInicio'), f = document.getElementById('filtroFim');
      if (i && f) url += `?inicio=${i.value}&fim=${f.value}`;
    }
    registros = await SGMF.get(url);
    if (tabela) { tabela.destroy(); }
    montarTabela();
    document.querySelector('#tabelaDados tbody').innerHTML =
      registros.map(linhaHtml).join('');

    tabela = new DataTable('#tabelaDados', {
      order: ordem, pageLength: 25, lengthMenu: [10, 25, 50, 100],
      language: {
        search: 'Buscar:', lengthMenu: 'Mostrar _MENU_ registros',
        info: '_START_ a _END_ de _TOTAL_ registros', infoEmpty: 'Nenhum registro',
        infoFiltered: '(filtrado de _MAX_)', zeroRecords: 'Nada encontrado com esse filtro',
        emptyTable: 'Nenhum registro cadastrado ainda.',
        paginate: { first: 'Primeira', last: 'Última', next: 'Próxima', previous: 'Anterior' }
      }
    });

    document.querySelectorAll('[data-editar]').forEach(b => b.onclick = () =>
      abrir(registros.find(r => r.id == b.dataset.editar)));
    document.querySelectorAll('[data-excluir]').forEach(b => b.onclick = () => {
      const item = registros.find(r => r.id == b.dataset.excluir);
      excluir(item.id, item.identificacao || item.numero || item.descricao || 'O registro');
    });

    if (aoRenderizar) aoRenderizar(registros);
  }

  /* ------------------------------------------------------------- inicializa */
  montarModal();
  const botaoNovo = document.getElementById('botaoNovo');
  if (botaoNovo && bloqueado()) botaoNovo.remove();
  else if (botaoNovo) botaoNovo.onclick = () => abrir();
  ['filtroInicio', 'filtroFim'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', carregar);
  });

  preencherSelects().then(carregar).catch(e => SGMF.falha(e.message));

  return { carregar, abrir, dados: () => registros };
};
