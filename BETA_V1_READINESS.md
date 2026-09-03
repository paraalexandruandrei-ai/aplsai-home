# APLSAI HOME — Beta V1 Readiness

Aggiornato: 2026-09-03

## Stato software

- [x] Percorso Cliente e registrazione
- [x] Area Staff / Cabina di Regia
- [x] RBAC Admin / Operatore / Partner / Cliente
- [x] Gestione Operatori con attivazione/disattivazione
- [x] Audit eventi operativi
- [x] Migrazione versionata per `User.active`
- [x] Account Partner con assegnazione obbligatoria a pratica
- [x] Isolamento Partner: solo pratiche assegnate
- [x] Protezione documenti Partner con redazione URL grezzi
- [x] Test sicurezza documenti
- [x] Test end-to-end Beta V1 Cliente → Staff → Partner → Documento
- [x] Security Baseline automatico in GitHub Actions

## Bloccanti prima di usare clienti/documenti reali

- [ ] Collegare storage privato reale per documenti
- [ ] Configurare host/storage privato autorizzato
- [ ] Portare servizio, database e storage in regione UE coerente
- [ ] Verificare strategia backup e ripristino database
- [ ] Verificare deploy automatico Render: il servizio dichiara auto-deploy attivo, ma il deploy LIVE osservato è ancora sul commit `498f6b2`
- [ ] Eseguire smoke test sulla versione LIVE dopo allineamento deploy
- [ ] Verificare configurazione produzione: `SECRET_KEY`, credenziali Admin, database persistente e variabili sensibili
- [ ] Privacy/GDPR e documentazione legale prima dell'apertura a utenti reali

## Regola di rilascio

Una versione può essere considerata Beta V1 pronta per utenti reali solo se:

1. Security Baseline verde.
2. Test end-to-end verde.
3. Deploy LIVE allineato all'ultimo commit approvato.
4. Storage documenti privato attivo e testato.
5. Backup e ripristino verificati.
6. Ambiente UE definitivo predisposto.
7. Documentazione privacy/legale approvata.

## Nota infrastrutturale

Il codice applicativo non deve mai esporre URL grezzi dei documenti a Partner esterni. L'accesso deve restare mediato dal backend, con controllo ruolo, account attivo, assegnazione pratica e audit dell'accesso o del diniego.
