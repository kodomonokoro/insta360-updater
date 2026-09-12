import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for label,path in [('studio_8k',r'X:\crotchet rest\processed\mp4_本物\VID_20260905_153205_00_004.mp4'),('studio_6k',r'X:\crotchet rest\processed\mp4_本物\VID_20260906_162319_00_012.mp4'),('sdk_8k_154_ai_denoise_fusion',str(ROOT/'outputs/sdk_8k_154_ai_denoise_fusion.mp4'))]:
    with (ROOT/'logs'/f'{label}_headers.log').open('wb') as f:
        subprocess.run(['ffmpeg','-hide_banner','-i',path,'-map','0:v:0','-c:v','copy','-bsf:v','trace_headers','-frames:v','1','-f','null','-'],stdout=f,stderr=subprocess.STDOUT,check=True)
