# Sentinel — AI roadmap (446–545)

Stavy: `[ ]` nový · `[A]` schváleno · `[X]` hotovo · `[N]` zamítnuto

Navazuje na dokončenou sekci 426–435. Zaměření: **jak AI pracuje, hledá problémy,
chápe souvislosti a řeší je.** Kontext architektury: Hailo NPU (qwen2.5-coder:1.5b)
+ CPU ollama fallback, ChromaDB RAG, `ai_evals.py`, autofix se safety klasifikátorem,
allowed_commands, DRY-RUN remediace, per-user chat paměť, token tracking.

Priorita: 🔴 vysoká (řeší dnešní bolest) · 🟡 střední · 🟢 nice-to-have

---

## Stav k 2026-08-03 (v2026.08.001)

**Hotovo 80 ze 100, včetně všech 19 🔴 položek.** 1050 testů, 25 nových modulů.

Zbývá 20 (🟡/🟢):

| Skupina | Položky | Blokuje |
|---|---|---|
| Čeká na provozní data | 528, 530–540 | `fix_attempts` má 0 záznamů — dnes by měřily prázdno |
| Vyžaduje cizí rozhraní | 452, 478, 483, 484, 501 | systemd závislosti, PBS API, SMART z agentů, Ansible |
| Frontend / integrace | 457, 460, 464, 524, 531 | HA senzory, vazba na SLO, vizualizace, streamování |

**Pozn. k 451/458/504:** vyřešeno jinak, než zadání předpokládalo — CDP/LLDP
data v instalaci nejsou, takže se závislosti odvozují ze sdíleného jádra
a souběžných výpadků (viz `dependencies.py`).

**Pozn.:** položky „čeká na provozní data" nemá smysl psát dřív, než bude co měřit —
jinak by se ladily proti prázdné množině.

---

## A. Root cause & souvislosti (446–465)

- [X] 446 🔴 **Incident grouping napříč hosty** — HOTOVO: analytics.group_incidents + GET /api/incidents — issues ze stejného časového okna (±2 min) na různých hostech sloučit do jednoho "incidentu" s vlastním ID; AI dostane celou skupinu místo izolovaných alertů
- [X] 447 🔴 **Kauzální řetěz místo seznamu** — AI má vrátit strukturu `{příčina → následek → následek}`, ne odstavec; UI vykreslí jako strom
- [X] 448 🔴 **Rozlišení příčina vs. symptom** — HOTOVO: POST /api/incidents/analyze (staví na 446 + ask_json) — u skupiny alertů označit, který je kořen (např. disk full → služba spadla → healthcheck selhal); symptomy sbalit pod příčinu
- [X] 449 🔴 **Korelace s telemetrií** — HOTOVO: get_telemetry_context + prompt v reanalyze + GET /api/issues/<k>/telemetry_context — k issue automaticky přiložit průběh CPU/RAM/disk/teploty ±30 min a nechat AI hledat souběh (dnes AI vidí jen text alertu)
- [X] 450 🔴 **Korelace se změnami** — spojit issue s tím, co se před ním změnilo: config_history, deploy (Gitea webhook), apt upgrade, restart služby
- [X] 451 🟡 **Topologická korelace** — využít `topology.py` (CDP/LLDP sousedi) k dohledání, zda výpadky sdílí switch/uplink/hypervizor
- [ ] 452 🟡 **Závislostní graf služeb** — z `depends_on` + systemd `After=/Requires=` (přes SSH) postavit graf a potlačit alerty následných služeb
- [X] 453 🟡 **Detekce společného jmenovatele** — u N alertů najít sdílený atribut (stejný balíček, kernel, mountpoint, VLAN) a nabídnout ho jako hypotézu
- [X] 454 🟡 **Časová osa incidentu** — chronologie ze všech zdrojů (logy, telemetrie, akce, notifikace) jako podklad pro AI i postmortem
- [X] 455 🟡 **"Co se změnilo od posledně"** — u opakujícího se issue diff proti minulému výskytu (jiná zpráva? jiný host? jiná hodnota?)
- [X] 456 🟡 **Cross-host pattern** — stejný alert na >30 % hostů = systémový problém, ne lokální; eskalovat jinak a nespamovat per-host
- [ ] 457 🟢 **Korelace s externími vlivy** — teplota v místnosti (HA senzory) vs. throttling; výpadek proudu vs. restart hostů
- [X] 458 🟡 **Blast radius** — AI odhadne, koho ještě problém zasáhne (závislé služby, uživatelé) a to řídí prioritu
- [X] 459 🟡 **Detekce kaskád** — rozpoznat lavinu (1 příčina → 20 alertů do 60 s) a poslat JEDNU notifikaci se souhrnem
- [ ] 460 🟢 **Korelace s SLO** — spojit issue s dopadem na error budget (404) a podle toho řadit
- [X] 461 🟡 **Hypotézy s pravděpodobností** — místo jedné odpovědi vrátit 2–3 hypotézy s odhadem jistoty a návrhem, čím je ověřit
- [X] 462 🔴 **Diagnostický plán** — HOTOVO: diagnostics.py katalog + POST /api/issues/<k>/diagnose{,/run} — AI navrhne posloupnost read-only příkazů k potvrzení hypotézy; spustí se jedním kliknutím a výsledek se vrátí modelu
- [X] 463 🟡 **Iterativní vyšetřování** — smyčka hypotéza → diagnostika → vyhodnocení → další krok (max N kol, s rozpočtem tokenů)
- [ ] 464 🟢 **Graf incidentu v UI** — vizualizace vztahů mezi issues (příčina/následek/duplicita)
- [X] 465 🟡 **Zpětná korelace při vyřešení** — když issue zmizí, ověřit, zda zmizely i navázané, a potvrdit tím správnost hypotézy

