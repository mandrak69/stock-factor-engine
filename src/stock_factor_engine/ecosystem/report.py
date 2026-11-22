import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

from .selection import select_report_bundle, export_size_selection

from .model import FINANCING, PURCHASES, instant, load_registry, view_as_of, summarize, reciprocal_candidates


def dump_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows, fields):
    if not rows:
        return 'Unavailable: no matching disclosed records.\n'
    def value(item):
        return 'unavailable' if item is None else str(item).replace('|', '/').replace('\n', ' ')
    lines = ['| ' + ' | '.join(fields) + ' |', '|' + '|'.join('---' for _ in fields) + '|']
    lines += ['| ' + ' | '.join(value(row.get(field)) for field in fields) + ' |' for row in rows]
    return '\n'.join(lines) + '\n'


def build_report(registry, output, as_of=None):
    bundle = load_registry(registry)
    if as_of is not None and instant(as_of) != instant(bundle['config']['as_of']):
        raise ValueError('Refresh entity perimeter and provenance for another as-of; this is a curated snapshot')
    bundle, size_decisions = select_report_bundle(bundle, registry)
    view = view_as_of(bundle, as_of or bundle['config']['as_of'])
    summary = summarize(bundle, view)
    pairs = reciprocal_candidates(view)
    nodes = {node['id']: node for node in bundle['entities']}
    sources = {source['id']: source for source in bundle['sources']}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    export_size_selection(output, size_decisions)
    summary['size_threshold_usd'] = bundle['config'].get('report_size_filter', {}).get('minimum_usd')
    summary['size_excluded_count'] = sum(r['status'] != 'included' for r in size_decisions)
    participants = []
    for node in bundle['entities']:
        participants.append({'ID': node['id'], 'Name': node['name'], 'Layer': node['layer'], 'Node type': node['node_type'],
            'Roles': '; '.join(node['roles']), 'Aliases': '; '.join(node['aliases']),
            'Sources': '; '.join(node['source_ids']), 'Notes': node['notes']})
    rows = []
    history_rows = []
    active_ids = {edge['id'] for edge in view['active']}
    for edge in view['historical']:
        refs = edge['source_ids']
        periods = edge.get('period_precision') or 'exact dates only where supplied'
        row = {'ID': edge['id'], 'From': nodes[edge['from_id']]['name'], 'To': nodes[edge['to_id']]['name'],
            'Kind': edge['kind'], 'Direction': edge.get('direction', 'named relationship; type determines economic meaning'), 'Status': edge['status'], 'USD amount': edge['amount_usd'],
            'USD bn': None if edge['amount_usd'] is None else str(Decimal(edge['amount_usd']) / 1_000_000_000),
            'Basis': edge['amount_qualifier'], 'Maximum USD': edge.get('maximum_usd'),
            'Quantity': edge.get('quantity'), 'Quantity unit': edge.get('quantity_unit'),
            'Start': edge.get('period_start') or edge.get('period_start_month') or edge.get('period_start_year'),
            'End': edge.get('period_end') or edge.get('period_end_month') or edge.get('period_end_year'),
            'Period precision': periods, 'Cash verified': edge['cash_verified'], 'Aggregation permitted': False,
            'Active disclosure': edge['id'] in active_ids,
            'Source IDs': '; '.join(refs), 'Source URLs': '; '.join(sources[key]['url'] for key in refs),
            'Available at': '; '.join(sources[key]['available_at'] for key in refs),
            'Source locator': edge['source_locator'], 'Notes': edge['notes']}
        history_rows.append(row)
        if edge['id'] in active_ids:
            rows.append(row)
    fields = ('ID','From','To','Kind','Direction','Status','USD amount','USD bn','Basis','Maximum USD','Quantity','Quantity unit',
              'Start','End','Period precision','Cash verified','Aggregation permitted','Active disclosure','Source IDs','Source URLs','Available at','Source locator','Notes')
    dump_csv(output / 'relationships.csv', rows, fields)
    dump_csv(output / 'disclosure-history.csv', history_rows, fields)
    dump_csv(output / 'participants.csv', participants, ('ID','Name','Layer','Node type','Roles','Aliases','Sources','Notes'))
    dump_csv(output / 'sources.csv', bundle['sources'], ('id','title','url','published_date','available_at','availability_policy','locator','reviewed_date'))
    contract_rows = sorted([row for row in rows if row['Kind'] in PURCHASES and row['Kind'] != 'hardware_framework' and row['USD amount'] is not None],
                           key=lambda row: -Decimal(row['USD amount']))
    funding_rows = [row for row in rows if row['Kind'] in FINANCING]
    def links(row):
        result = dict(row)
        result['Sources'] = ', '.join('[' + key + '](' + sources[key]['url'] + ')' for key in row['Source IDs'].split('; '))
        return result
    columns = ('From','To','USD bn','Basis','Status','Start','End','Notes','Sources')
    pair_rows = [{'Funder': nodes[item['funder']]['name'], 'Customer': nodes[item['customer']]['name'],
                  'Financing': item['funding_id'], 'Purchases': '; '.join(item['purchase_ids'])} for item in pairs]
    context_rows = [{'Subject': nodes[item['entity_id']]['name'], 'USD bn': str(Decimal(item['amount_usd']) / 1_000_000_000),
                     'Basis': item['basis'], 'Notes': item['notes']} for item in view['contexts']]
    diagram = ['flowchart LR']
    chosen = [edge for edge in view['active'] if edge['kind'] in (FINANCING | {'compute_commitment','lease_commitment'})
              and edge['id'] not in ('microsoft_nebius', 'openai_coreweave_order')]
    selected_nodes = {edge[key] for edge in chosen for key in ('from_id','to_id')}
    for key in sorted(selected_nodes):
        diagram.append('  ' + key + '["' + nodes[key]['name'].replace('"','') + '"]')
    for edge in chosen:
        label = edge['kind'] + (' / ' + str(Decimal(edge['amount_usd']) / 1_000_000_000) + ' USD bn' if edge['amount_usd'] else '')
        diagram.append('  ' + edge['from_id'] + ' -. "' + label + '" .-> ' + edge['to_id'])
    lines = ['# AI ekosistem: mapa ucesnika i objavljenih odnosa', '',
        'As-of: **' + view['as_of'] + '**. Version: ' + bundle['config']['version'] + '.',
        f'**{summary["company_group_count"]} grupe, {summary["reference_node_count"]} projektne/ugovorne reference, {summary["active_relationship_count"]} aktivnih zapisa o odnosima, {len(sources)} primarnih izvora.**', '',
        '**Pokrivenost od 95% nije dokazana.** Nema zajednickog, usaglasenog imenitelja za sve AI novcane tokove. Ova mapa je pocetni registar, ne globalni popis niti konsolidovani finansijski izvestaj.',
        'Postojanje odnosa ne dokazuje nepravilno knjizenje. Odvojene firme mogu pravilno iskazivati medjusobnu prodaju.',
        'Aktivan zapis znaci poslednju verziju medju pregledanim objavama, ne potvrdu da je ugovor i dalje neizmenjen niti da je ovo kompletan popis svih kasnijih izmena.', '',
        '## Granica analize', '', bundle['config']['scope'],
        '- Core: cloud, modeli, procesori i specijalizovani compute operatori.',
        '- Supply chain: proizvodnja cipova/memorije i serverskih sistema.',
        '- Capital: finansijeri i asset manageri; njihova fondovska sredstva nisu automatski sopstvena sredstva upravljaca.',
        '- Reference: projekti i delimicno nepoznati zakupodavci; nisu dodatne kompanije za sabiranje bilansa.',
        '- Whole-group likvidnost i AI-specific potraznja su razliciti pogledi. Maloprodaja, reklame, Office i svemirske usluge nisu automatski AI prihod.', '',
        'Prag veličine: tržišna kapitalizacija ≥50 mlrd USD; privatne valuacije su posebno označeni istorijski proxy. Market-values.csv prikazuje osnove i datume; size-exclusions.csv je zaseban audit. Kotacije su retrospektivni vendor snapshot, bez potvrđene tadašnje objave.', '', '## Operativno jezgro', '', markdown_table([row for row in participants if row['Layer']=='core'], ('Name','Roles','Sources','Notes')),
        '## Operativni dobavljaci', '', markdown_table([row for row in participants if row['Layer'] == 'supply_chain'], ('Name','Layer','Roles','Sources','Notes')),
        '## Odabrane veze', '', 'Isprekidane strelice prikazuju razlicite vrste odnosa i obaveza. Nisu dokaz izvrsenog toka istog novca niti sabirljivi iznosi.', '',
        '```mermaid', '\n'.join(diagram), '```', '',
        '## Najveci objavljeni ugovorni iznosi u registru', '',
        'USD milijarde. Razliciti rokovi, minimumi, maksimumi, uslovi raskida i lease principal nisu direktno uporedivi i nisu sabrani. Periodi oznaceni samo godinom/mesecem nemaju izmisljen tacan dan. Pool zakupodavaca nije ceo Broadcom.', '',
        markdown_table([links(row) for row in contract_rows], columns),
        '## Ulaganja i finansiranje: odvojeno od prihoda i gotovine', '', markdown_table([links(row) for row in funding_rows], columns),
        '## Moguca zavisnost finansiranja i kupca', '',
        'Ovo su veze koje zahtevaju analizu finansiranja/kupovine. Ne dokazuju round-tripping, identitet istog novca ili lazne prihode.', '',
        markdown_table(pair_rows, ('Funder','Customer','Financing','Purchases')),
        '## Kontekst: agregati i ciljevi, ne dodatne transakcije', '', markdown_table(context_rows, ('Subject','USD bn','Basis','Notes')),
        '## Zastita od dupliranja i pogresnog netiranja', '',
        '- Google/GCP/GOOG/GOOGL su jedna referenca za Alphabet; AWS je Amazon; Azure je Microsoft.',
        '- Noviji Anthropic/Microsoft zapis zamenjuje prethodnih 30 milijardi u aktivnom prikazu. Istorija cuva oba objavljivanja.',
        '- Nebius/Meta 27 milijardi obuhvata 12 milijardi dedicated i do 15 milijardi residual-capacity backstop; 27 nije treca kupovina.',
        '- Nebius/Microsoft 19.4 milijarde je prosireni maksimum, ne dodatak osnovnih 17.4 milijarde.',
        '- Broadcom lease assignments ne stvaraju novu kupovinu; finansijska linija za rentu nije jos jedan infrastrukturni trosak.',
        '- Warrant akcije, GW kapaciteta, kapital, kreditni limiti i prihod nisu isti tip mere.',
        '- Za eliminaciju prodaje opreme potrebni su i istorijski trosak, interna marza u imovini i amortizacija; sami naslovi ugovora nisu dovoljni.', '',
        '## Gotovina i konsolidacija', '',
        f'Verifikovani pojedinacni cash-settlement zapisi: {summary["verified_cash_record_count"]}. Dokumentovani cash subtotal: ' + ('unavailable' if summary['documented_cash_subtotal_usd'] is None else str(summary['documented_cash_subtotal_usd'])) + '.',
        'Spoljni prihod, spoljni neto cash flow i konsolidovani bilans: **unavailable**. Nisu postavljeni na nulu.', '',
        '## Preostale praznine za cilj od 95%', '', *['- ' + gap for gap in bundle['config']['gaps']], '',
        'Sledeci korak je usaglasavanje jedne vrste toka i jednog perioda, pa pracenje znacajnih spoljnih counterparties i izvornih uplata. Broj imenovanih grupa sam po sebi nije procenat ekonomske pokrivenosti.', '',
        '## Izvori', '', *['- [' + source['id'] + ': ' + source['title'] + '](' + source['url'] + ') â€” available_at ' + source['available_at'] + '; ' + source['locator'] for source in bundle['sources']]]
    (output / 'ecosystem.md').write_text('\n'.join(lines), encoding='utf-8')
    (output / 'map.mmd').write_text('\n'.join(diagram) + '\n', encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps({**summary, 'reciprocal_candidates':pairs}, default=str, indent=2), encoding='utf-8')
    (output / 'network.json').write_text(json.dumps({'entities':bundle['entities'], **view}, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        commit = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
    except Exception:
        commit = None
    manifest = {'commit':commit, 'registry_sha256': {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(registry).glob('*.json')},
                'output_sha256': {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file() and path.name!='manifest.json'}}
    (output / 'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return summary
