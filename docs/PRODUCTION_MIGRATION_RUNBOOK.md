# APLSAI HOME — Production Migration Runbook

## Obiettivo
Migrare la Beta V1 dall'infrastruttura temporanea Oregon a una produzione europea senza perdita dati e con rollback possibile.

## Stato di partenza
- Applicazione Render attuale: Oregon.
- PostgreSQL attuale: Render Free, Oregon, PostgreSQL 16.
- Codice Beta V1: test Security Baseline + end-to-end.
- Documenti privati: accesso applicativo protetto; storage fisico privato ancora da attivare.

## Regole di sicurezza
1. Non eliminare o modificare il database sorgente durante la preparazione.
2. Nessun cut-over senza backup verificato.
3. Nessun documento reale su URL pubblico.
4. Credenziali solo tramite variabili d'ambiente.
5. Il database Oregon resta disponibile durante la finestra di rollback.

## Fase A — Preparazione senza impatto
- [x] Migrazioni DB versionate predisposte.
- [x] Test automatici sicurezza.
- [x] Test Beta end-to-end.
- [x] Protezione Partner/documenti fail-closed.
- [ ] Repository GitHub privato.
- [ ] Nuovo PostgreSQL permanente Frankfurt.
- [ ] Nuovo servizio web Frankfurt.
- [ ] Storage privato UE.

## Fase B — Backup e prova di ripristino
1. Creare backup consistente del DB sorgente.
2. Calcolare/verificare dimensione e timestamp backup.
3. Ripristinare su DB europeo non collegato al traffico.
4. Confrontare almeno: numero utenti, profili cliente, documenti, operazioni, audit, operatori/partner e assegnazioni.
5. Eseguire migrazioni versionate sul DB destinazione.
6. Eseguire smoke test applicativo sulla destinazione.

## Fase C — Cut-over
1. Definire breve finestra di manutenzione.
2. Bloccare temporaneamente nuove scritture sul vecchio ambiente.
3. Eseguire backup finale/delta.
4. Ripristinare/allineare DB Frankfurt.
5. Impostare DATABASE_URL del servizio europeo.
6. Impostare SECRET_KEY e credenziali esclusivamente come environment variables.
7. Configurare PRIVATE_DOCUMENT_HOSTS solo dopo attivazione storage privato.
8. Avviare il servizio europeo.

## Fase D — Verifica prima dell'apertura
- [ ] Health check HTTP.
- [ ] Registrazione/Login Cliente.
- [ ] Login Admin e Operatore.
- [ ] Cabina di Regia e aggiornamento pratica.
- [ ] Creazione/login Partner.
- [ ] Isolamento Partner tra pratiche diverse.
- [ ] Accesso documenti privati.
- [ ] Audit eventi critici.
- [ ] Logout/sessioni/account disattivati.
- [ ] Test mobile essenziale.

## Rollback
Se uno dei controlli critici fallisce:
1. Non cancellare il nuovo ambiente.
2. Riportare il traffico al servizio precedente.
3. Riabilitare le scritture sul DB Oregon solo dopo aver verificato che non esistano scritture concorrenti sul nuovo DB.
4. Analizzare il problema e ripetere il cut-over.

## Criterio GO Beta reale
La Beta con dati reali può partire soltanto quando sono contemporaneamente veri:
- repository privato;
- servizio e database UE permanenti;
- backup + restore provati;
- storage documenti privato UE;
- Security Baseline verde;
- smoke test produzione verde;
- privacy/GDPR e informative operative pronte.