## B. Hledání problémů & prevence (466–485)

- [X] 466 🔴 **AI čte nezachycené logy** — periodicky nechat model projít vzorek řádků, které NEmatchnul žádný detektor, a navrhnout nové patterny (endpoint `/api/patterns/suggest` existuje, ale nemá volající — viz bug)
- [X] 467 🔴 **Detekce tiché degradace** — pomalý růst latence/chyb, který nepřekročí práh, ale trend je jasný; AI hlásí dřív než threshold
- [X] 468 🔴 **Chybějící signál** — alert na to, co PŘESTALO chodit (log se přestal plnit, metrika zmizela, cron nedoběhl) — dnes se detekuje jen přítomnost problému
- [X] 469 🟡 **Baseline profil hosta** — AI si drží popis "jak vypadá normální den" per host a hlásí odchylky od profilu, ne od σ
- [X] 470 🟡 **Sezónnost nad rámec 397** — kromě po-pá/víkend i denní doba, konec měsíce, backup okna
- [X] 471 🔴 **Prediktivní kapacita s AI kontextem** — k lineární regresi (`/api/predictions/capacity`) přidat vysvětlení, co růst způsobuje, a doporučení
- [X] 472 🟡 **Detekce konfiguračního driftu** — porovnat config/balíčky/kernel napříč podobnými hosty a hlásit odchylky
- [X] 473 🟡 **AI audit bezpečnostních logů** — vzory v auth.log/fail2ban, které jednotlivě neprojdou prahem (pomalý brute-force, distribuovaný sken)
- [X] 474 🔴 **Proaktivní kontrola zdraví** — týdenní AI průchod stavem infrastruktury s otázkou „co se pravděpodobně pokazí příště"
- [X] 475 🟡 **Detekce flappingu s příčinou** — `/api/analytics/flapping` říká CO flapuje; AI má říct PROČ
- [X] 476 🟡 **Anomálie ve vztazích metrik** — CPU roste, ale requests ne; disk I/O bez růstu dat — porušení očekávaných korelací
- [X] 477 🟢 **Detekce zombie zdrojů** — služby/kontejnery/VM, které běží a nikdo je nepoužívá (žádný provoz, žádné logy)
- [ ] 478 🟡 **Kontrola konzistence záloh** — AI ověří, že zálohy reálně běží a rostou (PBS), ne jen že job skončil OK
- [X] 479 🟡 **Certifikáty a expirace v kontextu** — kromě data expirace i kdo cert používá a co spadne, když vyprší
- [X] 480 🔴 **Rozpoznání falešných poplachů** — AI označí alerty, které historicky vždy samy zmizely, a navrhne úpravu prahu/patternu místo notifikace
- [X] 481 🟡 **Detekce chybějícího monitoringu** — které hosty/služby nikdo nesleduje (běží, ale nemá agenta ani detektor)
- [X] 482 🟢 **Analýza logů po restartu** — po každém rebootu nechat AI porovnat, zda vše naběhlo jako minule
- [ ] 483 🟡 **Detekce hardware degradace** — SMART, teploty, ECC chyby → trend a odhad zbývající životnosti (dnes je jen prahový alert)
- [ ] 484 🟡 **Analýza dopadu aktualizací** — po apt upgrade porovnat chování před/po a hlásit regrese
- [X] 485 🟢 **Kontrola dokumentace vs. realita** — AI porovná runbooky/wiki se skutečným stavem a hlásí zastaralé postupy

