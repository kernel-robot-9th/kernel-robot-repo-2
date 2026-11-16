"""Which input makes the model stall? Take an eval frame where the arm stalled (lift ~0) and a training
frame at the same phase (lift ~1, about to reach); swap one input at a time and see the predicted lift."""
import sys, torch, numpy as np, cv2
sys.argv=[sys.argv[0]]
exec(open('analysis/regress/offline_pred.py').read().split('tr = LeRobotDataset')[0])
from lerobot.datasets.lerobot_dataset import LeRobotDataset
tr = LeRobotDataset('jaewoo112/bi_gauze_v4'); ev = LeRobotDataset('local/eval_bi_gauze_v4_last_103446')
s10 = int(tr.meta.episodes['dataset_from_index'][10])
T = tr[s10 + 120]; E = ev[300]
print('train state', np.round(T['observation.state'].numpy()).tolist()); print('eval  state', np.round(E['observation.state'].numpy()).tolist())
EK = {'observation.images.top':'observation.images.camera1','observation.images.wrist_left':'observation.images.camera2','observation.images.wrist_right':'observation.images.camera3'}
def run(lbl, d):
    print(f'{lbl:34s}', np.round(chunk(d)[[0,10,20,30,40,49],1]).tolist())
Tn = {EK.get(k,k):v for k,v in T.items() if k.startswith('observation.')}
En = {k:v for k,v in E.items() if k.startswith('observation.')}
run('train frame', Tn); run('eval frame', En)
for k in ['observation.state','observation.images.camera1','observation.images.camera2','observation.images.camera3']:
    d = dict(En); d[k] = Tn[k]; run('eval + train '+k.split('.')[-1], d)
    d = dict(Tn); d[k] = En[k]; run('train + eval '+k.split('.')[-1], d)
row = [ (x.permute(1,2,0).numpy()*255).astype(np.uint8) for x in (Tn['observation.images.camera1'],Tn['observation.images.camera2'],Tn['observation.images.camera3'])]
row2= [ (x.permute(1,2,0).numpy()*255).astype(np.uint8) for x in (En['observation.images.camera1'],En['observation.images.camera2'],En['observation.images.camera3'])]
cv2.imwrite('/home/omen/main_project/stall_compare.jpg', cv2.cvtColor(np.vstack([np.hstack(row),np.hstack(row2)]),cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,80])
