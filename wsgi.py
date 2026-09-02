import app as app_module

app = app_module.create_app()

# Correzioni UX applicate alla versione online senza alterare la struttura grafica approvata.
FINAL_UX = r'''<script>
(function () {
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
