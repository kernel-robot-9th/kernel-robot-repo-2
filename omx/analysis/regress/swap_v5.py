import sys, torch, numpy as np, glob, os
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors
CK='outputs/train/smolvla_bi_gauze_v5/checkpoints/032000/pretrained_model'; TASK='pick and place green gauze from the row'
pol=SmolVLAPolicy.from_pretrained(CK).cuda().eval()
pre,post=make_pre_post_processors(pol.config,pretrained_path=CK,preprocessor_overrides={'device_processor':{'device':'cuda'}})
REN={'observation.images.top':'observation.images.camera1','observation.images.wrist_left':'observation.images.camera2','observation.images.wrist_right':'observation.images.camera3'}
def chunk(d):
    o=dict(d); o['task']=[TASK]
    with torch.inference_mode(): pol.reset(); return post(pol.predict_action_chunk(pre(o)))[0].float().cpu().numpy()
tr=LeRobotDataset('jaewoo112/bi_gauze_v5'); ev=LeRobotDataset('local/eval_bi_gauze_v5_032000_111318')
s0=int(tr.meta.episodes['dataset_from_index'][0]); s7=int(tr.meta.episodes['dataset_from_index'][7])
def get(ds,i,ren): it=ds[i]; return {(REN.get(k,k) if ren else k):v.unsqueeze(0) for k,v in it.items() if k.startswith('observation.')}
J=[0,10,20,30,49]
def show(lbl,d):
    c=chunk(d); print(f'{lbl:30s} pan',c[J,0].round(0).tolist(),' lift',c[J,1].round(0).tolist(),' elb',c[J,2].round(0).tolist(),' grip',c[J,5].round(0).tolist())
for nm,i in [('train ep0 f231',s0+231),('train ep7 f181',s7+181)]:
    T=get(tr,i,True); print(nm,'state',T['observation.state'][0,:6].numpy().round(0).tolist()); show(nm,T)
E=get(ev,90,False); print('eval 3s state',E['observation.state'][0,:6].numpy().round(0).tolist()); show('eval 3s',E)
T=get(tr,s0+231,True)
for k in ['observation.state','observation.images.camera1','observation.images.camera2','observation.images.camera3']:
    d=dict(E); d[k]=T[k]; show('eval + train '+k.split('.')[-1],d)
