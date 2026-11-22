# AI ekosistem — finansijski pregled i eliminacije

Decision cutoff: **2026-11-20T21:30:00+00:00**. Granica: **18 kompanije/grupe** iz datiranog registra.
Ciljni period grupnog obračuna: **2026-01-01 – 2026-09-30**.
Računovodstveni obuhvat izabranih kompanija: **18 jedinica**; kompletna kontrolna mapa još zahteva pregled.




**Grupni spoljni prihod: unavailable; neto novac: unavailable (milijarde USD). Dobit: unavailable.**
SoftBank Group, MGX i BlackRock/GIP su izvan operativne grupe. Njihove potvrđene uplate predstavljale bi spoljno finansiranje.
Registar ugovora ne dokazuje izvršene uplate. Prazan transakcioni registar ne znači nula stvarnog prometa.
Ovo je analitičko objedinjavanje nezavisnih kompanija, bez tvrdnje da postoji zajednička kontrola ili nepravilno knjiženje.

## Filter veličine

U glavnom izveštaju su samo operativni emitenti sa vrednošću ≥50 milijardi USD. Nije korišćen prihod, EV, backlog ili vrednost ugovora.
OpenAI je uključen na osnovu posebno označenog primarnog privatnog funding proxyja iz 31.03.2026. To nije berzanska kapitalizacija 20.11. ili potvrda najnovije privatne runde.
Javne kapitalizacije su vendor snapshot datiran na zatvaranje 20.11, preuzet naknadno. Tadašnja dostupnost vendor objave i share-count vintage nisu nezavisno arhivirani. Za azijske valute korišćen je prethodni završeni FX dan 19.11, naveden u audit JSON-u.
Vrednosti, osnove i datumi: market-values.csv. Isključeni i razlozi: size-exclusions.csv, zasebno od glavne finansijske tabele.

## Objavljene finansije po kompaniji

Iznosi su u milijardama USD. Svaki red ima svoj TTM period; različiti fiskalni kalendari se ne sabiraju.
Prihodi i CFO uključuju interne poslove sa drugim članicama i poslovanje koje nije AI. CFO minus cash PP&E nije grupni FCF,
ne uključuje automatski finance lease additions, otplate lease glavnice ili sve kategorije ulaganja. Cash nije potvrđena raspoloživa likvidnost.
*Vrednost kapitala je tržišna kapitalizacija na 20.11.2026; OpenAI je posebno označeni privatni funding proxy iz 31.03.2026. Sve vrednosti u tabeli su milijarde USD.

| Kompanija | Vrednost kapitala* | TTM od–do | Prihod | CFO | Cash PP&E | CFO−PP&E | CFO/PP&E |
|---|---:|---|---:|---:|---:|---:|---:|
| NVIDIA | 3,030.000 | 2025-07-28 – 2026-07-26 | unavailable | 134.360 | unavailable | unavailable | unavailable |
| AMD | 702.390 | 2025-09-28 – 2026-09-26 | 45.436 | 9.123 | 2.067 | 7.056 | 4.41x |
| Broadcom | 1,450.000 | 2025-08-04 – 2026-08-02 | 89.104 | 40.653 | 1.250 | 39.403 | 32.52x |
| Microsoft | 3,600.000 | 2025-10-01 – 2026-09-30 | 346.445 | 195.878 | 135.921 | 59.957 | 1.44x |
| Amazon | 2,670.000 | 2025-10-01 – 2026-09-30 | 797.455 | 168.300 | unavailable | unavailable | unavailable |
| Alphabet | 3,250.000 | 2025-10-01 – 2026-09-30 | 471.098 | 179.551 | 159.804 | 19.747 | 1.12x |
| Meta Platforms | 1,430.000 | 2025-10-01 – 2026-09-30 | unavailable | 133.087 | 104.438 | 28.649 | 1.27x |
| Oracle | 315.480 | 2025-09-01 – 2026-08-31 | unavailable | 46.940 | 75.660 | -28.720 | 0.62x |
| OpenAI | 852.000 | ? – ? | unavailable | unavailable | unavailable | unavailable | unavailable |
| Anthropic | 1,190.000 | 2025-10-01 – 2026-09-30 | 35.282 | 5.956 | 0.945 | 5.011 | 6.30x |
| SpaceX / SpaceX AI | 1,740.000 | ? – ? | unavailable | unavailable | unavailable | unavailable | unavailable |
| TSMC | 1,570.000 | ? – ? | unavailable | unavailable | unavailable | unavailable | unavailable |
| SK hynix | 594.911 | ? – ? | unavailable | unavailable | unavailable | unavailable | unavailable |
| Micron | 672.640 | 2025-08-29 – 2026-09-03 | 133.188 | 89.675 | 30.712 | 58.963 | 2.92x |
| Samsung Electronics | 874.068 | ? – ? | unavailable | unavailable | unavailable | unavailable | unavailable |
| Dell Technologies | 176.770 | 2025-08-02 – 2026-07-31 | 151.197 | 12.152 | 3.592 | 8.560 | 3.38x |
| Hewlett Packard Enterprise | 54.310 | 2025-08-01 – 2026-07-31 | 41.871 | 6.694 | unavailable | unavailable | unavailable |
| Foxconn / Hon Hai | 89.888 | ? – ? | unavailable | unavailable | unavailable | unavailable | unavailable |

