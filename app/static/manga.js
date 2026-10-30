const CHAVE_TAMANHO_FAIXA = 'mangakindle.tamanhoFaixa';
const TAMANHO_FAIXA_PADRAO = '10';

const itensCapitulo = [...document.querySelectorAll('.lista-capitulos li')];
const controlesFaixa = document.querySelector('.controles-faixa');
const seletorTamanho = document.getElementById('tamanho-faixa');
const seletorFaixa = document.getElementById('faixa');
const botaoFaixaAnterior = document.getElementById('faixa-anterior');
const botaoFaixaProxima = document.getElementById('faixa-proxima');
const contadorSelecionados = document.getElementById('contador-selecionados');
const botaoEnviar = document.getElementById('botao-enviar');
const formularioEnvio = document.getElementById('formulario-envio');
const opcaoReenvio = document.querySelector('.opcao-reenvio');
const caixaPermitirReenvio = document.getElementById('permitir-reenvio');

// Cada faixa guarda a posição do primeiro e do último capítulo na lista (em ordem de leitura).
let faixas = [];
let faixaAtual = 0;

function caixaDoCapitulo(item) {
  return item.querySelector('input[name=capitulos]');
}

function podeSerSelecionado(item) {
  return !caixaDoCapitulo(item).disabled;
}

// Os botões "Marcar não enviados" nunca pegam capítulos já enviados, mesmo com o reenvio liberado.
function aindaNaoFoiEnviado(item) {
  return item.dataset.estado === 'disponivel';
}

function liberarReenvio(permitido) {
  for (const item of itensCapitulo) {
    if (item.dataset.estado !== 'enviado') {
      continue;
    }
    const caixa = caixaDoCapitulo(item);
    caixa.disabled = !permitido;
    if (!permitido) {
      caixa.checked = false;
    }
  }
  atualizarContador();
}

function lerTamanhoSalvo() {
  try {
    return localStorage.getItem(CHAVE_TAMANHO_FAIXA) || TAMANHO_FAIXA_PADRAO;
  } catch {
    return TAMANHO_FAIXA_PADRAO;
  }
}

function salvarTamanho(tamanho) {
  try {
    localStorage.setItem(CHAVE_TAMANHO_FAIXA, tamanho);
  } catch {
    // Sem armazenamento (ex.: aba anônima): o tamanho só não fica lembrado.
  }
}

function montarFaixas() {
  const capitulosPorFaixa = seletorTamanho.value === 'todos' ? itensCapitulo.length : Number(seletorTamanho.value);
  faixas = [];

  for (let inicio = 0; inicio < itensCapitulo.length; inicio += capitulosPorFaixa) {
    const fim = Math.min(inicio + capitulosPorFaixa, itensCapitulo.length) - 1;
    faixas.push({ inicio, fim });
  }

  seletorFaixa.replaceChildren(
    ...faixas.map((faixa, indice) => {
      const primeiroNumero = itensCapitulo[faixa.inicio].dataset.numero;
      const ultimoNumero = itensCapitulo[faixa.fim].dataset.numero;
      const rotulo = primeiroNumero === ultimoNumero ? `Cap. ${primeiroNumero}` : `Cap. ${primeiroNumero}–${ultimoNumero}`;
      return new Option(rotulo, String(indice));
    })
  );
}

function faixaQueContem(posicao) {
  const indice = faixas.findIndex((faixa) => posicao >= faixa.inicio && posicao <= faixa.fim);
  return Math.max(indice, 0);
}

function mostrarFaixa(indice) {
  faixaAtual = indice;
  const faixa = faixas[indice];

  itensCapitulo.forEach((item, posicao) => {
    item.hidden = posicao < faixa.inicio || posicao > faixa.fim;
  });

  seletorFaixa.value = String(indice);
  botaoFaixaAnterior.disabled = indice === 0;
  botaoFaixaProxima.disabled = indice === faixas.length - 1;
  atualizarContador();
}

