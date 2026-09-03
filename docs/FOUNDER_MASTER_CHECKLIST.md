# APLSAI HOME — Founder Master Checklist

## Scopo
Una sola pagina di controllo per non perdere passaggi tra società, prodotto, infrastruttura, privacy e Beta.

### 1. Società — BLOCCANTE
- [ ] società costituita;
- [ ] denominazione/oggetto sociale/codici attività validati;
- [ ] PEC, firma digitale, conto societario;
- [ ] valutazione startup innovativa completata;
- [ ] titolarità/licenza degli asset APLSAI formalizzata.

### 2. Proprietà e controllo — BLOCCANTE
- [ ] marchio/domìni sotto controllo societario;
- [ ] repository GitHub privato e sotto controllo societario;
- [ ] cloud/database/storage intestati o contrattualizzati correttamente;
- [ ] accessi Admin individuali;
- [ ] Partner senza diritti automatici sul progetto complessivo.

### 3. Software Beta V1
- [x] autenticazione e ruoli;
- [x] Cliente/Staff/Cabina di Regia;
- [x] Operatori e disattivazione;
- [x] Partner assegnati alle pratiche;
- [x] audit;
- [x] migrazioni versionate;
- [x] protezione documenti fail-closed;
- [x] Security Baseline;
- [x] test end-to-end Beta;
- [ ] storage privato reale integrato.

### 4. Produzione — BLOCCANTE
- [ ] servizio applicativo UE definitivo;
- [ ] PostgreSQL UE permanente;
- [ ] storage privato UE;
- [ ] backup + restore provato;
- [ ] credenziali/segreti ruotati e solo in environment;
- [ ] smoke test produzione;
- [ ] monitoraggio minimo attivo.

### 5. Privacy/legale — BLOCCANTE
- [ ] Titolare e contatti privacy definiti;
- [ ] informativa Cliente validata;
- [ ] condizioni servizio validate;
- [ ] accordi Operatore/Partner;
- [ ] ruoli fornitori e art. 28 dove applicabile;
- [ ] retention policy;
- [ ] procedura diritti interessati;
- [ ] procedura data breach;
- [ ] verifica trattamento dati/AI;
- [ ] revisione professionale finale.

### 6. Operatività
- [ ] primo Operatore formato;
- [ ] canale assistenza definito;
- [ ] Partner iniziali classificati per ruolo;
- [ ] tre pratiche simulate completate;
- [ ] procedura disattivazione/revoca provata;
- [ ] review giornaliera Cabina di Regia pronta.

### 7. Beta reale
- [ ] GO/NO-GO firmato internamente;
- [ ] numero massimo iniziale di clienti definito;
- [ ] primi clienti selezionati;
- [ ] priorità clienti finanziariamente pronti applicata;
- [ ] KPI Beta registrati;
- [ ] review settimanale prevista;
- [ ] nessuna campagna marketing massiva prima della stabilità operativa.

## Cose da NON fare
- non caricare documenti reali nello storage non privato;
- non aprire indiscriminatamente l'accesso Partner;
- non cancellare utenti per revocare accessi quando serve conservare storico/audit;
- non lasciare asset centrali dispersi tra account personali senza accordi;
- non scalare il marketing prima che il processo operativo sia stabile;
- non trattare output AI come sostituti automatici di verifiche professionali necessarie.

## Prossimo gate pratico
Quando si decide di sostenere i costi infrastrutturali: creare PostgreSQL permanente Frankfurt + ambiente applicativo UE + storage privato UE, eseguire il runbook di migrazione e chiudere i gate produzione.
