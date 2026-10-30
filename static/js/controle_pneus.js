(() => {
  // Controle de pneus — tabela com prefixo, placa, medida, nº de fogo, marca,
  // posição, sulcos 1 a 4, situação, km, km/sulco e DOT.
  // Alerta de troca: menor sulco abaixo do limite (SULCO_MINIMO_MM, padrão 4 mm).
  const POSICOES = [
    'Dianteiro esquerdo', 'Dianteiro direito',
    'Tração traseiro externo esquerdo', 'Tração traseiro interno esquerdo',
    'Tração traseiro interno direito', 'Tração traseiro externo direito',
    'Truck traseiro externo esquerdo', 'Truck traseiro interno esquerdo',
    'Truck traseiro interno direito', 'Truck traseiro externo direito',
    'Estepe'
  ];

  let linhas = [];
  let veiculos = [];
  let limite = 4;
  let ultimaCarga = 0;   // evita recarregar a cada troca de aba
  let sujo = false;      // true quando o mapa salvou algo
  const FRESCOR_MS = 30000;

  const el = id => document.getElementById(id);
  const esc = v => SGMF.esc(v == null ? '' : v);
  const somenteLeitura = () => SGMF.somenteLeitura('pneus');

  const fmt = (v, max = 1) => v == null || v === ''
    ? '—'
    : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: max });

  const ROTULO_SITUACAO = {
    trocar: ['TROCAR', 'vermelha'],
    atencao: ['ATENÇÃO', 'ambar'],
    ok: ['OK', 'verde'],
    sem_medicao: ['SEM MEDIÇÃO', 'cinza']
  };

  function etiquetaSituacao(l) {
    const item = ROTULO_SITUACAO[l.situacao];
    return item ? SGMF.etiqueta(item[0], item[1]) : '<span class="cp-traco">—</span>';
  }

  function celulaSulco(l, campo) {
    const v = l[campo];
    if (v == null) return '<span class="cp-traco">—</span>';
    const abaixo = l.status === 'Em uso' && v < limite;
    return `<span class="${abaixo ? 'cp-sulco-baixo' : ''}">${esc(fmt(v, 1))}</span>`;
  }

  function linhasFiltradas() {
    const termo = el('cpBusca').value.trim().toLowerCase();
    const frota = el('cpFiltroFrota').value;
    const status = el('cpFiltroStatus').value;
    const soTrocar = el('cpSoTrocar').checked;

    return linhas.filter(l => {
      if (frota && String(l.veiculo_id) !== frota) return false;
      if (status && l.status !== status) return false;
      if (soTrocar && l.situacao !== 'trocar') return false;
      if (!termo) return true;
      const texto = [l.prefixo, l.placa, l.medida, l.numero_fogo, l.marca,
                     l.posicao, l.dot].join(' ').toLowerCase();
      return texto.includes(termo);
    });
  }

  function renderTabela() {
    const corpo = el('cpCorpo');
    const lista = linhasFiltradas();

    if (!lista.length) {
      corpo.innerHTML = '<tr><td colspan="15" class="cp-vazio">' +
        (linhas.length ? 'Nenhum pneu para este filtro.'
                       : 'Nenhum pneu cadastrado. Use “Novo pneu” para começar.') +
        '</td></tr>';
    } else {
      corpo.innerHTML = lista.map(l => {
        const classe = l.situacao === 'trocar' ? 'cp-trocar'
                     : l.situacao === 'atencao' ? 'cp-atencao' : '';
        const acao = somenteLeitura() ? '' :
          `<button class="btn btn-sm btn-contorno" data-editar="${esc(l.id)}" ` +
          `title="Editar / lançar medição"><i class="fa-solid fa-pen"></i></button>`;
        return `<tr class="${classe}">` +
          `<td><strong>${esc(l.prefixo || '—')}</strong></td>` +
          `<td>${esc(l.placa || '—')}</td>` +
          `<td>${esc(l.medida || '—')}</td>` +
          `<td><strong>${esc(l.numero_fogo)}</strong></td>` +
          `<td>${esc(l.marca || '—')}</td>` +
          `<td>${esc(l.posicao || '—')}</td>` +
          `<td class="cp-num">${celulaSulco(l, 'sulco_1')}</td>` +
          `<td class="cp-num">${celulaSulco(l, 'sulco_2')}</td>` +
          `<td class="cp-num">${celulaSulco(l, 'sulco_3')}</td>` +
          `<td class="cp-num">${celulaSulco(l, 'sulco_4')}</td>` +
          `<td>${etiquetaSituacao(l)}</td>` +
          `<td class="cp-num">${esc(fmt(l.km, 0))}</td>` +
          `<td class="cp-num">${esc(fmt(l.km_por_sulco, 2))}</td>` +
          `<td>${esc(l.dot || '—')}</td>` +
          `<td>${acao}</td>` +
          '</tr>';
      }).join('');
    }

    el('cpRodape').textContent =
      `${lista.length} de ${linhas.length} pneu(s) exibido(s). ` +
      `Linhas em vermelho: menor sulco abaixo de ${fmt(limite, 1)} mm.`;
  }

  function renderAlerta() {
    const caixa = el('cpAlerta');
    const trocar = linhas.filter(l => l.situacao === 'trocar');
    if (!trocar.length) {
      caixa.classList.add('d-none');
      caixa.innerHTML = '';
      return;
    }
    const itens = trocar.map(l =>
      `<li><strong>${esc(l.prefixo || '—')}</strong> · ${esc(l.placa || '—')} · ` +
      `fogo <strong>${esc(l.numero_fogo)}</strong> · ${esc(l.posicao || 'sem posição')} — ` +
      `<strong>${esc(fmt(l.menor_sulco, 1))} mm</strong></li>`).join('');
    caixa.innerHTML =
      `<div class="cp-alerta-titulo"><i class="fa-solid fa-triangle-exclamation"></i> ` +
      `${trocar.length} pneu(s) com sulco abaixo de ${esc(fmt(limite, 1))} mm — ` +
      `programar a substituição</div><ul>${itens}</ul>`;
    caixa.classList.remove('d-none');
  }

  function renderFiltroFrota() {
    const select = el('cpFiltroFrota');
    const atual = select.value;
    const vistos = new Map();
    linhas.forEach(l => {
      if (l.veiculo_id != null && !vistos.has(l.veiculo_id))
        vistos.set(l.veiculo_id, `${l.prefixo || '—'} · ${l.placa || '—'}`);
    });
    select.innerHTML = '<option value="">Todas as frotas</option>' +
      [...vistos.entries()]
        .sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'))
        .map(([id, nome]) => `<option value="${esc(id)}">${esc(nome)}</option>`).join('');
    if (vistos.has(Number(atual))) select.value = atual;
  }

  async function carregar(forcar = true) {
    if (!forcar && !sujo && Date.now() - ultimaCarga < FRESCOR_MS) return;
    try {
      const [dados, listaVeiculos] = await Promise.all([
        SGMF.get('/api/controle-pneus'),
        // a lista de veículos quase não muda: só busca na 1ª vez ou ao forçar
        (forcar || !veiculos.length) ? SGMF.get('/api/veiculos') : Promise.resolve(veiculos)
      ]);
      sujo = false;
      ultimaCarga = Date.now();
      limite = Number(dados.limite) || 4;
      linhas = dados.linhas || [];
      veiculos = (listaVeiculos || []).filter(v => !v.grupo_consumo_legado);
      renderFiltroFrota();
      renderAlerta();
      renderTabela();
    } catch (e) {
      el('cpCorpo').innerHTML =
        `<tr><td colspan="15" class="cp-vazio">${esc(e.message || 'Não foi possível carregar os pneus.')}</td></tr>`;
    }
  }

  /* ------------------------------------------------------------ formulário */
  function preencherSelects() {
    el('cpVeiculo').innerHTML = '<option value="">Selecione…</option>' +
      veiculos
        .slice()
        .sort((a, b) => String(a.prefixo).localeCompare(String(b.prefixo), 'pt-BR', { numeric: true }))
        .map(v => `<option value="${esc(v.id)}">${esc(v.prefixo || '—')} · ${esc(v.placa || '—')}</option>`)
        .join('');
    el('cpPosicao').innerHTML = '<option value="">— sem posição —</option>' +
      POSICOES.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
  }

  const valorOuVazio = v => (v == null ? '' : v);

  function atualizarAvisoSulco() {
    const medidos = ['cpSulco1', 'cpSulco2', 'cpSulco3', 'cpSulco4']
      .map(id => el(id).value)
      .filter(v => v !== '')
      .map(Number);
    const caixa = el('cpAvisoSulco');
    if (medidos.length && Math.min(...medidos) < limite) {
      caixa.className = 'alert alert-danger border mt-3 mb-0';
      caixa.innerHTML = `<strong>TROCAR:</strong> menor sulco ${esc(fmt(Math.min(...medidos), 1))} mm, ` +
        `abaixo de ${esc(fmt(limite, 1))} mm. Este pneu entrará nos alertas.`;
    } else {
      caixa.className = 'alert alert-light border mt-3 mb-0';
      caixa.innerHTML = `Quando o menor sulco ficar abaixo de <strong>${esc(fmt(limite, 1))} mm</strong>, ` +
        'o pneu é marcado como <strong>TROCAR</strong> e entra nos alertas do sistema.';
    }
  }

  function abrirFormulario(linha) {
    preencherSelects();
    el('cpId').value = linha ? linha.id : '';
    el('cpVeiculo').value = linha && linha.veiculo_id != null ? linha.veiculo_id : '';
    el('cpFogo').value = linha ? linha.numero_fogo : '';
    el('cpStatus').value = linha ? linha.status : 'Em uso';
    el('cpMedida').value = linha ? valorOuVazio(linha.medida) : '';
    el('cpMarca').value = linha ? valorOuVazio(linha.marca) : '';
    el('cpPosicao').value = linha && linha.posicao ? linha.posicao : '';
    el('cpSulco1').value = linha ? valorOuVazio(linha.sulco_1) : '';
    el('cpSulco2').value = linha ? valorOuVazio(linha.sulco_2) : '';
    el('cpSulco3').value = linha ? valorOuVazio(linha.sulco_3) : '';
    el('cpSulco4').value = linha ? valorOuVazio(linha.sulco_4) : '';
    el('cpKm').value = linha ? valorOuVazio(linha.km) : '';
    el('cpKmSulco').value = linha ? valorOuVazio(linha.km_por_sulco) : '';
    el('cpDot').value = linha ? valorOuVazio(linha.dot) : '';
    el('cpModalTitulo').textContent = linha
      ? `Editar pneu ${linha.numero_fogo}` : 'Novo pneu';
    el('cpSalvar').disabled = somenteLeitura();
    atualizarAvisoSulco();
    bootstrap.Modal.getOrCreateInstance(el('modalControlePneu')).show();
  }

  const numeroOuNulo = id => el(id).value === '' ? null : Number(el(id).value);

  async function salvar() {
    if (somenteLeitura())
      return SGMF.aviso('Seu acesso é somente leitura nesta tela.');

    const id = el('cpId').value;
    const dados = {
      veiculo_id: el('cpVeiculo').value ? Number(el('cpVeiculo').value) : null,
      numero_fogo: el('cpFogo').value.trim().toUpperCase(),
      status: el('cpStatus').value,
      medida: el('cpMedida').value.trim() || null,
      marca: el('cpMarca').value.trim() || null,
      posicao: el('cpPosicao').value || null,
      sulco_1: numeroOuNulo('cpSulco1'),
      sulco_2: numeroOuNulo('cpSulco2'),
      sulco_3: numeroOuNulo('cpSulco3'),
      sulco_4: numeroOuNulo('cpSulco4'),
      km: numeroOuNulo('cpKm'),
      km_por_sulco: numeroOuNulo('cpKmSulco'),
      dot: el('cpDot').value.trim() || null
    };

    if (!dados.veiculo_id) return SGMF.aviso('Selecione o prefixo/placa do veículo.');
    if (!dados.numero_fogo) return SGMF.aviso('Informe o número de fogo.');
    if (dados.status === 'Em uso' &&
        [dados.sulco_1, dados.sulco_2, dados.sulco_3, dados.sulco_4].every(v => v == null))
      return SGMF.aviso('Informe ao menos um sulco (mm) para o pneu em uso.');

    // Posição já ocupada por outro pneu em uso da mesma frota: confirma a troca.
    if (dados.status === 'Em uso' && dados.posicao) {
      const ocupante = linhas.find(l =>
        String(l.id) !== String(id) &&
        l.status === 'Em uso' &&
        l.veiculo_id === dados.veiculo_id &&
        l.posicao === dados.posicao);
      if (ocupante) {
        const ok = await SGMF.confirmar(
          'Posição já ocupada',
          `A posição “${dados.posicao}” já tem o pneu ${ocupante.numero_fogo}. ` +
          'Ele será marcado como Descartado e substituído por este pneu.',
          'Substituir');
        if (!ok) return;
        dados.substituir = true;
      }
    }

    const btn = el('cpSalvar');
    btn.disabled = true;
    try {
      if (id) await SGMF.put(`/api/controle-pneus/${id}`, dados);
      else await SGMF.post('/api/controle-pneus', dados);

      bootstrap.Modal.getInstance(el('modalControlePneu')).hide();
      SGMF.sucesso(id ? 'Pneu atualizado' : 'Pneu cadastrado');
      document.dispatchEvent(new Event('pneus:alterado'));
      await carregar(true);
    } catch (e) {
      SGMF.falha(e.message);
    } finally {
      btn.disabled = somenteLeitura();
    }
  }

  /* ---------------------------------------------------------------- eventos */
  ['cpBusca', 'cpFiltroFrota', 'cpFiltroStatus', 'cpSoTrocar'].forEach(id => {
    el(id).addEventListener(id === 'cpBusca' ? 'input' : 'change', renderTabela);
  });

  el('cpCorpo').addEventListener('click', e => {
    const botao = e.target.closest('[data-editar]');
    if (!botao) return;
    const linha = linhas.find(l => String(l.id) === botao.dataset.editar);
    if (linha) abrirFormulario(linha);
  });

  ['cpSulco1', 'cpSulco2', 'cpSulco3', 'cpSulco4'].forEach(id =>
    el(id).addEventListener('input', atualizarAvisoSulco));

  el('btnNovoControlePneu').addEventListener('click', () => {
    if (somenteLeitura())
      return SGMF.aviso('Seu acesso é somente leitura nesta tela.');
    bootstrap.Tab.getOrCreateInstance(el('tabControle')).show();
    abrirFormulario(null);
  });

  el('cpSalvar').addEventListener('click', salvar);

  // Troca de aba: só recarrega se algo mudou ou se os dados ficaram velhos.
  document.addEventListener('pneus:alterado', () => { sujo = true; });
  el('tabMapa').addEventListener('shown.bs.tab',
    () => document.dispatchEvent(new Event('pneus:mapa-visivel')));
  el('tabControle').addEventListener('shown.bs.tab', () => carregar(false));

  carregar(true);
})();
