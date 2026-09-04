/* SGMF Pro — motor das telas de cadastro.
   Cada tela declara seus campos e colunas; a listagem, o formulário,
   a validação e as mensagens são iguais em todo o sistema. */

SGMF.tela = function (config) {
  const {
    recurso, titulo, campos, colunas, tela = recurso,
    ordem = [[0, 'asc']], filtroPeriodo = false, acoesLinha = null,
    aoRenderizar = null, aoAbrirFormulario = null, aoColetar = null, podeExcluir = true,
    rotuloSalvar = null
  } = config;

  const idModal = `modal_${recurso}`;
  let tabela = null;
  let registros = [];
  let sujo = false;             // true assim que o usuário mexe em algum campo do formulário
  let fechamentoLiberado = false;  // true quando o fechamento já foi confirmado (ou é um salvamento)

  /* ------------------------------------------------------------- formulário */
  function campoHtml(c) {
    const col = c.col || 6;
    const obrig = c.obrigatorio ? '<span style="color:var(--alerta)">*</span>' : '';
    const nome = `campo_${c.nome}`;
    let entrada;

    if (c.tipo === 'select' || c.tipo === 'ref') {
      entrada = `<select class="form-select" id="${nome}" data-campo="${c.nome}">
                   <option value="">${c.vazio || '— selecione —'}</option></select>`;
    } else if (c.tipo === 'moeda') {
      /* Texto comum, não <input type="number">: number faz o navegador ler
         "." como separador decimal, então digitar "20.000" (separador de
         milhar) virava 20. Aqui o usuário só digita dígitos e o campo se
         formata sozinho (ver SGMF.mascaraMoeda). */
      entrada = `<input type="text" class="form-control text-end" id="${nome}"
                   data-campo="${c.nome}" placeholder="${c.exemplo || '0,00'}">`;
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
            <button class="btn btn-primario" id="${idModal}_salvar">${rotuloSalvar || `Salvar ${titulo}`}</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    document.getElementById(`${idModal}_salvar`).addEventListener('click', salvar);
    if (bloqueado()) document.getElementById(`${idModal}_salvar`).classList.add('d-none');
    campos.filter(c => c.tipo === 'moeda').forEach(c => {
      SGMF.mascaraMoeda(document.getElementById(`campo_${c.nome}`));
    });

    const elModal = document.getElementById(idModal);
    document.getElementById(`${idModal}_campos`)
      .addEventListener('input', () => { sujo = true; });
    document.getElementById(`${idModal}_campos`)
      .addEventListener('change', () => { sujo = true; });

    // Fechou (X, "Cancelar", clique fora ou Esc) com algo preenchido e não
    // salvo? Segura o fechamento e confirma antes de descartar.
    elModal.addEventListener('hide.bs.modal', (ev) => {
      if (!sujo || fechamentoLiberado) return;
      ev.preventDefault();
      SGMF.confirmar('Sair sem salvar?',
        'As informações preenchidas neste formulário serão perdidas.', 'Sair sem salvar')
        .then((ok) => {
          if (!ok) return;
          fechamentoLiberado = true;
          bootstrap.Modal.getInstance(elModal).hide();
        });
    });
    elModal.addEventListener('hidden.bs.modal', () => {
      sujo = false;
      fechamentoLiberado = false;
    });
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
    sujo = false;
    fechamentoLiberado = false;
    document.getElementById(`${idModal}_id`).value = registro ? registro.id : '';
    document.getElementById(`${idModal}_titulo`).textContent =
      bloqueado() ? `Visualizar ${titulo}` : (registro ? `Editar ${titulo}` : `Novo ${titulo}`);

    campos.forEach(c => {
      const el = document.getElementById(`campo_${c.nome}`);
      if (!el) return;
      if (c.tipo === 'personalizado') return;  // preenchido pelo aoAbrirFormulario da própria tela
      let valor = registro ? registro[c.nome] : (typeof c.padrao === 'function' ? c.padrao() : c.padrao);
      if (c.tipo === 'checkbox') el.checked = registro ? !!valor : (valor !== false);
      else if (c.tipo === 'moeda') SGMF.definirValorMoeda(el, valor);
      else el.value = (valor === null || valor === undefined) ? '' : valor;
      const podeEditarCampoSetor = SGMF.perfil() === 'admin' ||
        (SGMF.cargo() || '').trim().toUpperCase() === 'CCO';
      const isCCO = (SGMF.cargo() || '').trim().toUpperCase() === 'CCO';
      el.disabled = bloqueado() || !!(c.somenteNovo && registro) ||
        !!(c.travarParaOutroSetor && !podeEditarCampoSetor) ||
        !!(c.bloquearParaCCO && isCCO);
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
      else if (c.tipo === 'moeda') dados[c.nome] = SGMF.valorMoeda(el) || null;
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
      fechamentoLiberado = true;
      bootstrap.Modal.getInstance(document.getElementById(idModal)).hide();
      SGMF.sucesso(id ? `${titulo} atualizado` : `${titulo} cadastrado`);
      SGMF.limparCache(recurso);
      /* Um registro NOVO some da lista se o período filtrado no topo da tela
         não cobrir a data de hoje (o registro fica salvo, só não aparece).
         Para não confundir o usuário, garante que o filtro inclua hoje. */
      if (!id && filtroPeriodo) {
        const i = document.getElementById('filtroInicio'), f = document.getElementById('filtroFim');
        const hoje = SGMF.hoje();
        let ajustou = false;
        if (i && i.value > hoje) { i.value = hoje; ajustou = true; }
        if (f && f.value < hoje) { f.value = hoje; ajustou = true; }
        if (ajustou) [i, f].forEach(el => el && el.dispatchEvent(new Event('change')));
      }
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
      celulas.push(`<td class="text-nowrap"><button class="btn btn-contorno btn-sm" data-visualizar="${item.id}" title="Visualizar"><i class="fa-solid fa-eye"></i> Visualizar</button></td>`);
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

    /* Editar/Excluir são ligados por delegação de evento (ver
       ligarAcoesLinha, chamada uma única vez na inicialização) em vez de
       onclick direto em cada botão. O DataTables recria as linhas do
       <tbody> a cada página, ordenação ou busca — se os cliques fossem
       ligados aqui, os botões das páginas seguintes ficariam sem ação. */

    if (aoRenderizar) aoRenderizar(registros);
  }

  /* Delegação de clique no container da tabela: funciona para qualquer
     linha existente ou futura, mesmo depois do DataTables redesenhar o
     <tbody> (paginação, ordenação, busca). */
  function ligarAcoesLinha() {
    document.getElementById('areaTabela').addEventListener('click', (e) => {
      const botaoVisualizar = e.target.closest('[data-visualizar]');
      if (botaoVisualizar) {
        abrir(registros.find(r => r.id == botaoVisualizar.dataset.visualizar));
        return;
      }
      const botaoEditar = e.target.closest('[data-editar]');
      if (botaoEditar) {
        abrir(registros.find(r => r.id == botaoEditar.dataset.editar));
        return;
      }
      const botaoExcluir = e.target.closest('[data-excluir]');
      if (botaoExcluir) {
        const item = registros.find(r => r.id == botaoExcluir.dataset.excluir);
        excluir(item.id, item.identificacao || item.numero || item.descricao || 'O registro');
      }
    });
  }

  // Duplo clique na linha: abre a mesma tela usada pelo botão Editar.
  // A ação não interfere nos botões existentes da linha.
  document.getElementById('areaTabela').addEventListener('dblclick', (e) => {
    if (e.target.closest('button, a, input, select, textarea, [data-editar], [data-excluir], [data-visualizar]')) return;

    const linha = e.target.closest('tr');
    if (!linha) return;

    const botao = linha.querySelector('[data-editar], [data-visualizar]');
    if (!botao) return;

    const id = botao.dataset.editar || botao.dataset.visualizar;
    const registro = registros.find(r => r.id == id);
    if (registro) abrir(registro);
  });

  /* ------------------------------------------------------------- inicializa */
  montarModal();
  ligarAcoesLinha();
  const botaoNovo = document.getElementById('botaoNovo');
  if (botaoNovo && bloqueado()) botaoNovo.remove();
  else if (botaoNovo) botaoNovo.onclick = () => abrir();
  /* dataset.ligadoCrud evita ligar o mesmo listener duas vezes caso a tela
     tambem registre os filtros por conta propria. */
  ['filtroInicio', 'filtroFim'].forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.dataset.ligadoCrud) {
      el.dataset.ligadoCrud = '1';
      el.addEventListener('change', carregar);
    }
  });

  /* Se a carga inicial falhar, a mensagem aparece TAMBEM dentro da area da
     tabela. So o alerta nao bastava: ele some sozinho e a tela continua em
     branco, dando a impressao de que travou carregando. */
  preencherSelects().then(carregar).catch(e => {
    const area = document.getElementById('areaTabela');
    if (area) {
      area.innerHTML = `<div class="vazio"><i class="fa-solid fa-triangle-exclamation"
        style="color:var(--alerta)"></i><strong>Não consegui carregar esta tela</strong>
        ${SGMF.esc(e.message)}</div>`;
    }
    SGMF.falha(e.message);
  });

  return { carregar, abrir, dados: () => registros };
};
