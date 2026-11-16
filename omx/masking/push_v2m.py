from pathlib import Path
from lerobot.datasets.lerobot_dataset import LeRobotDataset
root = Path.home() / '.cache/huggingface/lerobot/jaewoo112/bi_gauze_v2_masked'
(root / '.masked_files').unlink(missing_ok=True)
ds = LeRobotDataset('jaewoo112/bi_gauze_v2_masked', root=root)
ds[0]; ds[len(ds) - 1]
print('LOAD OK', ds.num_episodes, ds.num_frames, flush=True)
ds.push_to_hub(private=True)
print('PUSHED', flush=True)
