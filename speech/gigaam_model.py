"""Load the publisher's Hugging Face CTC artifacts using the installed GigaAM package."""

import json
from pathlib import Path

import torch
from gigaam import GigaAMASR
from omegaconf import OmegaConf


def load_gigaam(root: Path = Path('/models/gigaam')) -> GigaAMASR:
    cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))['cfg']['model']['cfg']
    if cfg['model_name'] != 'v3_e2e_ctc':
        raise ValueError('Expected the GigaAM v3 end-to-end CTC configuration')

    # The publisher's config names its HF wrapper classes. Use the equivalent
    # classes in our pinned GigaAM package instead of executing downloaded code.
    targets = {
        'preprocessor': 'gigaam.preprocess.FeatureExtractor',
        'encoder': 'gigaam.encoder.ConformerEncoder',
        'head': 'gigaam.decoder.CTCHead',
        'decoding': 'gigaam.decoding.CTCGreedyDecoding',
    }
    for section, target in targets.items():
        cfg[section]['_target_'] = target
    cfg['encoder']['flash_attn'] = False
    cfg['decoding']['model_path'] = str(root / 'tokenizer.model')

    model = GigaAMASR(OmegaConf.create(cfg))
    weights = torch.load(root / 'pytorch_model.bin', map_location='cpu', weights_only=True)
    model.load_state_dict({name.removeprefix('model.'): tensor for name, tensor in weights.items()})
    return model.eval()
