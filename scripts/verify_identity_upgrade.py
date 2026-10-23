"""Opt-in LOCAL acceptance: generates four new images, never edits profiles.

Use a previously approved terminal batch as the source of reference and prompt.
Reports contain local identifiers: keep the output outside the source repository.
This records facts, not an automatic aesthetic/likeness acceptance decision.
"""
import argparse
import copy
import json
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8766')
    parser.add_argument('--source-batch', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cases', default='cold,warm,scheduled,research')
    parser.add_argument('--wait-source', action='store_true', help='Wait for an existing GUI-submitted source, without resubmitting it')
    parser.add_argument('--model-id', choices=['cyberrealistic-xl-plus-face', 'illustrious-xl-v2.0-plus-face'])
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.scheme != 'http':
        parser.error('Acceptance is restricted to local HTTP services')
    cases = args.cases.split(',')
    if not cases or any(case not in {'cold', 'warm', 'scheduled', 'research'} and not re.fullmatch(r'strength-(?:0(?:\.\d+)?|1(?:\.0+)?)', case) for case in cases):
        parser.error('Unknown acceptance case')
    repo = Path(__file__).resolve().parents[1]
    if args.output.resolve().is_relative_to(repo):
        parser.error('Keep private acceptance receipts outside the public source repository')
    if args.output.exists():
        parser.error('Use a new output directory; previous receipts are never overwritten')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, payload=None):
        request = urllib.request.Request(args.base_url + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    source = api('/api/identity/batches/' + args.source_batch)
    wait_started = time.monotonic()
    while args.wait_source and source['state'] not in {'complete', 'failed', 'cancelled'}:
        if time.monotonic()-wait_started > 1000:
            raise TimeoutError('Existing GUI batch did not finish; no new work submitted')
        print(json.dumps({'sourceState': source['state'], 'stage': source.get('stage'), 'step': source.get('step')}, ensure_ascii=False), flush=True)
        time.sleep(5)
        source = api('/api/identity/batches/' + args.source_batch)
    if args.wait_source and source['state'] != 'complete':
        parser.error('Existing GUI batch did not complete; inspect it before resubmission')
    if source['state'] not in {'complete', 'failed', 'cancelled'}:
        parser.error('Source batch is active; do not duplicate its work')
    original = source['request']
    args.output.mkdir(parents=True)
    (args.output / 'source.json').write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'sourceBatchId': source['id'], 'cases': [], 'visualQualityAccepted': False}
    for case in cases:
        payload = copy.deepcopy(original)
        payload.update(count=1, stepValues=None, previewEvery=0)
        request = payload['request']
        if args.model_id:
            request['modelId'] = args.model_id
        request.update(facePolish=False, traceLevel='basic', referenceStart=0., referenceEnd=1.)
        if case == 'scheduled':
            request.update(referenceStart=.15, referenceEnd=.85)
        if case == 'research':
            request.update(traceLevel='h7', researchCoverage='representative', steps=8, width=512, height=512)
        if case.startswith('strength-'):
            request['identityStrength'] = float(case.removeprefix('strength-'))
        started = time.monotonic()
        batch = api('/api/identity/batches', payload)
        print(json.dumps({'case': case, 'batchId': batch['id']}, ensure_ascii=False), flush=True)
        previous = None
        while batch['state'] not in {'complete', 'failed', 'cancelled'}:
            state = (batch['state'], batch.get('stage'), batch.get('step'))
            if state != previous:
                print(json.dumps({'case': case, 'state': state, 'elapsedSeconds': round(time.monotonic()-started, 1)}, ensure_ascii=False), flush=True)
                previous = state
            if time.monotonic()-started > 1000:
                raise TimeoutError('Acceptance timed out; batch remains available for inspection, not automatically resubmitted')
            time.sleep(2)
            batch = api('/api/identity/batches/' + batch['id'])
        receipt = {'case': case, 'wallSeconds': round(time.monotonic()-started, 3), 'batch': batch}
        (args.output / (case + '.json')).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        report['cases'].append(receipt)
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': case, 'state': batch['state'], 'wallSeconds': receipt['wallSeconds'], 'error': batch.get('error')}, ensure_ascii=False), flush=True)
        if batch['state'] != 'complete':
            raise RuntimeError('Acceptance stopped on a non-complete batch; inspect its receipt')


if __name__ == '__main__':
    main()
