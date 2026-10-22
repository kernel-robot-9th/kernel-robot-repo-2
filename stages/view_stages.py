"""Show one episode of a stage-labelled dataset in Rerun: cameras, left-arm actions and the stage.

Usage: python stages/view_stages.py [episode] [repo_id]   (default: 0 local/bi_gauze_v5_stages)
Opens a new Rerun window. The 'stage' plot is 0 search / 1 grasp / 2 carry; 'task' shows the sentence.
"""
import sys
import numpy as np
import rerun as rr
from lerobot.datasets.lerobot_dataset import LeRobotDataset

ep = int(sys.argv[1]) if len(sys.argv) > 1 else 0
repo = sys.argv[2] if len(sys.argv) > 2 else 'local/bi_gauze_v5_stages'
ds = LeRobotDataset(repo, episodes=[ep])
rr.init(f'{repo}/episode_{ep}', spawn=True)
names = ['pan', 'lift', 'elbow', 'wrist_flex', 'wrist_roll', 'gripper']
for i in range(len(ds)):
    it = ds[i]
    rr.set_time('frame_index', sequence=int(it['frame_index']))
    for k in ds.meta.camera_keys:
        rr.log(k.split('.')[-1], rr.Image((it[k].permute(1, 2, 0).numpy() * 255).astype(np.uint8)).compress())
    for j, n in enumerate(names):
        rr.log(f'left_action/{n}', rr.Scalars(float(it['action'][j])))
    rr.log('stage', rr.Scalars(int(it['task_index'])))
    rr.log('task', rr.TextLog(it['task']))
print(f'episode {ep}: {len(ds)} frames sent to Rerun')
