# APLSAI HOME — Archivio Documenti Privato V1

## Obiettivo
Eliminare, prima della beta reale, l'uso di link pubblici permanenti per documenti cliente o pratica.

## Principio
Il database applicativo conserva metadati e autorizzazioni; il file risiede in uno storage privato. Nessun documento sensibile deve essere incluso nel repository GitHub o servito come file pubblico statico dall'applicazione.

## Modello documento
Campi consigliati:
- id documento;
- client_id/practice_id;
- titolo;
- categoria;
- storage_key interno non pubblico;
- nome originale ripulito;
- tipo MIME verificato;
- dimensione;
- checksum SHA-256;
- caricato_da;
- created_at;
- stato (attivo/archiviato/eliminato);
- eventuale scadenza/retention.

Non memorizzare token di accesso permanenti nel database.

## Upload
1. sessione valida;
2. controllo ruolo e autorizzazione sulla pratica;
3. limiti dimensione;
4. allowlist dei tipi ammessi (inizialmente PDF e immagini/documenti realmente necessari);
5. nome file generato dal server, non fidarsi del nome inviato dal browser;
6. storage privato;
7. registrazione metadati e audit.

## Download/visualizzazione
1. richiesta autenticata;
2. controllo ruolo;
3. controllo autorizzazione sul documento specifico;
4. generazione URL temporaneo firmato oppure streaming controllato dal backend;
5. audit dell'accesso quando opportuno.

Un partner vede solo i documenti della pratica assegnata e soltanto quelli necessari al suo incarico.

## Protezioni
- HTTPS obbligatorio;
- bucket/container non pubblico;
- URL firmati a vita breve;
- nessun indice pubblico;
- antivirus/malware scanning da introdurre prima di accettare upload non controllati su scala;
- Content-Disposition sicuro;
- non eseguire file caricati;
- backup coerente con la retention;
- cancellazione logica + procedura di cancellazione fisica.

## Dati finanziari
Documenti finanziari dettagliati non devono essere caricati per default. Se una verifica richiede documentazione, deve essere raccolta solo quando necessaria, con accesso ristretto e retention specifica. Nel profilo operativo resta soltanto lo stato sintetico di prontezza finanziaria.

## Scelta provider
Il codice applicativo deve usare un'interfaccia astratta di storage, così APLSAI può utilizzare un provider compatibile S3/object storage senza legare il metodo proprietario a un singolo fornitore.

Variabili segrete previste, solo lato server:
- STORAGE_ENDPOINT;
- STORAGE_BUCKET;
- STORAGE_ACCESS_KEY;
- STORAGE_SECRET_KEY;
- STORAGE_REGION (se necessaria).

Queste variabili non devono mai entrare in GitHub.

## Gate di attivazione
Fino a quando lo storage privato non è configurato e testato, la funzione documenti deve essere considerata dimostrativa e non deve essere usata per documenti sensibili di clienti reali.

## Test obbligatori
- cliente A non può ottenere documento cliente B;
- partner A non può ottenere documenti di pratica non assegnata;
- URL temporaneo scade;
- storage key non è direttamente navigabile;
- file oltre limite viene respinto;
- tipo non ammesso viene respinto;
- accesso senza sessione viene respinto;
- cancellazione rende il documento non accessibile.
