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
  let ultimaCarga = 0;   // evita recarregar a cada troca de aba/foco
  let sujo = false;      // true quando algo foi salvo em outra aba da tela
  const FRESCOR_MS = 30000;
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

    const salvo = Number(veiculoSelecionado?.id || select.dataset.selecionado || 0);
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
    if (pneu.situacao === 'trocar') return 'vermelho';
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
        pneu.menor_sulco == null ? '—' : esc(SGMF.numero(pneu.menor_sulco,1)+' mm')
      }</div>` +
      `<div><strong>DOT:</strong> ${esc(pneu.dot || '—')}</div>`;
  }

  const SULCOS = ['mapaSulco1','mapaSulco2','mapaSulco3','mapaSulco4'];
  const CAMPOS_EDITAVEIS = ['mapaMedida','mapaNumeroFogo','mapaMarca','mapaDot', ...SULCOS];

  function limparFormulario(){
    ['mapaPneuId','mapaPneuPosicao','mapaPrefixo','mapaPlaca','mapaMedida',
     'mapaNumeroFogo','mapaMarca','mapaPosicaoCampo','mapaDot', ...SULCOS
    ].forEach(id => el(id).value='');
  }

  function avisoSulco(){
    const medidos = SULCOS.map(id => el(id).value).filter(v => v !== '').map(Number);
    const caixa = el('mapaAvisoPosicao');
    const limite = 4;
    if (medidos.length && Math.min(...medidos) < limite){
      caixa.className = 'alert alert-danger border mt-4 mb-0';
      caixa.innerHTML = `<strong>TROCAR:</strong> menor sulco ${esc(SGMF.numero(Math.min(...medidos),1))} mm, ` +
        `abaixo de ${limite} mm. Este pneu entrará nos alertas.`;
    }else{
      caixa.className = 'alert alert-light border mt-4 mb-0';
      caixa.innerHTML = `<strong>Posição fixa:</strong> ${esc(el('mapaPosicaoCampo').value)}. ` +
        `O cadastro será vinculado à frota <strong>${esc(frotaNome(veiculoSelecionado))}</strong>.`;
    }
  }

  function preencherFormulario(pos, pneu){
    limparFormulario();

    el('mapaPneuId').value = pneu?.id || '';
    el('mapaPneuPosicao').value = pos.nome;
    el('mapaPrefixo').value = veiculoSelecionado?.prefixo || '';
    el('mapaPlaca').value = veiculoSelecionado?.placa || '';
    el('mapaPosicaoCampo').value = pos.display;
    el('mapaNumeroFogo').value = pneu?.numero_fogo || pneusOS[pos.nome]?.numero_fogo || '';
    el('mapaMarca').value = pneu?.marca || '';
    el('mapaMedida').value = pneu?.medida || '';
    el('mapaSulco1').value = pneu?.sulco_1 ?? '';
    el('mapaSulco2').value = pneu?.sulco_2 ?? '';
    el('mapaSulco3').value = pneu?.sulco_3 ?? '';
    el('mapaSulco4').value = pneu?.sulco_4 ?? '';
    el('mapaDot').value = pneu?.dot || '';

    el('modalMapaTitulo').textContent =
      pneu ? `Editar pneu ${pneu.numero_fogo}` : `Cadastrar pneu — posição ${pos.n}`;
    el('modalMapaPosicao').textContent = pos.display;

    const bloqueado = somenteLeitura();
    CAMPOS_EDITAVEIS.forEach(id => { el(id).disabled = bloqueado; });
    el('btnSalvarMapaPneu').disabled = bloqueado;
    avisoSulco();
  }

  function abrirPneu(pos, pneu){
    pneuAtual = pneu;
    atualizarResumo(pneu);
    preencherFormulario(pos,pneu);
    bootstrap.Modal.getOrCreateInstance(el('modalMapaPneu')).show();
  }

  async function carregar(forcar = true){
    if (!forcar && !sujo && Date.now() - ultimaCarga < FRESCOR_MS) return;
    try{
      // A lista de veículos quase não muda: só é buscada na 1ª vez ou ao forçar.
      const reqVeiculos = (forcar || !veiculos.length)
        ? SGMF.get('/api/veiculos') : Promise.resolve(veiculos);
      const [listaVeiculos, controle] = await Promise.all([
        reqVeiculos,
        SGMF.get('/api/controle-pneus')
      ]);
      veiculos = listaVeiculos || [];
      pneus = (controle && controle.linhas) || [];
      sujo = false;
      ultimaCarga = Date.now();

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

    const num = id => el(id).value === '' ? null : Number(el(id).value);
    const dados = {
      veiculo_id: Number(veiculoSelecionado.id),
      numero_fogo: numero,
      status: 'Em uso',
      posicao: el('mapaPneuPosicao').value,
      medida: el('mapaMedida').value.trim() || null,
      marca: el('mapaMarca').value.trim() || null,
      sulco_1: num('mapaSulco1'),
      sulco_2: num('mapaSulco2'),
      sulco_3: num('mapaSulco3'),
      sulco_4: num('mapaSulco4'),
      // km e km/sulco não aparecem neste formulário: preserva o que já existe.
      km: pneuAtual?.km ?? null,
      km_por_sulco: pneuAtual?.km_por_sulco ?? null,
      dot: el('mapaDot').value.trim() || null
    };

    if ([dados.sulco_1, dados.sulco_2, dados.sulco_3, dados.sulco_4].every(v => v == null))
      return SGMF.aviso('Informe ao menos um sulco (mm).');

    // Nº de fogo diferente do pneu que está na posição = troca de pneu.
    let trocaDePneu = false;
    if (pneuAtual?.id && pneuAtual.numero_fogo !== numero){
      const ok = await SGMF.confirmar(
        'Trocar o pneu desta posição?',
        `A posição já tem o pneu ${pneuAtual.numero_fogo}. Ele será marcado como ` +
        `Descartado e o pneu ${numero} ocupará o lugar.`,
        'Trocar pneu');
      if (!ok) return;
      trocaDePneu = true;
      dados.substituir = true;
      dados.km = null;
      dados.km_por_sulco = null;
    }

    const btn = el('btnSalvarMapaPneu');
    btn.disabled = true;

    try{
      const editando = pneuAtual?.id && !trocaDePneu;
      if (editando)
        await SGMF.put(`/api/controle-pneus/${pneuAtual.id}`, dados);
      else
        await SGMF.post('/api/controle-pneus', dados);

      bootstrap.Modal.getInstance(el('modalMapaPneu')).hide();
      SGMF.sucesso(editando ? 'Pneu atualizado' : 'Pneu cadastrado no mapa');

      document.dispatchEvent(new Event('pneus:alterado'));
      await carregar(true);
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

  SULCOS.forEach(id => el(id).addEventListener('input', avisoSulco));
  el('btnAtualizarPneus').addEventListener('click', () => carregar(true));
  el('btnSalvarMapaPneu').addEventListener('click', salvar);

  // Eventos entre as duas abas da tela (evita recarregar tudo a cada clique).
  document.addEventListener('pneus:alterado', () => { sujo = true; });
  document.addEventListener('pneus:mapa-visivel', () => carregar(false));

  // Ao voltar para a janela, só recarrega se os dados estiverem velhos.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) carregar(false);
  });

  carregar(true);
})();
