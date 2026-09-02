# APLSAI HOME — Strategia Migrazioni Database V1

## Obiettivo
Passare da `db.create_all()` a una gestione versionata e reversibile dello schema prima che APLSAI contenga clienti reali.

## Perché è necessario
`db.create_all()` è utile nel prototipo per creare tabelle mancanti, ma non gestisce in modo affidabile modifiche successive come rinomina/rimozione colonne, trasformazioni dati, vincoli nuovi o rollback. Con dati reali ogni cambiamento di schema deve essere tracciato.

## Strategia scelta
Usare Alembic/Flask-Migrate come sistema ufficiale di migrazione, mantenendo SQLAlchemy come modello applicativo.

Flusso previsto per ogni modifica dati:
1. modificare i modelli SQLAlchemy;
2. generare una revisione di migrazione;
3. revisionare manualmente lo script generato;
4. eseguire backup/snapshot quando il cambiamento è rilevante;
5. applicare la migrazione in ambiente di test/staging;
6. eseguire smoke test;
7. applicare in produzione;
8. verificare salute applicazione e dati;
9. conservare la revisione nel repository.

## Regola produzione
Nessuna migrazione distruttiva deve essere eseguita automaticamente all'avvio dell'applicazione. Le migrazioni devono essere un passaggio di deploy esplicito e verificabile.

## Fase di transizione
Finché non è attivo il sistema versionato:
- `db.create_all()` può restare solo per compatibilità con il prototipo;
- evitare modifiche distruttive alle tabelle esistenti;
- preferire nuove tabelle/colonne opzionali;
- documentare ogni modifica schema;
- non introdurre dati clienti reali che dipendano da strutture non migrate in modo controllato.

## Prima migrazione baseline
La baseline dovrà rappresentare almeno le entità attuali:
- User;
- ClientProfile;
- Update;
- Property;
- Deal;
- Referral;
- Document;
- eventuali nuove entità operative/audit effettivamente presenti nel modello al momento della baseline.

Prima di generare la baseline occorre confrontare lo schema reale PostgreSQL con i modelli del repository per evitare che la cronologia delle migrazioni descriva una situazione diversa dalla produzione.

## Backup
Prima della beta reale definire:
- frequenza backup;
- retention;
- procedura di restore testata;
- responsabile del restore;
- tempo obiettivo di ripristino;
- verifica periodica che il backup sia realmente recuperabile.

Un backup non testato non viene considerato un controllo sufficiente.

## Gate
La voce “migrazioni database” è verde soltanto quando:
- Alembic/Flask-Migrate è configurato;
- esiste una baseline coerente con PostgreSQL;
- almeno una migrazione di prova è stata applicata in ambiente non produttivo;
- è documentata la procedura di rollback/restore;
- il deploy non dipende più da `db.create_all()` per evolvere lo schema.
