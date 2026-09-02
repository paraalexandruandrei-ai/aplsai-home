import re
from flask import request
import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts

app = app_module.create_app()
init_operations(app, app_module)
install_runtime_rbac(app, app_module)
init_staff_accounts(app, app_module)


def _sanitize_value(value, key=None):
    if key == "password": return value
    if isinstance(value, dict): return {k:_sanitize_value(v,k) for k,v in value.items()}
    if isinstance(value, list): return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        value=re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]","",value)
        return value.replace("<","").replace(">","")
    return value

@app.before_request
def aplsai_sanitize_json_input():
    if request.method in {"POST","PUT","PATCH"} and request.is_json:
        payload=request.get_json(silent=True)
        if isinstance(payload,dict):
            sanitized=_sanitize_value(payload)
            request._cached_json=(sanitized,sanitized)

# UX production conservata: correzione mobile, messaggio finale e Cabina di Regia.
FINAL_UX=r'''<script>
(function(){
 const obsoleteKeys=['aplsai_profiles','aplsai_current_profile','aplsai_client_session','aplsai_staff_session','aplsai_properties','aplsai_deals','aplsai_referrals','aplsai_documents'];
 try{obsoleteKeys.forEach(k=>localStorage.removeItem(k));}catch(_){}
 if(typeof window.saveClientProfile==='function') window.saveClientProfile=function(){return null;};
 const previousRender=window.render;
 if(typeof previousRender==='function') window.render=function(){const out=previousRender.apply(this,arguments);const p=document.getElementById('password');if(p){p.minLength=10;p.placeholder='Almeno 10 caratteri, lettere e numeri';}return out;};
 const previousNext=window.next;
 if(typeof previousNext==='function') window.next=async function(){try{if(typeof step!=='undefined'&&step===8){const p=document.getElementById('password');if(p&&p.value.length<10){if(typeof err==='function')err('La password deve avere almeno 10 caratteri, con lettere e numeri.');return;}}}catch(_){}return previousNext.apply(this,arguments);};
 const nativeScrollTo=window.scrollTo.bind(window);
 window.scrollTo=function(a,b){let top=null;if(typeof a==='object'&&a!==null)top=a.top;else if(typeof a==='number')top=(typeof b==='number'?b:a);const wizard=document.getElementById('wizardView');const visible=wizard&&wizard.style.display!=='none';if(window.innerWidth<=700&&visible&&top===0)return;return nativeScrollTo(a,b);};
 if(typeof window.choose==='function'){const old=window.choose;window.choose=async function(strategy,name){await old(strategy,name);const box=document.getElementById('strategyMsg');if(!box)return;box.setAttribute('aria-live','polite');if(!box.querySelector('.aplsai-final-actions'))box.insertAdjacentHTML('beforeend','<div class="aplsai-final-actions" style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;justify-content:center"><button class="primary" onclick="showClientArea()" style="min-height:48px">Vai alla mia Area Cliente</button><button class="secondary" onclick="goHome()" style="min-height:48px">Torna alla Home</button></div><p style="text-align:center;color:var(--muted);font-size:12px;margin:12px 0 0">La tua richiesta è stata salvata. APLSAI continuerà a lavorare sulle preferenze che hai indicato.</p>');setTimeout(function(){const target=box.querySelector('.success')||box;target.scrollIntoView({behavior:'smooth',block:'center'});},80);};}
 const labels={da_verificare:'Da verificare',mutuo_da_richiedere:'Mutuo da richiedere',pre_delibera:'Pre-delibera',mutuo_deliberato:'Mutuo deliberato',capitale_dichiarato:'Capitale dichiarato',capitale_verificato:'Capitale verificato'};
 function rank(r){const o=r.operation||{},due=o.next_action_due_at?new Date(o.next_action_due_at).getTime():null;if(due&&due<Date.now())return 0;if(o.financial_state==='capitale_verificato')return 1;if(o.financial_state==='mutuo_deliberato')return 2;if(o.financial_state==='pre_delibera'||o.financial_state==='capitale_dichiarato')return 3;if(o.phase==='Bloccato')return 4;return 5;}
 async function loadOps(){if(typeof api!=='function')return[];const d=await api('/api/staff/operations'),rows=d.results||[];rows.sort((a,b)=>rank(a)-rank(b));window.__aplsaiOperations=rows;return rows;}
 function opFor(id){return(window.__aplsaiOperations||[]).find(x=>String(x.client?.id)===String(id));}
 function command(rows){const grid=document.getElementById('todayGrid');if(!grid)return;const top=rows.slice(0,8);const card='<article class="area-card" id="aplsaiCommandCenter"><h3>Cabina di regia</h3>'+top.map(r=>{const c=r.client||{},o=r.operation||{},due=o.next_action_due_at?new Date(o.next_action_due_at):null,over=due&&due.getTime()<Date.now();return '<div class="list-row"><b>'+(c.name||'Cliente')+'</b><br><small>'+(o.phase||'Da qualificare')+' · '+(labels[o.financial_state]||'Da verificare')+'</small><br><strong>'+(o.next_action||'Definire prossima azione')+'</strong>'+(o.assigned_to?'<br><small>Responsabile: '+o.assigned_to+'</small>':'')+(due?'<br><small>'+(over?'⚠ Scaduta: ':'Scadenza: ')+due.toLocaleDateString('it-IT')+'</small>':'')+'</div>';}).join('')+'</article>';const old=document.getElementById('aplsaiCommandCenter');if(old)old.remove();grid.insertAdjacentHTML('afterbegin',card);}
 const rs=window.renderStaffServer;if(typeof rs==='function')window.renderStaffServer=async function(){const out=await rs.apply(this,arguments);try{command(await loadOps());}catch(_){}return out;};
 const oc=window.openServerClient;if(typeof oc==='function')window.openServerClient=function(id){oc(id);const row=opFor(id),box=document.getElementById('staffClientDetail');if(!row||!box)return;const o=row.operation||{},due=o.next_action_due_at?new Date(o.next_action_due_at).toLocaleDateString('it-IT'):'—';box.insertAdjacentHTML('beforeend','<div class="sum"><b>Fase pratica</b>'+(o.phase||'—')+'</div><div class="sum"><b>Prontezza finanziaria</b>'+(labels[o.financial_state]||'Da verificare')+'</div><div class="sum"><b>Prossima azione</b>'+(o.next_action||'—')+'</div><div class="sum"><b>Scadenza</b>'+due+'</div><div class="sum"><b>Responsabile</b>'+(o.assigned_to||'Da assegnare')+'</div>');};
})();
</script>'''

@app.after_request
def aplsai_final_ux(response):
    if response.content_type and response.content_type.startswith('text/html'):
        html=response.get_data(as_text=True)
        if '</body>' in html and 'aplsai-final-actions' not in html:
            html=html.replace('</body>',FINAL_UX+'\n<script src="/static/staff_operations_edit.js"></script>\n</body>')
            response.set_data(html);response.headers['Content-Length']=str(len(response.get_data()))
    return response
