"""Numeric support check, NOT a proof that a number is attached to the right entity."""
import json
import math
import re

NUMBER = re.compile(r'(?<![\w])[-+]?\d+(?:[.,]\d+)?')


def numbers(text):
    return [float(n.replace(',', '.')) for n in NUMBER.findall(text)]


def unsupported_numbers(text, evidence):
    allowed = numbers(json.dumps(evidence, ensure_ascii=False))
    # Round to the displayed precision; no broad relative tolerance for identifiers.
    bad = []
    for token in NUMBER.findall(text):
        value = float(token.replace(',', '.'))
        digits = len(re.split('[.,]', token)[1]) if re.search('[.,]', token) else 0
        if not any(math.isclose(value, round(a, digits), abs_tol=1e-8) for a in allowed):
            bad.append(token)
    return bad