## Novije i strane objave — poseban period i valuta

Ovi podaci dopunjuju starije TTM redove. Nisu sabrani sa njima. PP&E plus intangible assets ima drugačiji obuhvat od PP&E-only.
NVIDIA: najnoviji kvartal 115.844 mlrd USD; potvrđeni TTM prihod 361.808 mlrd USD = 215.938 − 147.811 + 293.681. TTM se završava 25.10.2026; ne mešati ga sa julskim TTM ostalih pokazatelja.

| Kompanija | Metrika | Period | Milijarde izvorne valute | Valuta |
|---|---|---|---:|---|
| nvidia | revenue | 2026-07-27 – 2026-10-25 | 115.844 | USD |
| nvidia | revenue_ttm | 2025-10-27 – 2026-10-25 | 361.808 | USD |
| sk_hynix | revenue | 2026-07-01 – 2026-09-30 | 104,615.500 | KRW |
| samsung_electronics | revenue | 2026-07-01 – 2026-09-30 | 195,300.000 | KRW |
| nvidia | operating_cash_flow | 2026-07-27 – 2026-10-25 | 48.253 | USD |
| nvidia | cash_ppe_and_intangibles | 2026-07-27 – 2026-10-25 | 4.422 | USD |
| tsmc | operating_cash_flow | 2026-01-01 – 2026-09-30 | 2,402.117 | TWD |
| tsmc | cash_ppe | 2026-01-01 – 2026-09-30 | 1,289.971 | TWD |
| foxconn | revenue | 2026-01-01 – 2026-09-30 | 7,661.062 | TWD |
| foxconn | operating_cash_flow | 2026-01-01 – 2026-09-30 | -125.723 | TWD |
| foxconn | reported_capital_expenditures | 2026-01-01 – 2026-09-30 | 161.726 | TWD |

Primljeni avansi se ne mogu automatski tumačiti kao samostalno održiva profitabilnost.
Izvorni URL, hash, dostupnost i napomene svakog reda su u supplemental-statements.csv.


## Kako se računa grupa

1. Priznati spoljni prihod = dokumentovana prodaja članica kupcima van granice. Interna prodaja se eliminiše jednom.
2. Spoljni neto novac = svi izvršeni prilivi preko granice minus svi izvršeni odlivi; kapital i dug se odvajaju od poslovnih tokova.
3. Operativni novac i ulaganja zahtevaju usaglašenu klasifikaciju. Kod interno proizvedene opreme trošak prema spoljnim dobavljačima zahteva preklasifikaciju; nije dovoljno obrisati interni capex.
4. Pokrivenost ulaganja = usaglašen spoljni operativni novac / bruto spoljna infrastrukturna ulaganja. Bez potvrđenog imenioca nema procenta.
5. Finansijski jaz = bruto spoljna infrastrukturna ulaganja − usaglašen spoljni operativni novac. Akvizicije, krediti, vlasnička ulaganja i dividende prikazuju se odvojeno.
6. Dobit zahteva eliminaciju interne marže u zalihama/opremi, korekciju amortizacije, troškova, poreza i equity-method rezultata; neto novac nije dobit.
7. Potrebno je usaglašavanje početne gotovine + neto tokova + FX = završna gotovina za isti period i granicu.

## Finansiranje i buduće obaveze

Odvojeno su izvezene 8 finansijske objave i 6 ugovorne objave.
One nisu sabrane: minimum, maksimum, opcija, namera, kreditni limit i prijavljeno ulaganje nisu ista osnova.
Revidirana Azure obaveza zamenjuje staru objavu; istorijska cifra se ne dodaje ponovo.

