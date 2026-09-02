import re
from flask import request
import app as app_module

app = app_module.create_app()


# Difesa aggiuntiva per i campi testuali ricevuti dal browser.
# Le password non vengono mai trasformate: devono essere verificate esattamente
# come sono state inserite dall'utente.
def _sanitize_value(value, key=None):
    if key == "password":
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
        # I campi APLSAI sono testo/dati, non HTML. Impedisce payload HTML/script
        # memorizzati nei profili e successivamente mostrati nelle aree riservate.
        return value.replace("<", "").replace(">", "")
    return value


@app.before_request
def aplsai_sanitize_json_input():
    if request.method in {"POST", "PUT", "PATCH"} and request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            sanitized = _sanitize_value(payload)
            # Flask conserva in cache il JSON decodificato. Sostituiamo quella copia
            # affinché le route applicative leggano soltanto il payload ripulito.
            request._cached_json = (sanitized, sanitized)


# Correzioni UX e hardening browser applicati alla versione online senza alterare
# la struttura grafica approvata.
FINAL_UX = r'''<script>
(function () {
  // PRIVACY: dalla migrazione al backend, profili e sessioni non devono più essere
  // conservati nel localStorage del dispositivo. Rimuove anche eventuali residui
  // creati dalle prime versioni del prototipo.
  const obsoleteKeys = [
    'aplsai_profiles','aplsai_current_profile','aplsai_client_session',
    'aplsai_staff_session','aplsai_properties','aplsai_deals',
    'aplsai_referrals','aplsai_documents'
  ];
  try { obsoleteKeys.forEach(k => localStorage.removeItem(k)); } catch (_) {}
  if (typeof window.saveClientProfile === 'function') {
    window.saveClientProfile = function(){ return null; };
  }

  // PASSWORD: frontend allineato alla policy server (minimo 10 caratteri).
  const previousRender = window.render;
  if (typeof previousRender === 'function') {
    window.render = function(){
      const out = previousRender.apply(this, arguments);
      const password = document.getElementById('password');
      if (password) {
        password.minLength = 10;
        password.placeholder = 'Almeno 10 caratteri, lettere e numeri';
      }
      return out;
    };
  }
  const previousNext = window.next;
  if (typeof previousNext === 'function') {
    window.next = async function(){
      try {
        if (typeof step !== 'undefined' && step === 8) {
          const password = document.getElementById('password');
          if (password && password.value.length < 10) {
            if (typeof err === 'function') err('La password deve avere almeno 10 caratteri, con lettere e numeri.');
            return;
          }
        }
      } catch (_) {}
      return previousNext.apply(this, arguments);
    };
  }

  // MOBILE: durante una scelta il wizard non deve riportare il cliente
  // all'inizio della pagina. Home e aree riservate continuano a scorrere normalmente.
  const nativeScrollTo = window.scrollTo.bind(window);
  window.scrollTo = function(a, b) {
    let top = null;
    if (typeof a === 'object' && a !== null) top = a.top;
    else if (typeof a === 'number') top = (typeof b === 'number' ? b : a);
    const wizard = document.getElementById('wizardView');
    const wizardVisible = wizard && wizard.style.display !== 'none';
    if (window.innerWidth <= 700 && wizardVisible && top === 0) return;
    return nativeScrollTo(a, b);
  };

  // FINALE: messaggio conclusivo e azione chiara verso l'Area Cliente.
  if (typeof window.choose === 'function') {
    const previousChoose = window.choose;
    window.choose = async function(strategy, name) {
      await previousChoose(strategy, name);
      const box = document.getElementById('strategyMsg');
      if (!box) return;
      box.setAttribute('aria-live', 'polite');
      if (!box.querySelector('.aplsai-final-actions')) {
        box.insertAdjacentHTML('beforeend', `
          <div class="aplsai-final-actions" style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;justify-content:center">
            <button class="primary" onclick="showClientArea()" style="min-height:48px">Vai alla mia Area Cliente</button>
            <button class="secondary" onclick="goHome()" style="min-height:48px">Torna alla Home</button>
          </div>
          <p style="text-align:center;color:var(--muted);font-size:12px;margin:12px 0 0">
            La tua richiesta è stata salvata. APLSAI continuerà a lavorare sulle preferenze che hai indicato.
          </p>`);
      }
      setTimeout(function(){
        const target = box.querySelector('.success') || box;
        target.scrollIntoView({behavior:'smooth', block:'center'});
      }, 80);
    };
  }
})();
</script>'''


@app.after_request
def aplsai_final_ux(response):
    if response.content_type and response.content_type.startswith('text/html'):
        html = response.get_data(as_text=True)
        if '</body>' in html and 'aplsai-final-actions' not in html:
            html = html.replace('</body>', FINAL_UX + '\n</body>')
            response.set_data(html)
            response.headers['Content-Length'] = str(len(response.get_data()))
    return response
