(function(){
  const phases=['Nuovo','Profilo completo','Da qualificare','Ricerca attiva','Opportunità individuata','Verifica','Proposta','Interesse confermato','Definizione','Contrattualizzazione','In lavorazione','Chiuso','In pausa','Bloccato','Non idoneo al momento'];
  const financial=[
    ['da_verificare','Da verificare'],
    ['mutuo_da_richiedere','Mutuo da richiedere'],
    ['pre_delibera','Pre-delibera'],
    ['mutuo_deliberato','Mutuo deliberato'],
    ['capitale_dichiarato','Capitale dichiarato'],
    ['capitale_verificato','Capitale verificato']
  ];
  function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function rowFor(id){return (window.__aplsaiOperations||[]).find(x=>String(x.client?.id)===String(id));}
  function dateInput(iso){if(!iso)return ''; const d=new Date(iso); if(Number.isNaN(d.getTime()))return ''; return d.toISOString().slice(0,10);}

  function appendEditor(id){
    const box=document.getElementById('staffClientDetail');
    const row=rowFor(id);
    if(!box||!row||box.querySelector('#aplsaiOperationEditor'))return;
    const o=row.operation||{};
    box.insertAdjacentHTML('beforeend',`
      <div id="aplsaiOperationEditor" class="area-card" style="margin-top:14px">
        <h3>Gestione pratica</h3>
        <label>Fase</label>
        <select id="opPhase">${phases.map(x=>`<option ${x===o.phase?'selected':''}>${esc(x)}</option>`).join('')}</select>
        <label>Prontezza finanziaria</label>
        <select id="opFinancial">${financial.map(([v,l])=>`<option value="${v}" ${v===o.financial_state?'selected':''}>${esc(l)}</option>`).join('')}</select>
        <label>Prossima azione</label>
        <input id="opNextAction" maxlength="255" value="${esc(o.next_action||'')}" placeholder="Es. Verificare documenti mutuo">
        <label>Scadenza</label>
        <input id="opDue" type="date" value="${dateInput(o.next_action_due_at)}">
        <label>Responsabile</label>
        <input id="opAssigned" maxlength="160" value="${esc(o.assigned_to||'')}" placeholder="Nome operatore">
        <label>Motivo blocco (solo se serve)</label>
        <textarea id="opBlocked" maxlength="500" rows="3">${esc(o.blocked_reason||'')}</textarea>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
          <button class="primary" id="opSaveBtn">Salva pratica</button>
        </div>
        <p id="opSaveMsg" aria-live="polite" style="margin-top:10px"></p>
      </div>`);
    const btn=document.getElementById('opSaveBtn');
    if(btn)btn.onclick=()=>saveOperation(id);
  }

  async function saveOperation(id){
    const msg=document.getElementById('opSaveMsg');
    const due=document.getElementById('opDue')?.value||'';
    const payload={
      phase:document.getElementById('opPhase')?.value,
      financial_state:document.getElementById('opFinancial')?.value,
      next_action:(document.getElementById('opNextAction')?.value||'').trim(),
      next_action_due_at:due?due+'T12:00:00Z':null,
      assigned_to:(document.getElementById('opAssigned')?.value||'').trim(),
      blocked_reason:(document.getElementById('opBlocked')?.value||'').trim()
    };
    try{
      if(msg)msg.textContent='Salvataggio…';
      await api('/api/staff/client/'+encodeURIComponent(id)+'/operation',{method:'POST',body:JSON.stringify(payload)});
      if(typeof window.renderStaffServer==='function')await window.renderStaffServer();
      if(typeof window.openServerClient==='function')window.openServerClient(Number(id));
      if(msg)msg.textContent='Pratica aggiornata.';
    }catch(e){
      if(msg)msg.textContent=e.message||'Errore durante il salvataggio.';
    }
  }
  window.saveAplsaiOperation=saveOperation;

  function install(){
    if(typeof window.openServerClient!=='function'||window.__aplsaiOperationEditorInstalled)return false;
    window.__aplsaiOperationEditorInstalled=true;
    const prev=window.openServerClient;
    window.openServerClient=function(id){
      prev(id);
      setTimeout(()=>appendEditor(id),0);
    };
    return true;
  }
  if(!install()){
    let tries=0; const timer=setInterval(()=>{tries++; if(install()||tries>40)clearInterval(timer);},100);
  }
})();