## Šta nedostaje

Za svih 18 operativnih članica nedostaje kompletan usaglašen registar međusobnih prihoda i plaćanja. Precizni razlozi su u data-gaps.csv i metric-evidence.csv.
IPO S-1 i strani/custom taksonomski izveštaji nisu automatski tretirani kao standardni US-GAAP 10-Q/10-K. Neobjavljeni iznosi ostaju nepoznati.
Za AI-only rezultat dodatno nedostaje pouzdana raspodela prihoda, operativnih troškova, capex-a i obrtnog kapitala na AI i ostalo poslovanje.
95% globalne pokrivenosti nije dokazano: nema potpunog, usaglašenog imenioca. Broj kompanija ili zbir najava nisu zamena.

## Izvori i dostupnost

SEC činjenice se koriste tek nakon accepted_at + 5 minuta. Noviji filings/restatements ne prepisuju raniji pogled.
Companyfacts je preuzet naknadno: ovo je rekonstruisan pogled sa proverom dostupnosti, bez tvrdnje da postoji potpuna arhiva tadašnjeg data-vintage-a.
Finansijske činjenice su hash-proverene; metric-evidence.csv i financial-audit.json čuvaju periode, komponente TTM-a, accession i availability.

Metod eliminacija: [IFRS 10 B86(c)](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2023/issued/part-a/ifrs-10-consolidated-financial-statements.pdf?bypass=on).
Njegove principe koristimo analitički; ove nezavisne kompanije nisu pravna konsolidovana grupa.

- NVIDIA: [SEC filing 0001045810-26-000075](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/0001045810-26-000075-index.html)
- AMD: [SEC filing 0000002488-26-000191](https://www.sec.gov/Archives/edgar/data/2488/000000248826000191/0000002488-26-000191-index.html)
- Broadcom: [SEC filing 0001730168-26-000080](https://www.sec.gov/Archives/edgar/data/1730168/000173016826000080/0001730168-26-000080-index.html)
- Microsoft: [SEC filing 0001193125-26-436133](https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/0001193125-26-436133-index.html)
- Amazon: [SEC filing 0001018724-26-000040](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/0001018724-26-000040-index.html)
- Alphabet: [SEC filing 0001652044-26-000084](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/0001652044-26-000084-index.html)
- Meta Platforms: [SEC filing 0001628280-26-066773](https://www.sec.gov/Archives/edgar/data/1326801/000162828026066773/0001628280-26-066773-index.html)
- Oracle: [SEC filing 0001193125-26-389274](https://www.sec.gov/Archives/edgar/data/1341439/000119312526389274/0001193125-26-389274-index.html)
- Micron: [SEC filing 0000723125-26-000023](https://www.sec.gov/Archives/edgar/data/723125/000072312526000023/0000723125-26-000023-index.html)
- Dell Technologies: [SEC filing 0001571996-26-000046](https://www.sec.gov/Archives/edgar/data/1571996/000157199626000046/0001571996-26-000046-index.html)
- Hewlett Packard Enterprise: [SEC filing 0001645590-26-000080](https://www.sec.gov/Archives/edgar/data/1645590/000164559026000080/0001645590-26-000080-index.html)

## Provereni S-1 izveštaji i radni kapital

### Anthropic: 2026-01-01 – 2026-09-30
Iznosi u milionima USD; odnose se na ceo issuer, nisu grupno spoljašnje poslovanje.
- operating_cash_flow: 6569
- investing_cash_flow: -36546
- financing_cash_flow: 110735
- fx: -7
- opening_cash_including_restricted: 17401
- closing_cash_including_restricted: 98152
- finance_lease_principal_payments: 88
- leased_assets_and_equipment_prepayments: 1955
- accounts_receivable_cash_adjustment: -7076
- deferred_revenue_cash_adjustment: 1702
- Whole-issuer reported figures, not verified external AI demand or bilateral settled cash.
- CFO is affected by working capital and noncash fair-value adjustments; accounting net loss is not cash burn.
- Cash-flow closing balance 98,152m differs by 50m from balance-sheet cash 95,562m plus restricted cash 2,540m in this archived document; unresolved, no clean liquidity estimate.
- Finance-lease principal and equipment prepayments are excluded from cash PP&E metric and must be separately reconciled.
Izvor: [Anthropic S-1/A, accession 0001628280-26-068676](https://www.sec.gov/Archives/edgar/data/2130357/000162828026068676/anthropicpbc-sx1ax1.htm)
