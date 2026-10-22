import glob, av, cv2, numpy as np, pandas as pd
H='/home/omen/.cache/huggingface/lerobot/'
def first(root, key, k=5):
    f=sorted(glob.glob(f'{root}/videos/{key}/chunk-000/*.mp4'))[0]
    with av.open(f) as c:
        s=c.streams.video[0]; s.thread_count=2
        for i,fr in enumerate(c.decode(s)):
            if i==k: return fr.to_ndarray(format='rgb24')
def states(root):
    d=pd.concat(pd.read_parquet(f) for f in glob.glob(root+'/data/*/*.parquet')).sort_values(['episode_index','frame_index'])
    return d
tr=H+'jaewoo112/bi_gauze_v4'; ev=H+'local/eval_bi_gauze_v4_last_103624'; old=H+'local/eval_bi_gauze_032000_120703'; oldtr=H+'local/bi_gauze'
a=first(tr,'observation.images.top'); b=first(ev,'observation.images.camera1')
g=lambda x: cv2.cvtColor(x,cv2.COLOR_RGB2GRAY).astype(np.float32)
(dx,dy),_=cv2.phaseCorrelate(g(a),g(b)); print('v4 eval vs train top shift', round(dx,1), round(dy,1), 'mean bright train/eval', round(a.mean(),1), round(b.mean(),1))
lab=lambda x,t: cv2.putText(x.copy(),t,(6,22),0,0.7,(255,255,0),2)
o=first(old,'observation.images.camera1'); ot=first(oldtr,'observation.images.top')
img=np.vstack([np.hstack([lab(a,'v4 train'),lab(b,'v4 eval today'),lab((0.5*a+0.5*b).astype(np.uint8),'overlay')]),
               np.hstack([lab(ot,'bi_gauze train (worked)'),lab(o,'bi_gauze eval 10-15 (grasped)'),lab((0.5*ot+0.5*o).astype(np.uint8),'overlay')])])
cv2.imwrite('/home/omen/main_project/regression_compare.jpg',cv2.cvtColor(img,cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,80])
T=states(tr); E=states(ev)
ts=np.stack(T[T.frame_index==0]['observation.state'].values); es=np.stack(E['observation.state'].values)
print('train start mean L', ts.mean(0)[:6].round(0).tolist(),' R', ts.mean(0)[6:].round(0).tolist())
print('eval  start      L', es[0,:6].round(0).tolist(),' R', es[0,6:].round(0).tolist())
ta=np.stack(T['observation.state'].values)
print('left lift max: train p95', np.percentile(ta[:,1],95).round(0), 'eval max', es[:,1].max().round(0), '| grip eval range', es[:,5].min().round(0), es[:,5].max().round(0))
print('eval lift over time', es[::60,1].round(0).tolist())
