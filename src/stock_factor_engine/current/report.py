from collections import Counter
from dataclasses import asdict
from datetime import datetime, date
from decimal import Decimal as D
import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from stock_factor_engine.providers.market.yahoo import parse as parse_chart
from stock_factor_engine.providers.sec.ingestion import parse_filings, parse_facts
from stock_factor_engine.regime.inputs import Membership, regime_inputs
from stock_factor_engine.regime.model import evaluate_market_regime, apply_exposure
from stock_factor_engine.strategy import rank_candidates, RankingResult
from stock_factor_engine.universe.registry import IDENTITIES
from .calculations import candidate, completed_prices


QUANT500 = ('SNDK', 'MU', 'PSX', 'VLO', 'MPC', 'STX', 'WDC', 'SMCI', 'HPE', 'DELL',
            'TER', 'APA', 'OXY', 'NUE', 'FTNT', 'NVDA', 'CVS', 'PLTR', 'CVX', 'EOG')
FIELDS = ('Rank', 'Ticker', 'Company', 'Sector', 'Quality', 'Value', 'Momentum', 'Risk',
          'Final Score', 'Previous Rank', 'Rank Change', 'Action', 'Rank Scope')
WEIGHTS = {'quality': D('.40'), 'value': D('.25'), 'momentum': D('.20'), 'risk': D('.15')}


def load_evidence(folder, key):
    location = folder / 'raw' / (key + '.json.gz')
    meta = json.loads((folder / 'raw' / (key + '.meta.json')).read_text(encoding='utf-8'))
    content = gzip.decompress(location.read_bytes())
    if hashlib.sha256(content).hexdigest() != meta['sha256']:
        raise ValueError('Evidence SHA-256 mismatch: ' + key)
    return content, meta


def price_history(folder, symbol, *, equity=False):
    content, meta = load_evidence(folder, 'chart_' + symbol)
    identity = {'instrument_type': 'EQUITY', 'exchange_timezone': 'America/New_York'} if equity else None
    bars, actions, rejected, chart_meta = parse_chart(content, symbol,
        datetime.fromisoformat(meta['retrieved_at']), identity=identity)
    if chart_meta.get('regularMarketTime') is None:
        raise ValueError('Missing market observation timestamp')
    return bars, actions, {'source': meta, 'quarantined': rejected, 'currency': chart_meta.get('currency')}


def action(rank, held):
    if held:
        return 'KEEP' if rank is not None and rank <= 35 else 'SELL'
    return 'BUY' if rank is not None and rank <= 20 else 'WATCH'


def ranking_rows(ranking, members, previous=None, holdings=frozenset()):
    previous = previous or {}
    rows = []
    for item in ranking.ranked:
        member = members[item.symbol]
        prior = previous.get(item.symbol)
        rows.append({'Rank': item.rank, 'Ticker': item.symbol, 'Company': member['company'],
            'Sector': member['sector'], 'Quality': item.components['quality'], 'Value': item.components['value'],
            'Momentum': item.components['momentum'], 'Risk': item.components['risk'], 'Final Score': item.score,
            'Previous Rank': prior, 'Rank Change': None if prior is None else prior - item.rank,
            'Action': action(item.rank, item.symbol in holdings),
            'Rank Scope': f'Provisional: {len(ranking.ranked)} complete-data names; global rank unavailable'})
    return rows


