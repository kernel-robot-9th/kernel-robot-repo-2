"""Run the v4 SmolVLA open-loop on recorded frames (no robot): what does it predict from the
training data's frames vs today's eval frames? Prints left shoulder_lift over the 50-step chunk."""
import sys, torch, numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors
CK = sys.argv[1] if len(sys.argv) > 1 else '/home/omen/main_project/outputs/train/smolvla_bi_gauze_v4/checkpoints/last/pretrained_model'
TASK = 'pick and place aligned green gauze'
pol = SmolVLAPolicy.from_pretrained(CK).cuda().eval()
pre, post = make_pre_post_processors(pol.config, pretrained_path=CK, preprocessor_overrides={'device_processor': {'device': 'cuda'}})
REN = {'observation.images.top': 'observation.images.camera1', 'observation.images.wrist_left': 'observation.images.camera2',
       'observation.images.wrist_right': 'observation.images.camera3'}
def chunk(item):
    obs = {REN.get(k, k): v.unsqueeze(0) for k, v in item.items() if k.startswith('observation.')}
    obs['task'] = [TASK]
    with torch.inference_mode():
        o = pre(obs); pol.reset()
        a = pol.predict_action_chunk(o)            # (1, 50, 12) normalised
        a = post(a)
    return a[0].float().cpu().numpy()
tr = LeRobotDataset('jaewoo112/bi_gauze_v4')
ev = LeRobotDataset('local/eval_bi_gauze_v4_last_103446')
ev2 = LeRobotDataset('local/eval_bi_gauze_v4_last_103624')
def show(name, ds, idx):
    it = ds[idx]; c = chunk(it)
    gt = ''
    if 'action' in it and idx + 50 <= len(ds):
        gt = ' | GT ' + str([round(float(ds[idx + j]['action'][1])) for j in (0, 10, 20, 30, 40, 49)])
    print(f'{name:22s} f{idx:4d} state lift {float(it["observation.state"][1]):5.0f} | pred lift', np.round(c[[0,10,20,30,40,49], 1]).tolist(), gt)
ep = tr.meta.episodes
for e in (0, 10, 30):
    s = int(ep['dataset_from_index'][e])
    for off in (0, 60, 120): show(f'train ep{e}', tr, s + off)
for off in (0, 60, 120, 300): show('eval 103446 (exp90)', ev, off)
for off in (0, 60, 120): show('eval 103624 (auto)', ev2, off)
