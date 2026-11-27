(function () {
  var form = document.getElementById('login');
  var whatsapp = document.getElementById('whatsapp');
  var senha = document.getElementById('senha');
  var status = document.getElementById('status');
  var toggle = document.getElementById('toggle');

  toggle.addEventListener('click', function () {
    var oculto = senha.type === 'password';
    senha.type = oculto ? 'text' : 'password';
    toggle.textContent = oculto ? 'Ocultar' : 'Mostrar';
    toggle.setAttribute('aria-pressed', oculto);
  });

  function erro(input, msg) {
    document.getElementById(input.id + '-e').textContent = msg || '';
    input.setAttribute('aria-invalid', msg ? 'true' : 'false');
    return !msg;
  }

  function validar() {
    var digitos = whatsapp.value.replace(/\D/g, '');
    var okW = erro(whatsapp, (digitos.length < 10 || digitos.length > 13)
      ? 'Digite o WhatsApp com DDD. Exemplo: (19) 99999-9999.' : '');
    var okS = erro(senha, senha.value ? '' : 'Digite sua senha.');
    if (!okW) whatsapp.focus(); else if (!okS) senha.focus();
    return okW && okS;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!validar()) return;

    var btn = form.querySelector('.submit');
    var texto = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Aguarde...';
    status.hidden = true;

    fetch(form.action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ whatsapp: whatsapp.value, senha: senha.value })
    })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        location.href = 'painel.html';
      })
      .catch(function () {
        status.textContent = 'WhatsApp ou senha incorretos, ou o serviço está indisponível. Tente de novo.';
        status.hidden = false;
        btn.disabled = false;
        btn.textContent = texto;
      });
  });
})();