def csv_write(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def table(rows, fields=FIELDS):
    if not rows:
        return 'Nema stavki.\n'
    def cell(value):
        if value is None: return 'unavailable'
        if isinstance(value, D): return f'{value:.2f}'
        return str(value).replace('|', '/').replace('\n', ' ')
    lines = ['| ' + ' | '.join(fields) + ' |', '|' + '|'.join('---' for _ in fields) + '|']
    lines += ['| ' + ' | '.join(cell(row.get(name)) for name in fields) + ' |' for row in rows]
    return '\n'.join(lines) + '\n'


def build_report(folder, *, as_of, previous_as_of, output):
    folder, output = Path(folder), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    current_date, previous_date = as_of.date().isoformat(), previous_as_of.date().isoformat()
    membership = json.loads((folder / 'membership.json').read_text(encoding='utf-8'))
    published = datetime.fromisoformat(membership['published_at'].replace('Z', '+00:00'))
    for instant in (previous_as_of, as_of):
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError('Decision timestamps must be timezone-aware')
        if published > instant or not date.fromisoformat(membership['effective_from']) <= instant.date() <= date.fromisoformat(membership['verified_through']):
            raise ValueError('Dated membership evidence does not cover the decision timestamp')
    members = {item['ticker']: item for item in membership['members']}
    if len(members) != 503 or len({item['cik'] for item in members.values()}) != 500:
        raise ValueError('This dated S&P roster must contain 503 securities and 500 issuers')
    prices, splits, price_audit, price_errors = {}, {}, {}, {}
    for symbol in list(members) + ['SPY', 'RSP', 'HYG', 'LQD', '^VIX']:
        try:
            bars, actions, meta = price_history(folder, symbol.replace('.', '-'), equity=symbol in members)
            prices[symbol], splits[symbol], price_audit[symbol] = bars, actions, meta
        except (ValueError, KeyError, OSError, ArithmeticError) as error:
            prices[symbol], splits[symbol] = [], []
            price_errors[symbol] = type(error).__name__ + ': ' + str(error)
    current_spy = completed_prices(prices['SPY'], as_of)
    prior_spy = completed_prices(prices['SPY'], previous_as_of)
    for reference, instant in ((current_spy, as_of), (prior_spy, previous_as_of)):
        if not reference or reference[-1].trading_date != instant.date():
            raise ValueError('SPY has no exact decision-session price: ' + str(instant.date()))
    snapshots = {'current': [], 'previous': []}
    exclusions = {'current': {}, 'previous': {}}
    audits = {'current': {}, 'previous': {}}
    fact_cache = {}
    issuer_counts = Counter(item['cik'] for item in members.values())
    for index, (symbol, member) in enumerate(members.items(), 1):
        initial_reasons = []
        if member['sector'] in ('Financials', 'Utilities'):
            initial_reasons = ['Excluded sector: ' + member['sector']]
        elif symbol in price_errors:
            initial_reasons = ['Price source: ' + price_errors[symbol]]
        facts, filing_map, sec_audit = [], {}, {}
        if not initial_reasons:
            try:
                cik = member['cik']
                if cik not in fact_cache:
                    submissions_raw, submission_meta = load_evidence(folder, 'submissions_' + cik)
                    facts_raw, facts_meta = load_evidence(folder, 'facts_' + cik)
                    submissions = json.loads(submissions_raw, parse_float=D)
                    payload = json.loads(facts_raw, parse_float=D)
                    if str(submissions['cik']).zfill(10) != cik or str(payload['cik']).zfill(10) != cik:
                        raise ValueError('SEC source CIK differs from dated roster')
                    filings, filing_rejects = parse_filings(submissions['filings']['recent'], 'sec:' + cik)
                    archive_sources = []
                    earliest = previous_as_of.date().replace(year=previous_as_of.year - 3)
                    for page in submissions['filings'].get('files', []):
                        if page.get('filingTo', '9999-12-31') < earliest.isoformat():
                            continue
                        archive_raw, archive_meta = load_evidence(folder, 'archive_' + page['name'][:-5])
                        archived, rejected = parse_filings(json.loads(archive_raw), 'sec:' + cik)
                        filings.extend(archived)
                        filing_rejects.extend(rejected)
                        archive_sources.append(archive_meta)
                    filing_map = {}
                    for filing in filings:
                        existing = filing_map.get(filing.accession_number)
                        if existing is not None and existing != filing:
                            raise ValueError('Conflicting SEC submissions pages for ' + filing.accession_number)
                        filing_map[filing.accession_number] = filing
                    parsed, fact_rejects = parse_facts(payload, 'sec:' + cik, filing_map)
                    facts = [item[0] for item in parsed]
                    cutoff_date = previous_as_of.date().replace(year=previous_as_of.year - 3)
                    facts = [fact for fact in facts if fact.period_end >= cutoff_date]
                    sec_audit = {'submissions': submission_meta, 'archives': archive_sources, 'companyfacts': facts_meta,
                        'rejected_filings': filing_rejects, 'rejected_fact_count': len(fact_rejects),
                        'filings': {key: asdict(value) for key, value in filing_map.items()}}
                    fact_cache = {cik: (facts, filing_map, sec_audit)}
                else:
                    facts, filing_map, sec_audit = fact_cache[cik]
                # Only dated roster/class information and the pre-existing registry
                # establish share scope. Current SEC ticker metadata is not historical.
                if (issuer_counts[cik] > 1 or '.' in symbol
                        or IDENTITIES.get(symbol, {}).get('multiple_share_classes', False)):
                    initial_reasons = ['Multiple/class-specific shares in dated identity evidence; issuer capitalization cannot use one class price']
            except (ValueError, KeyError, OSError, ArithmeticError) as error:
                initial_reasons = ['SEC source: ' + type(error).__name__ + ': ' + str(error)]
        for label, instant, reference in (('current', as_of, current_spy), ('previous', previous_as_of, prior_spy)):
            if initial_reasons:
                exclusions[label][symbol] = initial_reasons
                continue
            snapshot, reasons, audit = candidate(member, facts=facts, bars=prices[symbol], splits=splits[symbol],
                as_of=instant, session=reference[-1].trading_date,
                reference_dates=[bar.trading_date for bar in reference])
            if snapshot is not None:
                snapshots[label].append(snapshot)
                audit['raw_factors'] = asdict(snapshot)
            else:
                exclusions[label][symbol] = reasons
            audit['sec_sources'] = sec_audit
            audits[label][symbol] = audit
        if index % 50 == 0:
            print(f'Calculated {index}/{len(members)}; current complete={len(snapshots["current"])}', flush=True)
    rankings = {}
    for label, instant in (('current', as_of), ('previous', previous_as_of)):
        rankings[label] = rank_candidates(snapshots[label], model='compounder') if snapshots[label] else RankingResult('compounder', instant, (), ())
        for rejected in rankings[label].excluded:
            exclusions[label][rejected.symbol] = list(rejected.reasons)
    prior_ranks = {item.symbol: item.rank for item in rankings['previous'].ranked}
    rows = ranking_rows(rankings['current'], members, prior_ranks)
    previous_rows = ranking_rows(rankings['previous'], members)
    paper_holdings = {item.symbol for item in rankings['previous'].ranked[:20]} if len(previous_rows) >= 20 else set()
    rotation = ranking_rows(rankings['current'], members, prior_ranks, paper_holdings)
    for symbol in sorted(paper_holdings - {row['Ticker'] for row in rotation}):
        rotation.append({'Ticker': symbol, 'Company': members[symbol]['company'], 'Sector': members[symbol]['sector'],
                         'Action': 'SELL', 'Previous Rank': prior_ranks[symbol], 'Reason': '; '.join(exclusions['current'].get(symbol, ['No current rank']))})
    market = {symbol: prices[symbol] for symbol in ('SPY', 'RSP', 'HYG', 'LQD', '^VIX')}
    member_prices = {symbol: completed_prices(prices[symbol], as_of) for symbol in members}
    session, regime_values = regime_inputs(market, as_of=as_of,
        membership=Membership(as_of.date(), frozenset(members), membership['source'], True),
        member_prices=member_prices, include_completed_close=True)
    regime = evaluate_market_regime(regime_values, session=session)
    regime['inputs'] = {key: factor.payload() for key, factor in regime_values.items()}
    stock_weights = {}
    if len(rows) >= 20:
        stock_weights = {row['Ticker']: D('.05') for row in rows[:20]}
    allocation = apply_exposure(stock_weights, regime) if regime['status'] == 'available' and stock_weights else None
    quant = []
    by_symbol = {item.symbol: item for item in rankings['current'].ranked}
    top = list(rankings['current'].ranked[:20])
    means = {key: sum((item.components[key] for item in top), D(0)) / len(top) for key in WEIGHTS} if top else {}
    for reference_rank, symbol in enumerate(QUANT500, 1):
        item = by_symbol.get(symbol)
        entry = {'Quant500 Rank': reference_rank, 'Ticker': symbol, 'Our Rank': item.rank if item else None}
        if item:
            deficits = {key: (means[key] - item.components[key]) * weight for key, weight in WEIGHTS.items()}
            entry.update({key.title(): item.components[key] for key in WEIGHTS})
            entry['Largest weighted deficit vs scored candidate mean'] = max(deficits, key=deficits.get)
            entry['Weighted deficit'] = max(deficits.values())
        else:
            entry['Reason'] = '; '.join(exclusions['current'].get(symbol, ['Not in verified dated universe']))
        quant.append(entry)
    exclusion_rows = [{'Ticker': symbol, 'Company': members[symbol]['company'], 'Sector': members[symbol]['sector'],
                       'Reason': '; '.join(reasons)} for symbol, reasons in sorted(exclusions['current'].items())]
    csv_write(output / f'compoundrank-{current_date}.csv', rows, FIELDS)
    csv_write(output / f'compoundrank-{previous_date}.csv', previous_rows, FIELDS)
    csv_write(output / f'excluded-{current_date}.csv', exclusion_rows, ('Ticker', 'Company', 'Sector', 'Reason'))
    csv_write(output / f'paper-rotation-{current_date}.csv', rotation, FIELDS + ('Reason',))
    quant_fields = ('Quant500 Rank', 'Ticker', 'Our Rank', 'Quality', 'Value', 'Momentum', 'Risk',
                    'Largest weighted deficit vs scored candidate mean', 'Weighted deficit', 'Reason')
    csv_write(output / 'quant500-comparison.csv', quant, quant_fields)
    model_portfolio = [{'Ticker': row['Ticker'], 'Equity sleeve weight': D('.05') if len(rows) >= 20 else None,
        'Effective portfolio weight': allocation['equity_weights'][row['Ticker']] if allocation else None,
        'Status': 'target only; no execution' if allocation else 'unavailable: fewer than 20 names or incomplete regime decision'} for row in rows[:20]]
    csv_write(output / 'initial-model-portfolio.csv', model_portfolio,
              ('Ticker', 'Equity sleeve weight', 'Effective portfolio weight', 'Status'))
    def exclusion_kind(reasons):
        for reason in reasons:
            if reason.startswith('Excluded sector:'):
                return reason
        filters = ('Capital Employed is not positive', 'TTM EBIT is not positive', 'Price below',
                   'Fewer than 252 completed trading sessions')
        if any(any(marker in reason for marker in filters) for reason in reasons):
            return 'Other explicit universe filters'
        return 'Data unavailable or ambiguous; eligibility not established'
    coverage_counts = dict(Counter(exclusion_kind(reasons) for reasons in exclusions['current'].values()))
    summary = {'coverage_counts': coverage_counts, 'status': 'partial' if rows else 'unavailable', 'decision_timestamp': as_of, 'previous_timestamp': previous_as_of, 'universe': len(members),
               'issuers': len({item['cik'] for item in members.values()}), 'scored': len(rows),
               'excluded': len(exclusion_rows), 'previous_scored': len(previous_rows), 'regime': regime,
               'allocation': allocation, 'membership': membership, 'price_errors': price_errors,
               'quant500_overlap': sorted(set(QUANT500) & {row['Ticker'] for row in rows[:20]}) if len(rows) >= 20 else None,
               'quant500_scored_reference': sorted(set(QUANT500) & set(by_symbol)),
               'paper_rotation_status': 'available' if len(previous_rows) >= 20 else 'unavailable: fewer than 20 prior ranked names',
               'portfolio_basis': 'No actual holdings. Initial model starts from cash; paper rotation separately assumes prior Top20.',
               'data_vintage': 'Retrospective reconstruction from downloads on/after decision date. SEC availability uses accepted_at+5m; not a contemporaneously archived complete data vintage.'}
    (output / 'summary.json').write_text(json.dumps(summary, default=str, indent=2), encoding='utf-8')
    (output / 'audit.json').write_text(json.dumps({'financials': audits, 'prices': price_audit,
        'exclusions': exclusions}, default=str, indent=2), encoding='utf-8')
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except Exception:
        commit = 'unavailable'
    lines = [f'# CURRENT CompoundRank: {current_date}', '',
        f'Report status: **{summary["status"]}**. Rankings require complete observed factors; missing data are not zero-filled.', '',
        f'Decision timestamp: **{as_of.isoformat()}** (16:30 New York). Cena i faktori ukljucuju zavrsenu sesiju 20.11.',
        f'Universe: {len(members)} securities / 500 companies. Scored: **{len(rows)}**. Excluded/unavailable: **{len(exclusion_rows)}**.',
        f'Previous ranking: {previous_as_of.isoformat()}, {len(previous_rows)} scored. Rank Change = previous rank minus current rank.',
        'Rank movements also reflect changes in complete-data cross-section coverage, not only changes in one company.',
        '', '## Coverage', '', table([{'Category': key, 'Count': value} for key, value in coverage_counts.items()], ('Category', 'Count')),
        '', '## Podaci i ogranicenja', '',
        f'- Dated membership revision: [{membership["revision_id"]}]({membership["source"]}), published {membership["published_at"]}. ' + membership['verification'],
        '- SEC: original accession linked to accepted_at; available_at = accepted_at + 5 minutes. Future filings are excluded. Companyfacts downloaded later are not an independently archived as-of vintage.',
        '- Market data: Yahoo raw close for price and capitalization, adjusted close for momentum/risk/ratios and SMA. Downloaded after the decision; vendor corrections cannot be ruled out.',
        '- Formulas, score weights and thresholds were not changed after inspecting the result. No market-cap filter. Missing short debt or D&A is never assumed zero.',
        '- Report covers complete-data subset, not a claim that unscored companies are economically ineligible. Exclusions identify the exact reason.',
        '- No real portfolio supplied. Main Action uses an empty starting portfolio (BUY/WATCH). Separate paper rotation uses previous Top20 as hypothetical holdings; no trades have been executed.',
        '- A high rank is a screening result. Model targets would be executed no earlier than the next trading session.',
        f'- Source code base commit at generation: `{commit}`; see delivery commit for final implementation.', '',
        '## TOP 20 BUY candidates', '', 'Provisional complete-data subset only. A full Top20 is unavailable when fewer than 20 names can be scored.', '', table(rows[:20]),
        '## KEEP zone 21-35', '', 'This is the rank zone; without actual holdings these rows are WATCH.', '', table(rows[20:35]),
        '## SELL candidates', '', 'No real holdings supplied. Hypothetical prior-Top20 rotation status: ' + summary['paper_rotation_status'], '',
        table([row for row in rotation if row['Action'] == 'SELL'], FIELDS + ('Reason',)),
        '## Biggest rank improvements', '', table(sorted([row for row in rows if row['Rank Change'] is not None and row['Rank Change'] > 0], key=lambda row: -row['Rank Change'])[:10]),
        '## Biggest rank deteriorations', '', table(sorted([row for row in rows if row['Rank Change'] is not None and row['Rank Change'] < 0], key=lambda row: row['Rank Change'])[:10]),
        '## Market Regime', '', f'Status: **{regime["status"]}**. Regime: **{regime["regime"] or "unavailable"}**. Score: **{regime["score"] if regime["score"] is not None else "unavailable"}**. Target equity exposure: **{regime["equity_exposure"] if regime["equity_exposure"] is not None else "unavailable"}**.', '',
        table([{'Input': key, 'Value': factor.value * 100 if factor.value is not None and factor.unit == 'ratio' else factor.value, 'Unit': '%' if factor.unit == 'ratio' else factor.unit, 'Status': factor.payload()['status'], 'Reason': factor.reason}
               for key, factor in regime_values.items()], ('Input', 'Value', 'Unit', 'Status', 'Reason')),
        'Breadth incomplete members: ' + ', '.join(regime_values['breadth'].details.get('missing', [])) if regime_values['breadth'].details else '',
        'VIX front-month: unavailable/optional; no invented ticker or penalty.', '',
        '## Combined portfolio', '', 'Weight columns below are fractions of the full portfolio (0.05 means 5%).', '', table(model_portfolio, ('Ticker', 'Equity sleeve weight', 'Effective portfolio weight', 'Status')),
        ('Cash/defensive target: ' + str(allocation['cash_weight']) if allocation else 'Effective targets and cash/defensive bucket: unavailable because regime or Top20 is incomplete. No default exposure is substituted.'),
        'Illustration only: at 75% equity exposure with 20 equal weights, each stock would be 3.75% of total portfolio and cash/defensive 25%.', '',
        '## Quant500 sanity check', '',
        'Reference Top20 is supplied by the user, not independently verified or treated as the same methodology. ' + ('Top20 overlap unavailable: fewer than 20 names are scored.' if summary['quant500_overlap'] is None else 'Overlap: ' + str(len(summary['quant500_overlap'])) + '/20 (' + ', '.join(summary['quant500_overlap']) + ').'),
        'Scored Quant500 reference names: ' + ', '.join(summary['quant500_scored_reference']) + '. For scored reference names, the largest weighted component deficit relative to the scored candidate mean (up to 20 names) describes our model. Without Quant500 component data its actual cause of disagreement cannot be established. No parameter was tuned to match the list.', '',
        table(quant, quant_fields), '',
        '## All scored companies', '', 'Percentiles are relative to this complete-data subset, not the entire economically eligible S&P 500. A global rank cannot be claimed from incomplete factor coverage.', '', table(rows),
        '## All excluded or unavailable companies', '', table(exclusion_rows, ('Ticker', 'Company', 'Sector', 'Reason'))]
    (output / f'compoundrank-{current_date}.md').write_text('\n'.join(lines), encoding='utf-8')
    return summary
