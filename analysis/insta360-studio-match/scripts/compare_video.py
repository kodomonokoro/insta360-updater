import argparse,csv,json,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
STUDIO=r'X:\crotchet rest\processed\mp4_本物\VID_20260905_153205_00_004.mp4'
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--offset',type=int,default=89);p.add_argument('--full',action='store_true');a=p.parse_args()
    sdk=ROOT/'outputs'/f'{a.label}.mp4'
    s=json.loads((ROOT/'studio_8k_frames.json').read_text())['frames'];b=json.loads((ROOT/f'{a.label}_frames.json').read_text())['frames'][a.offset:a.offset+len(s)]
    sb=np.zeros(23);bb=np.zeros(23)
    for i,(x,y) in enumerate(zip(s,b)):
        sec=int(i*1001/30000)
        if sec<23: sb[sec]+=int(x['pkt_size'])*8;bb[sec]+=int(y['pkt_size'])*8
    result={'offset_frames':a.offset,'aligned_bitrate_correlation':float(np.corrcoef(sb,bb)[0,1]),'aligned_sdk_video_bitrate':sum(int(x['pkt_size'])*8 for x in b)/(len(s)*1001/30000),'studio_video_bitrate':sum(int(x['pkt_size'])*8 for x in s)/(len(s)*1001/30000)}
    with (ROOT/f'{a.label}_aligned_seconds.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['second','studio_bps','sdk_bps']);w.writerows(zip(range(23),sb,bb))
    for frame in ([0] if a.full else [60,330,630]):
        # One second at each representative location, accurate input seeking.
        t=frame*1001/30000;u=(frame+a.offset)*1001/30000
        graph='[0:v]setpts=PTS-STARTPTS,split=2[s1][s2];[1:v]setpts=PTS-STARTPTS,split=2[b1][b2];[s1][b1]ssim[ss];[s2][b2]psnr[ps]'
        duration=str(len(s)*1001/30000) if a.full else '1.001'
        cmd=['ffmpeg','-hide_banner','-threads','4','-ss',f'{t:.9f}','-t',duration,'-i',STUDIO,'-threads','4','-ss',f'{u:.9f}','-t',duration,'-i',str(sdk),'-filter_complex_threads','2','-filter_complex',graph,'-map','[ss]','-map','[ps]','-an','-f','null','-']
        with (ROOT/'logs'/f'{a.label}_quality_{frame}.log').open('wb') as f: subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
    (ROOT/f'{a.label}_comparison.json').write_text(json.dumps(result,indent=2))
    print(result)
