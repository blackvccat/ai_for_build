"""Local multilingual semantic retrieval; exact evidence stays in SQLite.

Visual descriptors are explicit image statistics, NOT learned visual embeddings.
Search returns candidates for trial assembly, never production approval.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_ID = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MODEL_REVISION = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'


def normalized(a):
    a = np.asarray(a, dtype=np.float32)
    return a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)


class SemanticEncoder:
    def __init__(self, directory):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        directory = Path(directory)
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(directory / 'model_qint8_arm64.onnx'), options,
                                            providers=['CPUExecutionProvider'])

    def encode(self, texts, batch_size=16):
        output = []
        for start in range(0, len(texts), batch_size):
            batch = self.tokenizer.encode_batch(texts[start:start + batch_size])
            inputs = {'input_ids': np.array([x.ids for x in batch], dtype=np.int64),
                      'attention_mask': np.array([x.attention_mask for x in batch], dtype=np.int64),
                      'token_type_ids': np.array([x.type_ids for x in batch], dtype=np.int64)}
            needed = {x.name for x in self.session.get_inputs()}
            hidden = self.session.run(None, {k: v for k, v in inputs.items() if k in needed})[0]
            mask = inputs['attention_mask'][..., None]
            output.append((hidden * mask).sum(axis=1) / mask.sum(axis=1).clip(1))
        return normalized(np.concatenate(output))


def visual_descriptor(path):
    """RGB distribution + 8x8 foreground occupancy, suitable only as a reranker."""
    rgb = np.asarray(Image.open(path).convert('RGB').resize((128, 128)), dtype=np.float32)
    background = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0)
    mask = np.linalg.norm(rgb - background, axis=2) > 35
    occupancy = mask.reshape(8, 16, 8, 16).mean(axis=(1, 3)).ravel()
    pixels = rgb[mask] if mask.any() else rgb.reshape(-1, 3)
    hist = np.concatenate([np.histogram(pixels[:, c], bins=8, range=(0, 256))[0]
                           for c in range(3)]).astype(float)
    hist /= max(len(pixels), 1)
    return normalized(np.concatenate([hist, occupancy]))


def component_record(entry, families):
    family = entry['family']
    annotation = entry.get('annotation', entry)
    voxels = entry.get('voxels')
    if voxels:
        xyz = np.array([v[:3] for v in voxels])
        dimensions = (xyz.max(0) - xyz.min(0) + 1).tolist()
        states = sorted(set(v[3] for v in voxels))
    else:
        dimensions = entry['scale_range']['native_xyz']
        states = sorted(entry['exact_block_states'])
    label = families.get(family, '完整窗构件 window assembly')
    # Interpretation comes first to prevent long inventories truncating meaning.
    text = ' '.join([label, family, entry.get('visual_interpretation', ''),
                     ' '.join(v.get('role', '') for v in entry.get('subcomponents', {}).values()),
                     ' '.join(s.split('[')[0].replace('minecraft:', '') for s in states),
                     annotation.get('occlusion', '')])
    return {'id': entry['component_id'], 'family': family, 'text': text,
            'width': dimensions[0], 'height': dimensions[1], 'depth': dimensions[2],
            'game_status': annotation.get('game_test', 'NOT_RUN'),
            'update_policy': annotation.get('update_policy', 'UNTESTED'),
            'evidence': entry, 'states': states, 'card': entry['card']}


def build_index(project_root, destination=None):
    root = Path(project_root)
    out = Path(destination) if destination else root / 'knowledge/retrieval'
    out.mkdir(parents=True, exist_ok=True)
    catalog_path = root / 'knowledge/library-v1/catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = catalog['windows'] + catalog['recipes']
    records = sorted([component_record(e, catalog['families']) for e in entries], key=lambda r: r['id'])
    encoder = SemanticEncoder(out / 'model')
    vectors = encoder.encode([r['text'] for r in records])
    visuals = np.array([visual_descriptor(root / r['card']) for r in records])
    np.savez_compressed(out / 'vectors.npz', semantic=vectors, visual=visuals)
    db = sqlite3.connect(str(out / 'components.sqlite3'))
    with db:
        db.execute('DROP TABLE IF EXISTS components')
        db.execute('CREATE TABLE components (id TEXT PRIMARY KEY, family TEXT, width INT, height INT, depth INT, game_status TEXT, record TEXT)')
        db.executemany('INSERT INTO components VALUES (?,?,?,?,?,?,?)',
                       [(r['id'], r['family'], r['width'], r['height'], r['depth'], r['game_status'],
                         json.dumps(r, ensure_ascii=False)) for r in records])
    db.close()
    meta = {'schema_version': 1, 'count': len(records), 'ids': [r['id'] for r in records],
            'model': MODEL_ID, 'revision': MODEL_REVISION, 'semantic_dimension': vectors.shape[1],
            'catalog_sha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
            'model_sha256': hashlib.sha256((out / 'model/model_qint8_arm64.onnx').read_bytes()).hexdigest(),
            'visual_descriptor': 'nonlearned RGB histogram and foreground occupancy',
            'excluded': 'Uninterpreted local contexts are not embedded.',
            'admission': 'All retrieved records remain candidates; game validation required.'}
    (out / 'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


class ComponentIndex:
    def __init__(self, directory):
        self.path = Path(directory)
        self.meta = json.loads((self.path / 'manifest.json').read_text(encoding="utf-8"))
        with sqlite3.connect(str(self.path / 'components.sqlite3')) as db:
            data = {k: json.loads(v) for k, v in db.execute('SELECT id, record FROM components')}
        self.records = [data[k] for k in self.meta['ids']]
        with np.load(self.path / 'vectors.npz') as arrays:
            self.semantic, self.visual = arrays['semantic'], arrays['visual']
        self.encoder = None

    def query(self, text, limit=5, family=None, max_width=None, max_depth=None,
              game_status=None, dimensions=None, reference_image=None):
        if not text.strip():
            raise ValueError('A nonempty architectural intent is required')
        if self.encoder is None:
            self.encoder = SemanticEncoder(self.path / 'model')
        similarity = self.semantic @ self.encoder.encode([text])[0]
        visual = self.visual @ visual_descriptor(reference_image) if reference_image else None
        result = []
        for i, r in enumerate(self.records):
            if family and r['family'] != family: continue
            if max_width is not None and r['width'] > max_width: continue
            if max_depth is not None and r['depth'] > max_depth: continue
            if game_status and r['game_status'] != game_status: continue
            scores = {'semantic': float(similarity[i])}
            weighted, weight = scores['semantic'], 1.0
            if visual is not None:
                scores['visual_statistics'] = float(visual[i]); weighted += .15 * visual[i]; weight += .15
            if dimensions is not None:
                target = np.asarray(dimensions, dtype=float)
                if target.shape != (3,) or np.any(target <= 0): raise ValueError('dimensions must be positive xyz')
                actual = np.array([r['width'], r['height'], r['depth']])
                scores['geometry'] = float(np.exp(-np.mean(abs(np.log(actual / target)))))
                weighted += .25 * scores['geometry']; weight += .25
            result.append({'id': r['id'], 'family': r['family'], 'score': float(weighted / weight),
                           'scores': scores, 'dimensions': [r['width'], r['height'], r['depth']],
                           'explanation': r['text'], 'evidence': r['evidence'],
                           'game_status': r['game_status'], 'decision': 'CANDIDATE_REQUIRES_TRIAL_ASSEMBLY'})
        return sorted(result, key=lambda r: (-r['score'], r['id']))[:limit]