function atualizarContador() {
  const selecionados = itensCapitulo.filter((item) => caixaDoCapitulo(item).checked);
  const foraDaFaixa = selecionados.filter((item) => item.hidden).length;

  if (selecionados.length === 0) {
    contadorSelecionados.textContent = 'Nenhum capítulo selecionado';
  } else {
    const plural = selecionados.length === 1 ? 'capítulo selecionado' : 'capítulos selecionados';
    const avisoForaDaFaixa = foraDaFaixa > 0 ? ` (${foraDaFaixa} fora desta faixa)` : '';
    contadorSelecionados.textContent = `${selecionados.length} ${plural}${avisoForaDaFaixa}`;
  }
  botaoEnviar.disabled = selecionados.length === 0;
}

function marcarCapitulos(selecao) {
  for (const item of itensCapitulo) {
    const estaNaFaixaVisivel = !item.hidden;
    if (selecao === 'nenhum') {
      caixaDoCapitulo(item).checked = false;
    } else if (selecao === 'todos' && aindaNaoFoiEnviado(item)) {
      caixaDoCapitulo(item).checked = true;
    } else if (selecao === 'faixa' && estaNaFaixaVisivel && aindaNaoFoiEnviado(item)) {
      caixaDoCapitulo(item).checked = true;
    }
  }
  atualizarContador();
}

function iniciarFaixas() {
  if (itensCapitulo.length === 0) {
    return;
  }

  controlesFaixa.hidden = false;
  seletorTamanho.value = lerTamanhoSalvo();
  montarFaixas();

  // Depois de marcar um capítulo como lido, a página volta com #capitulo-ID e abre na faixa dele.
  // Sem isso, abre na faixa do primeiro capítulo que ainda não foi enviado nem está na fila.
  const capituloDoEndereco = document.getElementById(decodeURIComponent(location.hash.slice(1)));
  const posicaoDoEndereco = capituloDoEndereco ? itensCapitulo.indexOf(capituloDoEndereco.closest('li')) : -1;
  if (posicaoDoEndereco >= 0) {
    mostrarFaixa(faixaQueContem(posicaoDoEndereco));
    capituloDoEndereco.closest('li').scrollIntoView({ block: 'center' });
  } else {
    const primeiroDisponivel = itensCapitulo.findIndex(podeSerSelecionado);
    mostrarFaixa(faixaQueContem(Math.max(primeiroDisponivel, 0)));
  }

  seletorTamanho.addEventListener('change', () => {
    const primeiroVisivel = faixas[faixaAtual].inicio;
    salvarTamanho(seletorTamanho.value);
    montarFaixas();
    mostrarFaixa(faixaQueContem(primeiroVisivel));
  });
  seletorFaixa.addEventListener('change', () => mostrarFaixa(Number(seletorFaixa.value)));
  botaoFaixaAnterior.addEventListener('click', () => mostrarFaixa(faixaAtual - 1));
  botaoFaixaProxima.addEventListener('click', () => mostrarFaixa(faixaAtual + 1));
}

for (const botao of document.querySelectorAll('button[data-selecao]')) {
  botao.addEventListener('click', () => marcarCapitulos(botao.dataset.selecao));
}
for (const item of itensCapitulo) {
  caixaDoCapitulo(item).addEventListener('change', atualizarContador);
}

if (opcaoReenvio) {
  opcaoReenvio.hidden = false;
  caixaPermitirReenvio.addEventListener('change', () => liberarReenvio(caixaPermitirReenvio.checked));
}

// Trava o botão depois do primeiro toque para não criar o mesmo envio duas vezes.
// Os botões de "lido" também enviam este formulário, mas para outro endereço.
formularioEnvio.addEventListener('submit', (evento) => {
  if (evento.submitter !== botaoEnviar) {
    return;
  }
  botaoEnviar.disabled = true;
  botaoEnviar.textContent = 'Colocando na fila…';
});

iniciarFaixas();
atualizarContador();
