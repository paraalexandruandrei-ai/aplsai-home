from datetime import datetime
import app as app_module

# SQLite restituisce le DateTime esistenti senza timezone. Manteniamo lo stesso
# formato anche per i nuovi valori, evitando confronti naive/aware nel profilo.
def utcnow_compatible():
    return datetime.utcnow()

app_module.utcnow = utcnow_compatible
app = app_module.create_app()

# Su mobile il wizard originale forza lo scroll a inizio pagina a ogni scelta.
# Intercettiamo solo quel salto mentre il wizard e' visibile; Home/aree restano normali.
MOBILE_FIX = r'''<script>
(function () {
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
})();
</script>'''

@app.after_request
def aplsai_mobile_fix(response):
    if response.content_type and response.content_type.startswith('text/html'):
        html = response.get_data(as_text=True)
        if '</body>' in html:
            html = html.replace('</body>', MOBILE_FIX + '\n</body>')
            response.set_data(html)
            response.headers['Content-Length'] = str(len(response.get_data()))
    return response
