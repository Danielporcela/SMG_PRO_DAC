(() => {
  // Convenção da imagem superior:
  // - frente do caminhão = esquerda da imagem
  // - parte superior da imagem = lado DIREITO do caminhão
  // - parte inferior da imagem = lado ESQUERDO do caminhão
  //
  // Total: 10 pneus
  // 2 dianteiros + 4 no 1º eixo traseiro + 4 no 2º eixo traseiro.
  const POSICOES = [
    {n:1, nome:'Dianteiro direito', display:'1º eixo dianteiro — direito', cor:'vermelho', x:23.9, y:27.0},
    {n:2, nome:'Dianteiro esquerdo', display:'1º eixo dianteiro — esquerdo', cor:'vermelho', x:23.9, y:76.7},

    // 1º eixo traseiro: os pneus externo e interno ficam no MESMO eixo.
    {n:3, nome:'Tração traseiro externo direito', display:'1º eixo traseiro — externo direito', cor:'verde', x:65.7, y:26.1},
    {n:4, nome:'Tração traseiro interno direito', display:'1º eixo traseiro — interno direito', cor:'azul', x:65.7, y:35.3},
    {n:5, nome:'Tração traseiro interno esquerdo', display:'1º eixo traseiro — interno esquerdo', cor:'azul', x:65.7, y:71.8},
    {n:6, nome:'Tração traseiro externo esquerdo', display:'1º eixo traseiro — externo esquerdo', cor:'verde', x:65.7, y:80.3},

    // 2º eixo traseiro: os pneus externo e interno ficam no MESMO eixo.
    {n:7, nome:'Truck traseiro externo direito', display:'2º eixo traseiro — externo direito', cor:'verde', x:79.2, y:26.1},
    {n:8, nome:'Truck traseiro interno direito', display:'2º eixo traseiro — interno direito', cor:'azul', x:79.2, y:35.3},
    {n:9, nome:'Truck traseiro interno esquerdo', display:'2º eixo traseiro — interno esquerdo', cor:'azul', x:79.2, y:71.8},
    {n:10, nome:'Truck traseiro externo esquerdo', display:'2º eixo traseiro — externo esquerdo', cor:'verde', x:79.2, y:80.3}
  ];

  let veiculos = [];
  let pneus = [];
  let pneusOS = {};   // pneus lançados nas OS da frota, por posição
  let veiculoSelecionado = null;
  let pneuAtual = null;
  const somenteLeitura = () => SGMF.somenteLeitura('pneus');

  const el = id => document.getElementById(id);
  const esc = v => SGMF.esc(v == null ? '' : v);

  function setStatus(msg, erro=false){
    const box = el('mapaStatus');
    box.textContent = msg;
    box.style.background = erro ? '#fde8e8' : '#fff5cf';
    box.style.color = erro ? '#8b1e1e' : '#6c5500';
  }

  function frotaNome(v){
    return `${v.prefixo || '—'} · ${v.placa || '—'}`;
  }

  function renderFrotas(){
    const select = el('pneuFrota');
    const atuais = veiculos.filter(v => !v.grupo_consumo_legado);
    select.innerHTML = atuais
      .map(v => `<option value="${esc(v.id)}">${esc(frotaNome(v))}</option>`)
      .join('');

    if (!atuais.length){
      setStatus('Nenhum veículo disponível para o mapa.', true);
      return;
    }

    const salvo = Number(select.dataset.selecionado || 0);
    const alvo = atuais.find(v => v.id === salvo) || atuais[0];
    select.value = alvo.id;
    veiculoSelecionado = alvo;
  }

  function pneusDaFrota(){
    return pneus.filter(
      p => Number(p.veiculo_id) === Number(veiculoSelecionado?.id) &&
           p.status === 'Em uso'
    );
  }

  function normalizarPosicao(valor){
    const s = String(valor || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g,'')
      .toLowerCase()
      .trim();

    const mapa = {
      'dianteiro esquerdo':'Dianteiro esquerdo',
      'dianteiro direito':'Dianteiro direito',
      'traseiro esquerdo externo':'Tração traseiro externo esquerdo',
      'traseiro esquerdo interno':'Tração traseiro interno esquerdo',
      'traseiro direito externo':'Tração traseiro externo direito',
      'traseiro direito interno':'Tração traseiro interno direito',
      'tracao traseiro externo esquerdo':'Tração traseiro externo esquerdo',
      'tracao traseiro interno esquerdo':'Tração traseiro interno esquerdo',
      'tracao traseiro interno direito':'Tração traseiro interno direito',
      'tracao traseiro externo direito':'Tração traseiro externo direito',
      'truck traseiro externo esquerdo':'Truck traseiro externo esquerdo',
      'truck traseiro interno esquerdo':'Truck traseiro interno esquerdo',
      'truck traseiro interno direito':'Truck traseiro interno direito',
      'truck traseiro externo direito':'Truck traseiro externo direito'
    };

    return mapa[s] || valor;
  }

  function buscarPneu(pos){
    return pneusDaFrota().find(
      p => normalizarPosicao(p.posicao) === pos.nome
    ) || null;
  }

  function fogoDaPosicao(pos, pneu){
    // 1º o pneu cadastrado em uso; 2º o que foi lançado na OS.
    return pneu?.numero_fogo || pneusOS[pos.nome]?.numero_fogo || '';
  }

  async function carregarPneusOS(){
    pneusOS = {};
    if (!veiculoSelecionado) return;
    try{
      pneusOS = await SGMF.get(`/api/mapa-pneus/${veiculoSelecionado.id}/os`) || {};
    }catch(e){ pneusOS = {}; }
  }

  function corHotspot(pos, pneu){
    if (!pneu && !pneusOS[pos.nome]?.numero_fogo)
      return pos.cor === 'vermelho' ? 'vermelho' : 'cinza';
    if (!pneu) return pos.cor;
    if (pneu.trocar) return 'vermelho';
    return pos.cor;
  }

  function renderMapa(){
    const areas = el('areasPneus');
    areas.innerHTML = '';

    POSICOES.forEach(pos => {
      const pneu = buscarPneu(pos);
      const doOS = pneusOS[pos.nome];
      const fogo = fogoDaPosicao(pos, pneu);
      const button = document.createElement('button');

      button.type = 'button';
      button.className =
        `pneu-hotspot ${corHotspot(pos,pneu)} ${fogo ? 'cadastrado' : ''} ${!pneu && fogo ? 'so-os' : ''}`;

      button.style.left = `${pos.x}%`;
      button.style.top = `${pos.y}%`;
      button.title = fogo
        ? `${pos.display} — pneu ${fogo}` +
          (!pneu && doOS ? ` (lançado na OS ${doOS.os_numero || doOS.os_id}, ainda sem cadastro completo)` : '')
        : `${pos.display} — sem pneu`;
      button.setAttribute('aria-label', button.title);
      button.innerHTML =
        `<em class="pneu-n">${pos.n}</em>` +
        `<span class="pneu-fogo">${fogo ? esc(fogo) : '—'}</span>`;

      button.addEventListener('click', () => abrirPneu(pos, pneu));
      areas.appendChild(button);
    });

    const preenchidas = POSICOES.filter(
      pos => fogoDaPosicao(pos, buscarPneu(pos))
    ).length;
    setStatus(
      `${frotaNome(veiculoSelecionado)} — ${preenchidas}/10 posições com pneu (cadastro + OS).`
    );
    atualizarResumo(null);
  }

  function atualizarResumo(pneu){
    const p = el('pneuSelecionado');

    if (!pneu){
      p.innerHTML =
        '<div><strong>Pneu selecionado:</strong> —</div>' +
        '<div><strong>Posição:</strong> —</div>' +
        '<div><strong>Nº de fogo:</strong> —</div>' +
        '<div><strong>Status:</strong> —</div>' +
        '<div><strong>Sulco:</strong> —</div>';
      return;
    }

    p.innerHTML =
      `<div><strong>Pneu selecionado:</strong> #${esc(pneu.id)}</div>` +
      `<div><strong>Posição:</strong> ${esc(pneu.posicao)}</div>` +
      `<div><strong>Nº de fogo:</strong> ${esc(pneu.numero_fogo)}</div>` +
      `<div><strong>Status:</strong> ${esc(pneu.status)}</div>` +
      `<div><strong>Sulco:</strong> ${
        pneu.sulco_mm == null ? '—' : esc(SGMF.numero(pneu.sulco_mm,1)+' mm')
      }</div>`;
  }

  function limparFormulario(){
    [
      'mapaPneuId',
      'mapaPneuPosicao',
      'mapaNumeroFogo',
      'mapaMarca',
      'mapaMedida',
      'mapaSulco',
      'mapaKm',
      'mapaData',
      'mapaCusto',
      'mapaMedicao'
    ].forEach(id => el(id).value='');

    el('mapaVida').value = 'Novo';
    el('mapaStatusPneu').value = 'Em uso';
  }

  function preencherFormulario(pos, pneu){
    limparFormulario();

    el('mapaPneuId').value = pneu?.id || '';
    el('mapaPneuPosicao').value = pos.nome;
    el('mapaNumeroFogo').value = pneu?.numero_fogo || '';
    el('mapaMarca').value = pneu?.marca || '';
    el('mapaMedida').value = pneu?.medida || '';
    el('mapaSulco').value = pneu?.sulco_mm ?? '';
    el('mapaKm').value = pneu?.km_instalacao ?? '';
    el('mapaData').value = pneu?.data_instalacao || SGMF.hoje();
    el('mapaVida').value = pneu?.vida || 'Novo';
    el('mapaStatusPneu').value = pneu?.status || 'Em uso';
    el('mapaCusto').value = pneu?.custo ?? '';
    el('mapaMedicao').value = pneu?.data_medicao || SGMF.hoje();

    el('modalMapaTitulo').textContent =
      pneu ? `Editar pneu ${pneu.numero_fogo}` : `Cadastrar pneu — posição ${pos.n}`;

    el('modalMapaPosicao').textContent = pos.display;

    el('mapaAvisoPosicao').innerHTML =
      `<strong>Posição fixa:</strong> ${esc(pos.display)}. ` +
      `O cadastro será vinculado à frota <strong>${esc(frotaNome(veiculoSelecionado))}</strong>.`;

    if (!pneu && pneusOS[pos.nome]?.numero_fogo)
      el('mapaNumeroFogo').value = pneusOS[pos.nome].numero_fogo;

    el('btnSalvarMapaPneu').disabled = somenteLeitura();
    el('mapaNumeroFogo').disabled = somenteLeitura();
  }

  function abrirPneu(pos, pneu){
    pneuAtual = pneu;
    atualizarResumo(pneu);
    preencherFormulario(pos,pneu);
    bootstrap.Modal.getOrCreateInstance(el('modalMapaPneu')).show();
  }

  async function carregar(){
    try{
      [veiculos,pneus] = await Promise.all([
        SGMF.get('/api/veiculos'),
        SGMF.get('/api/pneus')
      ]);

      renderFrotas();
      await carregarPneusOS();
      renderMapa();
    }catch(e){
      setStatus(e.message || 'Não foi possível carregar o mapa.', true);
    }
  }

  async function salvar(){
    if (somenteLeitura())
      return SGMF.aviso('Seu acesso é somente leitura nesta tela.');

    if (!veiculoSelecionado)
      return SGMF.aviso('Selecione uma frota.');

    const numero = el('mapaNumeroFogo').value.trim().toUpperCase();

    if (!numero)
      return SGMF.aviso('Informe o número de fogo.');

    const dados = {
      numero_fogo: numero,
      veiculo_id: Number(veiculoSelecionado.id),
      posicao: el('mapaPneuPosicao').value,
      marca: el('mapaMarca').value.trim() || null,
      medida: el('mapaMedida').value.trim() || null,
      sulco_mm: el('mapaSulco').value === ''
        ? null : Number(el('mapaSulco').value),
      km_instalacao: el('mapaKm').value === ''
        ? null : Number(el('mapaKm').value),
      data_instalacao: el('mapaData').value || null,
      vida: el('mapaVida').value,
      status: el('mapaStatusPneu').value,
      custo: el('mapaCusto').value === ''
        ? null : Number(el('mapaCusto').value),
      data_medicao: el('mapaMedicao').value || null
    };

    const btn = el('btnSalvarMapaPneu');
    btn.disabled = true;

    try{
      if (pneuAtual?.id)
        await SGMF.put(`/api/pneus/${pneuAtual.id}`, dados);
      else
        await SGMF.post('/api/pneus', dados);

      bootstrap.Modal.getInstance(el('modalMapaPneu')).hide();

      SGMF.sucesso(
        pneuAtual?.id ? 'Pneu atualizado' : 'Pneu cadastrado no mapa'
      );

      await carregar();
    }catch(e){
      SGMF.falha(e.message);
    }finally{
      btn.disabled = somenteLeitura();
    }
  }

  el('pneuFrota').addEventListener('change', e => {
    veiculoSelecionado =
      veiculos.find(v => Number(v.id) === Number(e.target.value)) || null;
    carregarPneusOS().then(renderMapa);
  });

  el('btnAtualizarPneus').addEventListener('click', carregar);
  el('btnSalvarMapaPneu').addEventListener('click', salvar);

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) carregar();
  });

  carregar();
})();
