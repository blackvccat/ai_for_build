"""Recheck a recorded visual review without advancing its building workflow."""
import argparse
import json
from pathlib import Path

from paris_builder import atelier_workflow as a
from paris_builder.learning import digest, read_json
from paris_builder.local_credentials import load_key
from paris_builder.operations import ROOT, Operation, write_json
from paris_builder.providers import MultimodalClient, ProviderError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--prior-operation', required=True)
    args = parser.parse_args()
    task = a.load(ROOT / 'runs' / args.run)
    data = a.summary(ROOT / 'runs' / args.run)
    candidate = next(item for item in data['candidates'] if item['id'] == args.candidate)
    prior = ROOT / 'runs/LEARNING-WORKBENCH-v1/operations' / args.prior_operation
    observations = {}
    view_names = {str(Path(item['path']).resolve()): name for name, item in candidate['views'].items()}
    input_receipts = []
    for path in sorted(prior.glob('views-*-0.json')):
        saved = read_json(path)
        images = saved['receipt']['image_evidence']
        for image, text in zip(images, saved['result']['observations']):
            if digest(Path(image['path'])) != image['sha256']:
                raise ValueError('Recorded image changed: ' + image['path'])
            observations[view_names[str(Path(image['path']).resolve())]] = text
        input_receipts.append(saved['receipt'])
    if set(observations) != set(candidate['views']):
        raise ValueError('Recorded observations do not cover current candidate views')
    reference = read_json(prior / 'references-0.json')
    for image in reference['receipt']['image_evidence']:
        if digest(Path(image['path'])) != image['sha256']:
            raise ValueError('Recorded reference changed')
    operation = Operation('vision.schema-verification', {'run': args.run, 'candidate': args.candidate,
        'prior_operation': args.prior_operation, 'input_receipts': input_receipts + [reference['receipt']]})
    client = MultimodalClient({'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
        'vision': True, 'max_calls': None, 'max_total_tokens': None, 'max_output_tokens': 16000,
        'raw_reply_dir': str(operation.folder), 'timeout_seconds': 180,
        'request_options': {'thinking': {'type': 'disabled'}}}, credential=load_key())
    def checked_call(label, payload, images, validator):
        for attempt in range(3):
            try:
                result, receipt = client.complete(json.dumps(payload, ensure_ascii=False), images=images, max_tokens=8000)
                write_json(operation.folder / (label + '-' + str(attempt) + '.json'), {'result': result, 'receipt': receipt})
                if not validator(result): raise ValueError('Invalid summary schema')
                print(label + ': validated', flush=True)
                return result
            except (ValueError, ProviderError) as error:
                if attempt == 2: raise
                payload['format_reminder'] = str(error) + '; follow required_output exactly, checks must be objects.'
    try:
        verdict = a.collect_architectural_verdict(task, {'brief': task['brief'], 'plan': candidate['plan'],
            'stage_scope': 'Current stage: ' + task['stage'] + '. Inspect built facade composition and surrounds; '
                'shopfront dressing, rails and rustication are future tier work. Roof form must already match '
                'Haussmann mansard: steep lower slope, break, shallower upper slope. Blind party walls are intentional. '
                'Resolve occlusion against the geometry manifest. No game acceptance.',
            'structure': candidate.get('manifest', {}).get('structure'),
            'walls': candidate.get('manifest', {}).get('walls'),
            'openings': candidate.get('manifest', {}).get('openings'),
            'observations': observations, 'reference_comparisons': reference['result']['comparisons']}, checked_call)
        write_json(operation.folder / 'verified-review.json', verdict)
        operation.finish(verdict, validation={'schema': 'PASS', 'workflow_modified': False, 'game_acceptance': 'PENDING'})
        print(json.dumps({'operation': operation.id, 'schema': 'PASS', 'decision': verdict['decision'],
                          'layers': len(verdict.get('detail_checks', {})),
                          'storeys': len(verdict.get('storey_checks', {}))}), flush=True)
    except Exception as error:
        operation.fail(str(error))
        raise


if __name__ == '__main__':
    main()
