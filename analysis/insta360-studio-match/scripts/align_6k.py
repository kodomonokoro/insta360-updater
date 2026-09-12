import json,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
STUDIO=r'X:\crotchet rest\processed\mp4_本物\VID_20260906_162319_00_012.mp4'
SDK=ROOT/'outputs/sdk_6k_80_ai_denoise_fusion_013.mp4'
def raw(path,start,duration):
    cmd=['ffmpeg','-v','error','-threads','4','-ss',str(start),'-i',str(path),'-t',str(duration),'-vf','scale=160:80','-pix_fmt','gray','-fps_mode','passthrough','-f','rawvideo','-']
    return np.frombuffer(subprocess.check_output(cmd),np.uint8).reshape(-1,80,160).astype(np.float32)
out=[]
for sdk_frame in [300,2100,3900]:
    t=sdk_frame*1001/30000
    # Candidate correspondence includes both no start trim and 89-frame trim.
    first=53940+sdk_frame-180
    ref=raw(STUDIO,first*1001/30000,12.012)
    test=raw(SDK,t,0.033366667)[0]
    scores=np.mean((ref-test)**2,axis=(1,2)); best=int(scores.argmin())
    out.append({'sdk_frame':sdk_frame,'studio_frame':first+best,'studio_minus_sdk_frames':first+best-sdk_frame,'mse':float(scores[best]),'next_best_mse':float(np.sort(scores)[1])})
(ROOT/'sdk_6k_alignment.json').write_text(json.dumps(out,indent=2))
print(out)
