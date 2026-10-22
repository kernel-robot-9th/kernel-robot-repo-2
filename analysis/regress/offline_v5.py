"""Open-loop check of a v5 checkpoint on its training frames: per-joint error of the predicted 50-step chunk."""
import sys, torch, numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors
CK, REPO, TASK = sys.argv[1], sys.argv[2], sys.argv[3]
pol = SmolVLAPolicy.from_pretrained(CK).cuda().eval()
pre, post = make_pre_post_processors(pol.config, pretrained_path=CK, preprocessor_overrides={'device_processor': {'device': 'cuda'}})
REN = {'observation.images.top': 'observation.images.camera1', 'observation.images.wrist_left': 'observation.images.camera2', 'observation.images.wrist_right': 'observation.images.camera3'}
ds = LeRobotDataset(REPO)
ep = ds.meta.episodes; errs = []
for e in range(0, len(ep['dataset_from_index']), 7):
    s, t = int(ep['dataset_from_index'][e]), int(ep['dataset_to_index'][e])
    for i in range(s, t - 50, 90):
        it = ds[i]
        obs = {REN.get(k, k): v.unsqueeze(0) for k, v in it.items() if k.startswith('observation.')}; obs['task'] = [TASK]
        with torch.inference_mode():
            pol.reset(); a = post(pol.predict_action_chunk(pre(obs)))[0].float().cpu().numpy()
        gt = np.stack([ds.hf_dataset[i + j]['action'].numpy() if hasattr(ds.hf_dataset[i + j]['action'], 'numpy') else np.array(ds.hf_dataset[i + j]['action']) for j in range(50)])
        errs.append(np.abs(a - gt).mean(0))
errs = np.array(errs)
print(CK.split('/')[-2], 'samples', len(errs), 'mean abs err per joint L', errs.mean(0)[:6].round(1).tolist(), 'R', errs.mean(0)[6:].round(2).tolist())
