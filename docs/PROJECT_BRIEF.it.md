# Scheda di progetto: Imageability urbana e conoscenza geografica nei Vision-Language Models

**Istituzione:** Middlesex University London · **Data:** giugno 2026 · **Codebook:** v0.3.1
*(Versione canonica in inglese: `docs/PROJECT_BRIEF.md`. Questa è la versione italiana per il meeting.)*

---

## 1. Obiettivo

Studiare come i **Vision-Language Models (VLM)** riconoscano **città** e **quartieri** a
partire da immagini stradali (street-level), e *perché*, verificare se la riconoscibilità
sia guidata dalla **distintività fisica** della scena (imageability, secondo Kevin Lynch)
oppure dalla **visibilità culturale** del luogo (proxy della sua presenza nei dati di
addestramento del modello), e soprattutto dalla **loro interazione**.

**Domande di ricerca:** (1) accuratezza nell'identificazione della città; (2)
discriminazione tra quartieri della stessa città; (3) ruolo dei landmark/forma distintiva;
(4) i luoghi a maggiore imageability vengono riconosciuti meglio? (5) alcune regioni del
mondo sono sistematicamente più "visibili" ai modelli? (6) forma vs visibilità culturale vs
entrambe; (7) i VLM mostrano una cognizione geografica analoga alle mappe mentali umane?

## 2. Impianto concettuale (ciò che ne fa uno studio, non una demo)

