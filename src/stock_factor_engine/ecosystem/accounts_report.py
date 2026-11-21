"""Reproducible financial context and fail-closed analytical boundary worksheet."""
import argparse
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import subprocess

from .financials import issuer_financials
from .ledger import calculate_accounts
from .model import load_registry, view_as_of, FINANCING, PURCHASES
from .reviewed import reviewed_financials
from .supplemental import supplemental_statements
from .perimeter import accounting_perimeter


def write_csv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def display(value):
    return 'unavailable' if value is None else f'{value / 1000000000:,.3f}'


def build_accounts_report(registry, roots, output):
    registry, output = Path(registry), Path(output)
    bundle = load_registry(registry)
    inputs = json.loads((registry / 'accounts.json').read_text(encoding='utf-8'))
    if inputs['as_of'] != bundle['config']['as_of']:
        raise ValueError('Refresh dated group perimeter and source registry before changing cutoff')
    entities = [e for e in bundle['entities'] if e['node_type'] == 'company_group']
    ids = {e['id'] for e in entities}
    controls = json.loads((registry / 'controls.json').read_text(encoding='utf-8'))
    perimeter = accounting_perimeter(ids, controls, Path('data/ai-ecosystem-2026-11-20/supplemental-evidence'),
        as_of=inputs['as_of'], period_start=inputs['period_start'], period_end=inputs['period_end'])
    accounts = calculate_accounts(inputs, members=perimeter['members'], as_of=inputs['as_of'],
                                  period_start=inputs['period_start'], period_end=inputs['period_end'])
    financials = [issuer_financials(e, roots, inputs['as_of']) for e in entities]
    reviews = json.loads((registry / 'reviewed-statements.json').read_text(encoding='utf-8'), parse_float=Decimal)
    source_map = {s['id']: s for s in bundle['sources']}
    for review in reviews:
        entity = next(e for e in entities if e['id'] == review['entity_id'])
        reviewed = reviewed_financials(entity, review, source_map[review['source_id']],
            Path(inputs['reviewed_evidence_dir']), inputs['as_of'])
        financials = [reviewed if f['entity_id'] == entity['id'] else f for f in financials]
    view = view_as_of(bundle, inputs['as_of'])
    sources = {s['id']: s for s in bundle['sources']}
    supplements = supplemental_statements(json.loads((registry / 'supplemental.json').read_text(encoding='utf-8')),
        Path('data/ai-ecosystem-2026-11-20/supplemental-evidence'), inputs['as_of'], ids)
    disclosures = []
    for edge in view['active']:
        if edge['kind'] not in FINANCING | PURCHASES:
            continue
        disclosures.append({**edge, 'amount_usd': edge.get('amount_usd'),
            'source_urls': ' ; '.join(sources[s]['url'] for s in edge['source_ids']),
            'cash_ledger_eligible': False,
            'reason': 'Disclosure basis/term not reconciled to actual same-period settled cash; never aggregate with sales/cash'})
    parents, metric_rows, gaps = [], [], []
    for f in financials:
        row = {key: f.get(key) for key in ('entity_id', 'company', 'cik', 'status', 'scope', 'reporting_end',
               'reported_parent_cash_after_ppe_usd', 'reported_parent_cfo_to_ppe_ratio')}
        for name in ('revenue', 'operating_income', 'operating_cash_flow', 'capital_expenditure', 'cash', 'total_debt', 'net_ppe'):
            metric = f['metrics'].get(name, {})
            row[name + '_usd'] = metric.get('value')
            if name == 'revenue':
                row['ttm_start'] = metric.get('period_start')
                row['ttm_end'] = metric.get('period_end')
            metric_rows.append({'entity_id': f['entity_id'], 'metric': name,
                'value_usd': metric.get('value'), 'period_start': metric.get('period_start'),
                'period_end': metric.get('period_end'), 'status': metric.get('status', 'unavailable'),
                'reason': metric.get('reason', '; '.join(f['reasons']) if not metric else ''),
                'evidence_json': json.dumps(metric, default=str, sort_keys=True)})
        if row.get('ttm_start') is None:
            available = next((m for m in f['metrics'].values() if m.get('period_start') and m.get('value') is not None), None)
            if available:
                row['ttm_start'], row['ttm_end'] = available['period_start'], available['period_end']
        row['reasons'] = '; '.join(f['reasons'])
        parents.append(row)
        for reason in f['reasons']:
            gaps.append({'entity_id': f['entity_id'], 'domain': 'reported parent context', 'reason': reason})
        for note in f.get('review_notes', []):
            gaps.append({'entity_id': f['entity_id'], 'domain': 'reviewed statement qualification', 'reason': note})
        gaps.append({'entity_id': f['entity_id'], 'domain': 'analytical group',
                     'reason': 'Same-calendar bilateral cash/sales, AI allocation, asset margin, receivables/payables and ownership/elimination reconciliation incomplete'})
    output.mkdir(parents=True, exist_ok=True)
    parent_fields = ['entity_id', 'company', 'cik', 'status', 'reporting_end', 'ttm_start', 'ttm_end',
        'revenue_usd', 'operating_income_usd', 'operating_cash_flow_usd', 'capital_expenditure_usd',
        'reported_parent_cash_after_ppe_usd', 'reported_parent_cfo_to_ppe_ratio',
        'cash_usd', 'total_debt_usd', 'net_ppe_usd', 'scope', 'reasons']
    write_csv(output / 'parent-financials.csv', parents, parent_fields)
    write_csv(output / 'supplemental-statements.csv', supplements,
        ['entity_id', 'metric', 'amount', 'currency', 'period_start', 'period_end', 'period_basis',
         'available_at', 'availability_policy', 'basis', 'url', 'sha256', 'ttm_bridge', 'evidence_format', 'reviewed_page_index', 'locator', 'note'])
    write_csv(output / 'metric-evidence.csv', metric_rows,
              ['entity_id', 'metric', 'value_usd', 'period_start', 'period_end', 'status', 'reason', 'evidence_json'])
    fields = ['id', 'from_id', 'to_id', 'kind', 'status', 'amount_usd', 'amount_qualifier',
              'period_start', 'period_end', 'source_urls', 'cash_ledger_eligible', 'reason', 'notes']
    write_csv(output / 'financing-disclosures.csv', [d for d in disclosures if d['kind'] in FINANCING], fields)
    write_csv(output / 'purchase-obligations.csv', [d for d in disclosures if d['kind'] in PURCHASES], fields)
    write_csv(output / 'data-gaps.csv', gaps, ['entity_id', 'domain', 'reason'])
    ledger_fields = ['economic_id', 'payer', 'payee', 'amount_usd', 'currency', 'basis', 'category',
                     'period_start', 'period_end', 'available_at', 'source_urls', 'boundary', 'eliminated_usd']
    write_csv(output / 'cash-eliminations.csv', accounts['cash_eliminations'], ledger_fields)
    write_csv(output / 'sales-eliminations.csv', accounts['sales_eliminations'], ledger_fields)
    summary = {'as_of': inputs['as_of'], 'accounting_period': [inputs['period_start'], inputs['period_end']],
               'company_count': len(entities), 'parent_context_complete_count': sum(f['status'] == 'available' for f in financials),
               'accounting_perimeter': perimeter,
               'accounting_unit_count': len(perimeter['members']),
               'parent_context_partial_count': sum(f['status'] == 'partial' for f in financials),
               'parent_context_unavailable_count': sum(f['status'] == 'unavailable' for f in financials),
               'companies_with_any_financial_context': len({f['entity_id'] for f in financials if f['metrics']} | {r['entity_id'] for r in supplements}),
               'group_accounts': accounts, 'global_flow_coverage': None,
               'self_funding_coverage': accounts['self_funding_coverage'], 'financing_gap_usd': accounts['financing_gap_usd'], 'liquidity_runway_months': None,
               'status': accounts['status'],
               'reason': ('No estimates from mixed-term commitments or uneliminated parent totals; private/foreign/custom taxonomy data need reviewed extraction'
                          if accounts['status'] != 'complete' else 'Boundary accounts reconciled; profit and forward liquidity still require separate evidence')}
    (output / 'summary.json').write_text(json.dumps(summary, default=str, indent=2), encoding='utf-8')
    (output / 'financial-audit.json').write_text(json.dumps(financials, default=str, indent=2), encoding='utf-8')
    lines = ['# AI ekosistem — finansijski pregled i eliminacije', '',
        f"Decision cutoff: **{inputs['as_of']}**. Granica: **{len(entities)} kompanije/grupe** iz datiranog registra.",
        f"Ciljni period grupnog obračuna: **{inputs['period_start']} – {inputs['period_end']}**.",
        f"Posle potvrđenog spajanja Wiwynn u Wistron: **{len(perimeter['members'])} računovodstvenih jedinica**; kompletna kontrolna mapa još zahteva pregled.",
        'Wiwynn je naveden i zasebno radi konteksta. Njegove finansije se ne dodaju ponovo Wistron konsolidovanim finansijama.', '',
        'Kontrolna veza: [Wiwynn Q3 2026, Note 7(a), PDF strana 55](https://www.wiwynn.com/hubfs/Investors/Financial_Report/Wiwynn_2026Q3_Financial.pdf).', '',
        f"**Grupni spoljni prihod: {display(accounts['external_revenue_usd'])}; neto novac: {display(accounts['external_net_cash_usd'])} (milijarde USD). Dobit: unavailable.**",
        'Registar ugovora ne dokazuje izvršene uplate. Prazan transakcioni registar ne znači nula stvarnog prometa.',
        'Ovo je analitičko objedinjavanje nezavisnih kompanija, bez tvrdnje da postoji zajednička kontrola ili nepravilno knjiženje.', '',
        '## Objavljene finansije po kompaniji', '',
        'Iznosi su u milijardama USD. Svaki red ima svoj TTM period; različiti fiskalni kalendari se ne sabiraju. ',
        'Prihodi i CFO uključuju interne poslove sa drugim članicama i poslovanje koje nije AI. CFO minus cash PP&E nije grupni FCF, ',
        'ne uključuje automatski finance lease additions, otplate lease glavnice ili sve kategorije ulaganja. Cash nije potvrđena raspoloživa likvidnost.', '',
        '| Kompanija | TTM od–do | Prihod | CFO | Cash PP&E | CFO−PP&E | CFO/PP&E |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in parents:
        dates = f"{row.get('ttm_start') or '?'} – {row.get('ttm_end') or row.get('reporting_end') or '?'}"
        ratio = row.get('reported_parent_cfo_to_ppe_ratio')
        lines.append('| ' + ' | '.join([row['company'], dates, *[display(row.get(key)) for key in
            ('revenue_usd', 'operating_cash_flow_usd', 'capital_expenditure_usd', 'reported_parent_cash_after_ppe_usd')],
            'unavailable' if ratio is None else f'{ratio:.2f}x']) + ' |')
    lines += ['', '## Novije i strane objave — poseban period i valuta', '',
        'Ovi podaci dopunjuju starije TTM redove. Nisu sabrani sa njima. PP&E plus intangible assets ima drugačiji obuhvat od PP&E-only.',
        'NVIDIA: najnoviji kvartal 115.844 mlrd USD; potvrđeni TTM prihod 361.808 mlrd USD = 215.938 − 147.811 + 293.681. TTM se završava 25.10.2026; ne mešati ga sa julskim TTM ostalih pokazatelja.', '',
        '| Kompanija | Metrika | Period | Milijarde izvorne valute | Valuta |',
        '|---|---|---|---:|---|']
    for row in supplements:
        lines.append(f"| {row['entity_id']} | {row['metric']} | {row['period_start']} – {row['period_end']} | {row['amount'] / 1000000000:,.3f} | {row['currency']} |")
    lines += ['', 'Nebius: devetomesečni CFO 4.231 mlrd USD uključuje 7.829 mlrd USD promene deferred revenue; avansi se ne mogu tumačiti kao samostalno održiva profitabilnost.',
        'Izvorni URL, hash, dostupnost i napomene svakog reda su u supplemental-statements.csv.', '']
    lines += ['', '## Kako se računa grupa', '',
        '1. Priznati spoljni prihod = dokumentovana prodaja članica kupcima van granice. Interna prodaja se eliminiše jednom.',
        '2. Spoljni neto novac = svi izvršeni prilivi preko granice minus svi izvršeni odlivi; kapital i dug se odvajaju od poslovnih tokova.',
        '3. Operativni novac i ulaganja zahtevaju usaglašenu klasifikaciju. Kod interno proizvedene opreme trošak prema spoljnim dobavljačima zahteva preklasifikaciju; nije dovoljno obrisati interni capex.',
        '4. Pokrivenost ulaganja = usaglašen spoljni operativni novac / bruto spoljna infrastrukturna ulaganja. Bez potvrđenog imenioca nema procenta.',
        '5. Finansijski jaz = bruto spoljna infrastrukturna ulaganja − usaglašen spoljni operativni novac. Akvizicije, krediti, vlasnička ulaganja i dividende prikazuju se odvojeno.',
        '6. Dobit zahteva eliminaciju interne marže u zalihama/opremi, korekciju amortizacije, troškova, poreza i equity-method rezultata; neto novac nije dobit.',
        '7. Potrebno je usaglašavanje početne gotovine + neto tokova + FX = završna gotovina za isti period i granicu.', '',
        '## Finansiranje i buduće obaveze', '',
        f"Odvojeno su izvezene {sum(d['kind'] in FINANCING for d in disclosures)} finansijske objave i {sum(d['kind'] in PURCHASES for d in disclosures)} ugovorne objave.",
        'One nisu sabrane: minimum, maksimum, opcija, namera, kreditni limit i prijavljeno ulaganje nisu ista osnova.',
        'Revidirana Azure obaveza zamenjuje staru objavu; istorijska cifra se ne dodaje ponovo.', '',
        '## Šta nedostaje', '',
        'Za svih 32 članice nedostaje kompletan usaglašen registar međusobnih prihoda i plaćanja. Precizni razlozi po kompaniji i metrici su u data-gaps.csv i metric-evidence.csv.',
        'IPO S-1 i strani/custom taksonomski izveštaji nisu automatski tretirani kao standardni US-GAAP 10-Q/10-K. Neobjavljeni iznosi ostaju nepoznati.',
        'Za AI-only rezultat dodatno nedostaje pouzdana raspodela prihoda, operativnih troškova, capex-a i obrtnog kapitala na AI i ostalo poslovanje.',
        '95% globalne pokrivenosti nije dokazano: nema potpunog, usaglašenog imenioca. Broj kompanija ili zbir najava nisu zamena.', '',
        '## Izvori i dostupnost', '',
        'SEC činjenice se koriste tek nakon accepted_at + 5 minuta. Noviji filings/restatements ne prepisuju raniji pogled. ',
        'Companyfacts je preuzet naknadno: ovo je rekonstruisan pogled sa proverom dostupnosti, bez tvrdnje da postoji potpuna arhiva tadašnjeg data-vintage-a.',
        'Finansijske činjenice su hash-proverene; metric-evidence.csv i financial-audit.json čuvaju periode, komponente TTM-a, accession i availability.', '',
        'Metod eliminacija: [IFRS 10 B86(c)](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2023/issued/part-a/ifrs-10-consolidated-financial-statements.pdf?bypass=on). ',
        'Njegove principe koristimo analitički; ove nezavisne kompanije nisu pravna konsolidovana grupa.', '']
    for f in financials:
        if f.get('latest_filing'):
            acc = f['latest_filing']['accession_number']
            lines.append(f"- {f['company']}: [SEC filing {acc}](https://www.sec.gov/Archives/edgar/data/{int(f['cik'])}/{acc.replace('-', '')}/{acc}-index.html)")
    lines += ['', '## Provereni S-1 izveštaji i radni kapital', '']
    for f in financials:
        if f.get('reviewed_period_context'):
            lines.append(f"### {f['company']}: {f['reviewed_period'][0]} – {f['reviewed_period'][1]}")
            lines.append('Iznosi u milionima USD; odnose se na ceo issuer, nisu grupno spoljašnje poslovanje.')
            for key, value in f['reviewed_period_context'].items():
                lines.append(f'- {key}: {value}')
            for note in f['review_notes']:
                lines.append('- ' + note)
            lines.append(f"Izvor: [{f['sources'][0]['title']}]({f['sources'][0]['url']})")
    (output / 'financial-report.md').write_text('\n'.join(line.rstrip() for line in lines) + '\n', encoding='utf-8')
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except subprocess.CalledProcessError:
        commit = None
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'commit': commit, 'as_of': inputs['as_of'],
                'registry_sha256': {p.name: digest(p) for p in sorted(registry.glob('*.json'))},
                'code_sha256': {p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
                'outputs_sha256': {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != 'manifest.json'}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return {key: value for key, value in summary.items() if key not in ('group_accounts', 'accounting_perimeter')}


def main(argv=None):
    parser = argparse.ArgumentParser(description='AI ecosystem financial context and analytical eliminations')
    parser.add_argument('--registry', type=Path, default=Path('research/ai-ecosystem'))
    parser.add_argument('--evidence', type=Path, action='append')
    parser.add_argument('--output', type=Path, default=Path('data/reports/ai-financials-2026-11-20'))
    args = parser.parse_args(argv)
    roots = args.evidence or [Path('data/current-2026-11-20'), Path('data/ai-ecosystem-2026-11-20/financial-evidence')]
    print(json.dumps(build_accounts_report(args.registry, roots, args.output), default=str, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