## C. Řešení & remediace (486–505)

- [X] 486 🔴 **Ověření, že oprava fungovala** — po remediaci AI zkontroluje, zda problém opravdu zmizel (dnes se jen přepne na `validating`)
- [X] 487 🔴 **Vysvětlení odmítnutí** — když safety klasifikátor/allowlist zablokuje příkaz, AI vysvětlí proč a navrhne povolenou alternativu
- [X] 488 🔴 **Postupná remediace** — nejdřív nejmenší zásah (restart služby), teprve při neúspěchu větší; ne rovnou reboot
- [X] 489 🟡 **Rollback plán** — ke každému návrhu i postup, jak změnu vrátit, pokud nepomůže
- [X] 490 🔴 **Návrh pravidla do allowlistu** — když AI opakovaně navrhuje stejný bezpečný příkaz, nabídnout jeho přidání (s diffem sudoers dopadu)
- [X] 491 🟡 **Odhad rizika v kontextu** — riziko `systemctl restart` závisí na tom, co ta služba dělá; AI zohlední kritičnost hosta
- [X] 492 🟡 **Dry-run diff** — u příkazů, které to umí (`apt -s`, `mount --fake`), ukázat, co by se stalo, ještě před schválením
- [X] 493 🔴 **Učení z ručních zásahů** — když admin problém vyřeší přes SSH sám, AI z historie příkazů odvodí postup a nabídne ho příště
- [X] 494 🟡 **Runbook generátor z incidentu** — z vyřešeného incidentu vygenerovat runbook a navázat na typ issue (tabulka `runbooks` existuje)
- [X] 495 🟡 **Odhad doby řešení** — na základě historie podobných issues predikovat, jak dlouho to zabere
- [X] 496 🟡 **Návrh preventivního opatření** — po vyřešení: co udělat, aby se to nestalo znovu (cron, logrotate, alert, kvóta)
- [X] 497 🟢 **Batch remediace** — stejný problém na N hostech vyřešit jedním schváleným plánem místo N kliknutí
- [X] 498 🟡 **Kontrola maintenance okna** — AI nenavrhne restart produkce v pracovní době, pokud problém není kritický
- [X] 499 🔴 **Eskalace s kontextem** — když AI neví, sestavit shrnutí pro člověka: co zkusila, co vyloučila, co doporučuje ověřit
- [X] 500 🟡 **Rozpoznání "neřešitelného"** — odlišit problém vyžadující fyzický zásah (výměna disku) a nenabízet SSH příkazy
- [ ] 501 🟢 **Koordinace s Ansible** — u opakovaného problému navrhnout trvalou opravu jako Ansible task, ne jednorázový příkaz
- [X] 502 🟡 **Prioritizace fronty práce** — AI seřadí otevřené issues podle dopadu × jistoty řešení a navrhne, čím začít
- [X] 503 🟡 **Detekce protichůdných akcí** — varovat, když by nová akce zrušila předchozí (restart služby, kterou někdo právě maskoval)
- [X] 504 🟢 **Simulace dopadu** — „co se stane, když tenhle host vypnu" na základě topologie a závislostí
- [X] 505 🔴 **Auto-remediace s postupným rozšiřováním důvěry** — příkaz, který 10× uspěl bez následného problému, navrhnout k povýšení na `auto_execute`