- **Due costrutti, misurati *separatamente***, così da poter testare sia gli effetti
  principali sia la loro **interazione**. L'imageability è un **indice composito**
  (sotto-componenti di Lynch: landmark/nodo/percorso/margine/distretto + misure
  sull'immagine), con pesi da **apprendere da valutazioni umane**. La visibilità culturale
  resta un insieme di **predittori distinti e in competizione** (portata globale, prominenza
  locale, impronta visiva, fama dei landmark), *non* aggregati, perché la domanda è *quale*
  dimensione predice il riconoscimento.
- **Salienza fisica ≠ fama.** I landmark entrano nell'imageability solo per attributi fisici
  (altezza/impronta/tipo); la loro fama vive interamente nella visibilità culturale.
- **Frame spaziale uniforme.** "La città" = **estensione GHSL Urban Centre** (stessa regola
  di densità in tutto il mondo), non i confini amministrativi (non comparabili tra Paesi).
- **Campionamento stratificato.** N fisso = **200 punti/città**, allocazione uguale su **5
  strati di tessuto urbano** (centro storico / residenziale denso / commerciale / suburbano /
  periferico), così che le differenze di riconoscimento riflettano il *tipo di luogo* e non
  un bias di campionamento.
- **Nessun retrieval in inferenza.** Ai modelli si dà solo l'immagine, niente web/RAG, per
  misurare la conoscenza *interna* al modello. Versioni esatte dei modelli fissate.
- **Non-circolarità dell'encoder.** Ogni misura di distintività basata sull'immagine usa un
  encoder self-supervised congelato (es. DINO) *diverso* dai VLM in esame.
- **Riproducibilità.** Seed fissi; tutte le coordinate campionate + metadati archiviati;
  risposte grezze dei modelli separate dai punteggi derivati, così il ri-scoring non richiede
  mai di ri-eseguire l'inferenza.

## 3. Pipeline dei dati

```
città ─► QID Wikidata ─► centroidi ─► frame GHSL ─► classificatore strati di tessuto
   ─► campionamento punti riproducibile ─► snapping Street View ─► tabella points
   ─► [immagini ─► viste rettilinee ─► inferenza VLM ─► punteggi] (fase successiva)
```
| Fase | Stato |
|---|---|
| Frame di 50 città (bilanciato per regione) | ✅ |
| QID Wikidata, centroidi | ✅ 50/50 |
| Frame GHSL Urban Centre | ✅ 50/50 |
| Classificatore strati (uso del suolo OSM × centralità/densità) | ✅ costruito + validato |
| Campionamento Stage-A + snapping Street View | ✅ pipeline completa; **14 città campionate** |
| Restanti ~34 città | ⏳ meccanico (scaricare estratto OSM, eseguire il batch) |
| Immagini → viste → inferenza → punteggi | ⛔ fase successiva (1 decisione di design aperta) |

## 4. Struttura del repository

- **`codebook.yaml`**, unica fonte di verità: ogni variabile, entrambi i costrutti,
  confondenti, frame spaziale, disegno di campionamento, normalizzazione. Lo schema del DB e
  il codice sono *derivati* da esso. (`codebook.md` = versione leggibile.)
- **`cities_seed.csv`**, il frame di 50 città (8 macro-regioni bilanciate + 2 wildcard).
- **`schema/001_init.sql`**, schema PostgreSQL/PostGIS (22 tabelle; risposte grezze separate
  dai punteggi).
- **`ingest/`**, pipeline: sync della specifica, validazione, risoluzione QID, matching dei
  frame GHSL, campionatore riproducibile, classificatore degli strati, lettore OSM, snapping
  Street View, driver batch.
- **`tests/`**, 46 test unitari superati sulla logica deterministica.

## 5. Stato attuale (concreto)

- Database (PostgreSQL 18 + PostGIS): **50 città** con QID + centroide + frame GHSL.
- **14 città completamente campionate** nella tabella `points` (≈200 punti stratificati e
  agganciati a Street View ciascuna): amman, paris, accra, auckland, cape_town, colombo,
  dakar, johannesburg, lagos, nairobi, seoul, tunis, valparaiso, lima.
- Calibrazione validata su una città **sparsa** (Amman) e una **densa** (Paris).
- Lo snapping usa l'**endpoint metadata gratuito** (£0); le immagini non sono ancora scaricate.

## 6. Problemi incontrati e come sono stati risolti

| Problema | Soluzione |
|---|---|
| Confini amministrativi non comparabili tra Paesi | Adottata l'estensione morfologica **GHSL Urban Centre** (uniforme nel mondo). |
| **I Termini di Servizio di Google Street View vietano di archiviare le immagini** (si può conservare solo il `pano_id`) | Verificato sui ToS (non dato per scontato). Lo snapping usa l'endpoint **metadata gratuito**; la decisione sull'*archiviazione* delle immagini è rinviata (tenere solo i pano_id e riscaricare, oppure passare a **Mapillary**, che consente l'archiviazione). |
| **Nessuna copertura Street View ufficiale in Nord Africa**, cairo (Egitto) 1%, casablanca (Marocco) 0% | Verificato con sonde di copertura gratuite. **cairo → sostituita con Tunis**; **casablanca → sostituzione in sospeso**. Documentato come *gap di copertura correlato alla regione* (rilevante per la RQ5 e per il controllo `conf_sv_coverage`), non nascosto. |
| Ambiguità dei QID Wikidata (es. "Tunis" che risolve allo Stato Tunisia; città vs stati/università/film) | Il resolver filtra per **tipo di insediamento**, ordina per **sitelink**, preferisce il Paese corretto e rinuncia in caso di ambiguità invece di indovinare; il caso eccezionale (Tunis) è **fissato** con un QID verificato. |
| Estratti OSM con **territori oltre l'antimeridiano** (Nuova Zelanda): bounding box enorme che agganciava erroneamente città lontane dell'emisfero sud → dati errati | Il matching città→estratto ora aggiunge un **controllo sulle feature stradali**; i falsi match vengono respinti. Le righe errate sono state individuate ed eliminate. |
| Due strati (commerciale, storico) **sotto-rappresentati** con le soglie di default | Calibrato secondo la definizione stessa del codebook ("alta densità di negozi" → commerciale via densità di POI) + pool di candidati più ampio; gli strati genuinamente rari **registrano un deficit** invece di forzare i punti. |
| Città a bassa copertura (Tunis, 14% ufficiale) | Riempie comunque i 200 punti con oversampling maggiore; la copertura è registrata come valore di `conf_sv_coverage`. |

## 7. Decisioni aperte e rischi

- **Schema di presentazione in inferenza** (l'unica decisione di design aperta nel codebook):
  come presentare la cattura a 360° come viste rettilinee (N viste cardinali; tutte insieme
  vs sequenziali vs best-view). Non blocca la raccolta dati.
- **Sorgente/archiviazione immagini** (dovuta al vincolo dei ToS): Google solo `pano_id` +
  riscaricamento, vs Mapillary (archiviabile). Determina se ~10k immagini stanno su disco
  (~5–30 GB) o no.
- **Sostituzione di casablanca**, il Nord Africa è esaurito (solo la Tunisia ha copertura);
  si sonderà e sceglierà una candidata del Golfo/Levante.
- **La copertura come confondente regionale**, la disponibilità di Street View varia per
  regione; è un limite reale ma alimenta anche la RQ5 (va modellata, non ignorata).

## 8. Prossimi passi

1. Completare il campionamento Stage-A per le città restanti (scaricare gli estratti OSM,
   eseguire il batch).
2. Risolvere la sostituzione di casablanca e (opzionale) aggiungere la densità GHS-BUILT agli
   strati.
3. Chiudere la decisione sullo schema di presentazione e quella sulla sorgente delle immagini.
4. Acquisire le immagini → viste rettilinee → **inferenza VLM** (open-weight: Qwen-VL/LLaVA/
   InternVL; proprietari: GPT/Gemini/Claude; output JSON strutturato con un campo di
   ragionamento/cue).
5. **Scoring** (task città: errore geodetico, accuratezza@{25,200,750} km, accuratezza
   Paese/regione; task quartiere: match del confine corretto) → **analisi** (riconoscimento ~
   imageability × visibilità culturale + regione + controlli).

## 9. Stack tecnologico

PostgreSQL 18 + PostGIS · Python 3.14 (geopandas, shapely, pyogrio, rasterio) ·
GHS-UCDB R2024A (frame urbani) · OpenStreetMap via estratti Geofabrik `.osm.pbf` (driver GDAL)
· API Wikidata (identità + coordinate) · API metadata Google Street View (snapping/copertura)
· in seguito: un encoder congelato tipo DINO + i VLM in esame.

## 10. Letteratura di riferimento (selezione)

Il progetto si colloca all'intersezione tra cognizione urbana, scienza delle immagini
stradali, geolocalizzazione da immagine e bias nei modelli di visione. Fonti reali e
citabili, raggruppate per pilastro (verificare pagina/DOI esatti in un reference manager
prima della citazione formale).

**Leggibilità urbana e mappe cognitive, l'ancoraggio teorico**
- **Lynch, K. (1960). *The Image of the City*. MIT Press.**, Introduce l'*imageability* e i
  cinque elementi (landmark/nodo/percorso/margine/distretto); base concettuale del costrutto
  di imageability.

**Quantificare la percezione urbana dalle immagini stradali**
- **Salesses, Schechtner & Hidalgo (2013). "The Collaborative Image of the City." *PLoS ONE*.**
 , Il Place Pulse originale: valutazioni percettive crowdsourced di scene stradali; precedente
  per la validazione dell'imageability tramite giudizi umani.
- **Dubey, Naik, Parikh, Raskar & Hidalgo (2016). "Deep Learning the City…" *ECCV*.**, Place
  Pulse 2.0 (~110k immagini, 56 città) + CNN; modello metodologico per le misure di scena
  basate sull'immagine.
- **Li et al. (2015). "…modified green view index." *Urban Forestry & Urban Greening*.**,
  Metrica di verde/cielo (tipo Treepedia) da panorami; base della variabile `img_skyview_green`.

**Morfologia urbana e una definizione globale comparabile di "città"**
- **Boeing (2017). "OSMnx…" *Computers, Environment and Urban Systems*.**, Strumento/metodo per
  ricavare la struttura della rete stradale da OSM; alla base delle misure percorso/nodo.
- **Boeing (2019). "Urban Spatial Order: …Orientation… Entropy." *Applied Network Science*.**,
  Entropia di orientamento (griglia vs organico) su 100 città; direttamente la variabile
  `path_entropy`.
- **Florczyk et al. (2019). *GHS Urban Centre Database 2015* (GHS-UCDB), JRC** e **Dijkstra et
  al. (2020), Degree of Urbanisation.**, La definizione di città basata sulla densità
  (avallata dall'ONU) + il dataset di centri urbani usato come frame spaziale (perché GHSL e
  non i confini amministrativi).

**Geolocalizzazione da immagine, il compito, dai classici all'era CLIP**
- **Hays & Efros (2008). "IM2GPS…" *CVPR*.**, Lavoro fondativo sull'inferenza della posizione
  da una singola foto.
- **Weyand, Kostrikov & Philbin (2016). "PlaNet, Photo Geolocation with CNNs." *ECCV*.**,
  Imposta la geolocalizzazione globale come classificazione su geocelle.
- **Haas, Skreta, Alberti & Finn (2024). "PIGEON: Predicting Image Geolocations." *CVPR*
  (+ StreetCLIP, 2023).**, Stato dell'arte nella geolocalizzazione di immagini stradali su
  CLIP; il precedente tecnico più vicino, e StreetCLIP è un candidato encoder congelato.

**Conoscenza geografica, bias e privacy nei modelli (visione-)linguaggio**
- **"Granular Privacy Control for Geolocation with Vision Language Models." *EMNLP 2024*.**,
  Mostra che modelli tipo GPT-4V geolocalizzano le immagini; prova che i VLM possiedono la
  conoscenza geografica che indaghiamo.
- **"Assessing the Geolocation Capabilities… of Generative Vision-Language Models."
  *arXiv:2508.19967 (2025)*.**, Confronta 25 VLM sulla geolocalizzazione; motiva uno studio
  controllato come questo.
- **DeVries, Misra, Wang & van der Maaten (2019). "Does Object Recognition Work for Everyone?"
  *CVPR Workshops*.**, Documenta un bias di performance amero/eurocentrico per regione/reddito;
  il presupposto dietro la RQ5 e il costrutto di visibilità culturale.

**Strumenti metodologici**
- **Caron, Touvron, Misra et al. (2021). "…Self-Supervised Vision Transformers" (DINO). *ICCV*;
  Oquab et al. (2023). "DINOv2." *arXiv:2304.07193*.**, L'encoder self-supervised, generale e
  congelato, per la misura di distintività *non circolare* basata sull'immagine.
- **Schuhmann et al. (2022). "LAION-5B…" *NeurIPS Datasets & Benchmarks*.**, Il tipo di corpus
  immagine-testo da web che alimenta i VLM open; motiva l'uso della frequenza nelle
  caption/training come proxy di visibilità culturale.
