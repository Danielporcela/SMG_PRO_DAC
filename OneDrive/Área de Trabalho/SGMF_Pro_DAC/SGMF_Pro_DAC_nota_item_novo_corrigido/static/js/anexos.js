/* SGMF Pro — anexos de ordens de serviço e abastecimentos.
   Nota fiscal, foto do defeito e PDF ficam junto do lançamento. */

SGMF.anexos = (function () {

  const ID = 'modalAnexos';
  let contexto = { tipo: null, registro: null, aoFechar: null };

  /* 'ordens' e 'abastecimentos' são os nomes usados pela API; para saber
     se o usuário pode editar, precisamos do nome da TELA correspondente. */
  const TELA_POR_TIPO = { ordens: 'manutencao', abastecimentos: 'combustivel' };
  const podeEditarAnexo = (tipo) => SGMF.podeEditar(TELA_POR_TIPO[tipo] || tipo);

  function montarModal() {
    if (document.getElementById(ID)) return;
    document.body.insertAdjacentHTML('beforeend', `
    <div class="modal fade" id="${ID}" tabindex="-1">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header" style="background:var(--aco);color:#fff">
            <div>
              <h5 class="modal-title display mb-0">Anexos</h5>
              <small style="color:var(--hi-vis)" id="anexosSubtitulo"></small>
            </div>
            <button class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row g-2 align-items-end mb-3" id="anexosEnvio">
              <div class="col-md-5">
                <label class="form-label" for="anexoArquivo">Arquivo</label>
                <input type="file" class="form-control form-control-sm" id="anexoArquivo"
                       accept="image/jpeg,image/png,image/webp,image/gif,application/pdf">
              </div>
              <div class="col-md-5">
                <label class="form-label" for="anexoDescricao">Descrição</label>
                <input class="form-control form-control-sm" id="anexoDescricao"
                       placeholder="Ex.: nota fiscal da oficina">
              </div>
              <div class="col-md-2">
                <button class="btn btn-primario btn-sm w-100" id="anexoEnviar">
                  <i class="fa-solid fa-upload"></i> Anexar
                </button>
              </div>
              <div class="col-12">
                <div class="form-text" style="font-size:11.5px">
                  Fotos (JPG, PNG, WEBP) ou PDF, até 5 MB por arquivo.
                </div>
              </div>
            </div>
            <div id="anexosLista"></div>
          </div>
        </div>
      </div>
    </div>`);

    document.getElementById('anexoEnviar').onclick = enviar;
  }

  async function abrir(tipo, registro, subtitulo, aoFechar) {
    montarModal();
    contexto = { tipo, registro, aoFechar };
    document.getElementById('anexosSubtitulo').textContent = subtitulo || '';
    document.getElementById('anexoArquivo').value = '';
    document.getElementById('anexoDescricao').value = '';
    document.getElementById('anexosEnvio').style.display = podeEditarAnexo(tipo) ? '' : 'none';
    await listar();
    bootstrap.Modal.getOrCreateInstance(document.getElementById(ID)).show();
  }

  async function listar() {
    const { tipo, registro } = contexto;
    const anexos = await SGMF.get(`/api/anexos/${tipo}/${registro}`);
    const area = document.getElementById('anexosLista');

    if (!anexos.length) {
      area.innerHTML = `<div class="vazio"><i class="fa-solid fa-paperclip"></i>
        <strong>Nenhum arquivo anexado</strong>Guarde aqui a nota fiscal e as fotos do serviço.</div>`;
      return;
    }

    area.innerHTML = `<div class="row g-2">${anexos.map(a => `
      <div class="col-md-6">
        <div class="cartao h-100">
          <div class="cartao-corpo d-flex gap-3 align-items-start" style="padding:12px">
            ${a.imagem
              ? `<a href="/api/anexos/${a.id}/arquivo" target="_blank">
                   <img src="/api/anexos/${a.id}/arquivo" alt="${SGMF.esc(a.nome)}"
                        style="width:74px;height:74px;object-fit:cover;border-radius:4px;border:1px solid var(--linha)"></a>`
              : `<div style="width:74px;height:74px;display:grid;place-items:center;
                        background:var(--superficie);border-radius:4px;border:1px solid var(--linha)">
                   <i class="fa-solid fa-file-pdf" style="font-size:26px;color:var(--alerta)"></i></div>`}
            <div style="min-width:0;flex:1">
              <div style="font-weight:600;font-size:13px;word-break:break-word">${SGMF.esc(a.nome)}</div>
              ${a.descricao ? `<div style="font-size:12px;color:var(--texto-suave)">${SGMF.esc(a.descricao)}</div>` : ''}
              <div style="font-size:11.5px;color:var(--texto-suave)" class="num">
                ${SGMF.esc(a.tamanho_legivel)} · ${SGMF.esc(a.enviado_por || '')}
              </div>
              <div class="mt-2 d-flex gap-1">
                <a class="btn btn-contorno btn-icone" href="/api/anexos/${a.id}/arquivo?baixar=1" title="Baixar">
                  <i class="fa-solid fa-download"></i></a>
                <a class="btn btn-contorno btn-icone" href="/api/anexos/${a.id}/arquivo" target="_blank" title="Abrir">
                  <i class="fa-solid fa-up-right-from-square"></i></a>
                ${podeEditarAnexo(contexto.tipo) ?
                  `<button class="btn btn-contorno btn-icone" data-excluir-anexo="${a.id}" title="Excluir">
                     <i class="fa-solid fa-trash"></i></button>` : ''}
              </div>
            </div>
          </div>
        </div>
      </div>`).join('')}</div>`;

    document.querySelectorAll('[data-excluir-anexo]').forEach(b => b.onclick = async () => {
      if (!await SGMF.confirmar('Excluir anexo?', 'O arquivo será removido definitivamente.', 'Excluir')) return;
      try {
        await SGMF.del(`/api/anexos/${b.dataset.excluirAnexo}`);
        SGMF.sucesso('Anexo removido');
        await listar();
        if (contexto.aoFechar) contexto.aoFechar();
      } catch (e) { SGMF.falha(e.message); }
    });
  }

  async function enviar() {
    const campo = document.getElementById('anexoArquivo');
    if (!campo.files.length) return SGMF.aviso('Escolha o arquivo que quer anexar.');

    const corpo = new FormData();
    corpo.append('arquivo', campo.files[0]);
    corpo.append('descricao', document.getElementById('anexoDescricao').value);

    const botao = document.getElementById('anexoEnviar');
    botao.disabled = true;
    botao.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
      const resposta = await fetch(`/api/anexos/${contexto.tipo}/${contexto.registro}`,
                                   { method: 'POST', body: corpo, credentials: 'same-origin' });
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(dados.erro || 'Não consegui anexar o arquivo.');
      SGMF.sucesso('Arquivo anexado');
      campo.value = '';
      document.getElementById('anexoDescricao').value = '';
      await listar();
      if (contexto.aoFechar) contexto.aoFechar();
    } catch (e) {
      SGMF.falha(e.message);
    } finally {
      botao.disabled = false;
      botao.innerHTML = '<i class="fa-solid fa-upload"></i> Anexar';
    }
  }

  /* Botão padrão usado nas listagens. */
  function botao(tipo, item) {
    const quantidade = item.qtd_anexos || 0;
    return `<button class="btn btn-contorno btn-icone" data-anexos="${item.id}"
              title="Anexos${quantidade ? ` (${quantidade})` : ''}">
              <i class="fa-solid fa-paperclip"></i>${quantidade ? `<span class="num ms-1">${quantidade}</span>` : ''}
            </button>`;
  }

  function ligarBotoes(tipo, linhas, rotulo, aoFechar) {
    document.querySelectorAll('[data-anexos]').forEach(b => b.onclick = () => {
      const item = linhas.find(i => i.id == b.dataset.anexos);
      abrir(tipo, item.id, rotulo(item), aoFechar);
    });
  }

  return { abrir, botao, ligarBotoes };
})();
