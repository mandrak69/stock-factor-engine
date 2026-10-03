from dataclasses import asdict

from .balance import Result


def result_payload(result):
    return {'status': result.status, 'value': str(result.value) if result.value is not None else None,
            'unit': result.unit, 'formula': result.formula, 'reason': result.reason,
            'assumptions': result.assumptions,
            'inputs': {name: result_payload(item) if isinstance(item, Result) else item
                       for name, item in result.inputs.items()},
            'sources': [asdict(term) for term in result.sources]}
