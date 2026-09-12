import json,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def raw(path,t):
    return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-threads','4','-ss',str(t),'-i',str(path),'-frames:v','1','-pix_fmt','gray','-f','rawvideo','-']),np.uint8).reshape(3008,6016).astype(np.float32)
a=raw(r'X:\crotchet rest\processed\mp4_本物\VID_20260906_162319_00_012.mp4',1869.868)
b=raw(ROOT/'outputs/sdk_6k_50_ai_denoise_fusion_013.mp4',70.07)
out={'mean_signed_difference':float((a-b).mean()),'mae':float(np.abs(a-b).mean()),'regions':[]}
for name,x,y in [('ceiling',2500,200),('people',2500,1300),('left_seam',0,1300),('right_people',5000,1300),('floor',2500,2200)]:
    w=h=512;aa=a[y:y+h,x:x+w];bb=b[y:y+h,x:x+w]
    mse=float(np.mean((aa-bb)**2));scores=[]
    for dy in range(-3,4):
        for dx in range(-3,4):
            scores.append((float(np.mean((aa[4:-4,4:-4]-bb[4+dy:h-4+dy,4+dx:w-4+dx])**2)),dx,dy))
    down=[]
    for s in [1,2,4,8]:
        ad=aa.reshape(h//s,s,w//s,s).mean((1,3));bd=bb.reshape(h//s,s,w//s,s).mean((1,3));down.append(float(10*np.log10(255**2/np.mean((ad-bd)**2))))
    out['regions'].append({'name':name,'x':x,'y':y,'mse':mse,'best_shift':min(scores),'block_average_psnr_1_2_4_8':down})
(ROOT/'sdk_6k_spatial_diagnostic.json').write_text(json.dumps(out,indent=2));print(out)
