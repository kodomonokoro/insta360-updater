import argparse,csv,json,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
STUDIO=r'X:\crotchet rest\processed\mp4_本物\VID_20260906_162319_00_012.mp4'
p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--full',action='store_true');p.add_argument('--spatial-diagnostic',action='store_true');a=p.parse_args()
offset=53940
s=json.loads((ROOT/'studio_6k_frames.json').read_text())['frames'][offset:]
b=json.loads((ROOT/f'{a.label}_frames.json').read_text())['frames'][:len(s)]
duration=len(s)*1001/30000; n=int(duration);x=np.zeros(n);y=np.zeros(n)
for i,(sf,bf) in enumerate(zip(s,b)):
    sec=int(i*1001/30000)
    if sec<n:x[sec]+=int(sf['pkt_size'])*8;y[sec]+=int(bf['pkt_size'])*8
def stats(rows,seconds):
    return {'bitrate':sum(int(f['pkt_size'])*8 for f in rows)/duration,'second_min':float(seconds.min()),'second_max':float(seconds.max()),'second_mean':float(seconds.mean()),'second_cv':float(seconds.std()/seconds.mean()),'types':{t:{'count':sum(f['pict_type']==t for f in rows),'mean_bytes':float(np.mean([int(f['pkt_size']) for f in rows if f['pict_type']==t])) if any(f['pict_type']==t for f in rows) else 0} for t in ['I','P','B']}}
result={'studio_start_frame':offset,'frame_count':len(s),'duration':duration,'studio':stats(s,x),'sdk':stats(b,y),'correlation':float(np.corrcoef(x,y)[0,1])}
with (ROOT/f'{a.label}_aligned_seconds.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['second_in_013','studio_bps','sdk_bps']);w.writerows(zip(range(n),x,y))
for frame in ([0] if a.full else [300,2100,3900]):
    t=(offset+frame)*1001/30000;u=frame*1001/30000;length=str(duration) if a.full else '1.001'
    left='extractplanes=y,crop=6015:3008:1:0:exact=1,' if a.spatial_diagnostic else ''
    right='extractplanes=y,crop=6015:3008:0:0:exact=1,' if a.spatial_diagnostic else ''
    graph=f'[0:v]{left}setpts=PTS-STARTPTS,split=2[s1][s2];[1:v]{right}setpts=PTS-STARTPTS,split=2[b1][b2];[s1][b1]ssim[ss];[s2][b2]psnr[ps]'
    cmd=['ffmpeg','-hide_banner','-threads','4','-ss',f'{t:.9f}','-t',length,'-i',STUDIO,'-threads','4','-ss',f'{u:.9f}','-t',length,'-i',str(ROOT/'outputs'/f'{a.label}.mp4'),'-filter_complex_threads','2','-filter_complex',graph,'-map','[ss]','-map','[ps]','-an','-f','null','-']
    suffix='_spatial_luma' if a.spatial_diagnostic else ''
    with (ROOT/'logs'/f'{a.label}_quality_{frame}{suffix}.log').open('wb') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
(ROOT/f'{a.label}_comparison.json').write_text(json.dumps(result,indent=2))
print(result)