## D. Kvalita odpovědí, kontext & RAG (506–525)

- [X] 506 🔴 **Strukturovaný výstup místo textu** — HOTOVO (41876f8): extract_json (párování závorek) + ask_json s retry — přechod na JSON schema pro analýzy (dnes se parsuje volný text regexem a `_ai_reply_ok` čichá k prefixům)
- [X] 507 🔴 **execute_ollama vrací (ok, text)** — HOTOVO (7f15a72): AIResult(str) s .ok/.error, zpětně kompatibilní — místo chybové hlášky jako obsahu; odstraní prefix-sniffing napříč kódem *(známý accepted-risk)*
- [X] 508 🔴 **Kontextové okno podle úlohy** — krátký prompt pro klasifikaci severity, velký pro korelaci; dnes se posílá stejně velký kontext
- [X] 509 🟡 **Komprese kontextu** — před odesláním zkrátit opakující se log řádky (`... 47× stejný řádek`) místo ořezu na N znaků
- [X] 510 🔴 **RAG relevance filtr** — zahodit chunky pod prahem podobnosti (dnes se vrací top-N i když nesouvisí a model se jimi nechá zmást)
- [X] 511 🟡 **Hybridní vyhledávání** — kombinovat vektory s klíčovými slovy (hostname, kód chyby); dnes je fallback jen textový
- [X] 512 🟡 **Citace zdroje v odpovědi** — u AI odpovědi ukázat, ze kterého KB chunku/incidentu čerpá
- [X] 513 🟡 **RAG čistota** — deduplikace a expirace naučených chunků (`learned_kb.txt` roste bez limitu)
- [X] 514 🟡 **Chunking podle struktury** — dělit KB podle sekcí, ne po pevných blocích
- [X] 515 🟢 **Reranking** — druhý průchod nad top-20 pro lepší pořadí
- [X] 516 🔴 **Detekce halucinace** — ověřit, že hostnamy/služby/cesty v odpovědi reálně existují v DB; jinak označit
- [X] 517 🟡 **Odmítnutí bez dat** — model má říct „nevím, chybí mi X" místo pravděpodobné smyšlenky (eval 434 to už částečně testuje)
- [X] 518 🟡 **Konzistence napříč dotazy** — stejná otázka nemá dávat protichůdné odpovědi; cache + kontrola
- [X] 519 🟡 **Jazyk odpovědi dle uživatele** — dnes prompty míchají češtinu a angličtinu podle místa v kódu
- [X] 520 🟡 **Prompt verzování** — prompty v `PROMPTS`/prompt_library verzovat a měřit dopad změny přes eval suite
- [X] 521 🟢 **Few-shot z reálných incidentů** — do promptu přidat 2–3 vyřešené příklady ze stejné kategorie
- [X] 522 🟡 **Routing podle složitosti** — triviální klasifikace na malý rychlý model, korelace na velký (fallback chain 426 rozšířit o volbu dle úlohy)
- [X] 523 🟡 **Rozpočet tokenů per úloha** — limit a měření (435 sbírá data, chybí strop)
- [ ] 524 🟢 **Streamování dlouhých analýz** — postmortem/digest streamovat do UI, ne čekat na celek
- [X] 525 🟡 **Cache odpovědí** — stejný alert do X minut neanalyzovat znovu (šetří NPU i čas)

## E. Učení, zpětná vazba & evaluace (526–545)

