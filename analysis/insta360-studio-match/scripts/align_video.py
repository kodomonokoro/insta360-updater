import json, subprocess, sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def decode(path,label):
    target=ROOT/f'{label}_160x80.gray'
    if not target.exists():
        subprocess.run(['ffmpeg','-v','error','-threads','4','-i',str(path),'-map','0:v:0','-vf','scale=160:80','-pix_fmt','gray','-fps_mode','passthrough','-f','rawvideo',str(target)],check=True)
    return np.fromfile(target,dtype=np.uint8).reshape(-1,80,160).astype(np.float32)
if __name__=='__main__':
    a=decode(sys.argv[1],'studio_8k'); b=decode(sys.argv[2],sys.argv[3])
    results=[]
    for offset in range(len(b)-len(a)+1):
        mse=float(np.mean((a[::10]-b[offset:offset+len(a):10])**2));results.append((mse,offset))
    results.sort(); best=results[0][1]
    report={'sdk_frame_offset':best,'offset_seconds':best*1001/30000,'top_candidates':results[:10],'per_frame_mse':np.mean((a-b[best:best+len(a)])**2,axis=(1,2)).tolist(),'note':'Low resolution grayscale alignment, not a full resolution quality score.'}
    (ROOT/f'{sys.argv[3]}_alignment.json').write_text(json.dumps(report,indent=2))
    print({k:v for k,v in report.items() if k!='per_frame_mse'})