- [X] 526 🔴 **Palec nahoru/dolů u AI odpovědi** — sbírat hodnocení a ukládat s kontextem; bez zpětné vazby se kvalita neměří
- [X] 527 🔴 **Učení z odmítnutých návrhů** — když admin autofix zamítne, zaznamenat proč a nenabízet totéž znovu
- [ ] 528 🟡 **Sledování úspěšnosti návrhů** — poměr „návrh → provedeno → problém zmizel" per typ issue
- [X] 529 🔴 **Eval suite z reálných incidentů** — generovat testy z vyřešených incidentů, ne jen 6 ručních (434)
- [ ] 530 🟡 **Regresní brána při změně modelu** — nedovolit přepnutí modelu, pokud skóre klesne pod baseline (dnes 5/6)
- [ ] 531 🟡 **A/B porovnání modelů** — pustit stejný dotaz přes 2 modely a porovnat (benchmark UI už umí měřit rychlost, chybí kvalita)
- [ ] 532 🟡 **Kalibrace confidence** — porovnat deklarovanou jistotu (429) se skutečnou úspěšností a korigovat
- [ ] 533 🟡 **Detekce driftu kvality** — sledovat skóre evalů v čase a hlásit zhoršení
- [X] 534 🟢 **Anotace pro fine-tuning** — sbírat dvojice (incident → správné řešení) v exportovatelném formátu
- [ ] 535 🟡 **Metrika falešných poplachů AI** — kolik AI-generovaných issues bylo označeno jako FP
- [ ] 536 🟡 **Srovnání AI vs. člověk** — u incidentů řešených ručně porovnat, zda AI navrhla totéž
- [ ] 537 🟢 **Kvalita per kategorie** — skóre zvlášť pro disk/síť/služby/bezpečnost, ať je vidět slabina
- [ ] 538 🟡 **Auto-tuning prahů** — z historie FP/FN navrhnout lepší prahy detektorů
- [ ] 539 🟡 **Vysvětlitelnost** — u každé AI akce logovat, jaký kontext dostala (pro audit i ladění)
- [ ] 540 🟢 **Denní přehled kvality AI** — kolik dotazů, jaká úspěšnost, kolik tokenů, kde to selhalo
- [X] 541 🟡 **Detekce zacyklení** — AI navrhuje stále totéž bez efektu → zastavit a eskalovat
- [X] 542 🟢 **Sdílení znalostí mezi instancemi** — export/import naučené KB pro víc Sentinelů
- [X] 543 🟡 **Ochrana proti prompt injection z logů** — obsah logu je nedůvěryhodný vstup; oddělit ho od instrukcí a testovat evalem
- [X] 544 🟡 **Limit dopadu AI** — strop akcí za hodinu (AI nesmí spustit lavinu remediací)
- [X] 545 🔴 **Audit stopa AI rozhodnutí** — co model dostal, co vrátil, co se z toho vykonalo — dohledatelné zpětně

---

## Doporučené pořadí (první vlna)

Největší efekt na „AI reálně pomáhá řešit problémy":

1. **506 + 507** — strukturovaný výstup a `(ok, text)`; všechno ostatní na tom staví
2. **446 + 448 + 449** — seskupení incidentů, příčina vs. symptom, korelace s telemetrií
3. **462** — diagnostický plán (AI si sama dojde pro data místo hádání)
4. **486 + 499** — ověření opravy a smysluplná eskalace
5. **526 + 527** — zpětná vazba, bez ní se kvalita neposune
6. **516 + 543** — halucinace a prompt injection z logů (bezpečnostní minimum)

## Známé blokátory

- `/api/patterns/suggest` a `/api/analyze/auto_clusters` existují, ale **nemají volající v UI** (`_suggestPatterns`, `_autoClusterAnalyze` nejsou definované) — opravit před 466
- Hailo NPU nevrací `prompt_eval_count` → vstupní tokeny se neměří (435)
- Dlouhý prompt na RPi5 CPU trvá >90 s (`ai_timeout_seconds` = 180) — 508/509 tím dostávají výkonnostní smysl
