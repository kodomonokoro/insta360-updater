import argparse, json, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT.parents[1]/'sdk/MediaSDK/bin/MediaSDKTest.exe'
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--bitrate',default='154000000');p.add_argument('--stitch',default='optflow');p.add_argument('--no-flowstate',action='store_true');p.add_argument('--denoise',action='store_true');p.add_argument('--fusion',action='store_true');p.add_argument('--input',default=r'D:\DCIM\Camera01\VID_20260905_153205_00_004.insv');p.add_argument('--size',default='7680x3840');p.add_argument('--log-level',default='info');a=p.parse_args()
    output=ROOT/'outputs'/f'{a.label}.mp4'
    if output.exists(): raise SystemExit('Output already exists; choose a new label.')
    cmd=[str(EXE),'-inputs',a.input,'-output',str(output),'-output_size',a.size,'-enable_h265_encoder','-bitrate',a.bitrate,'-stitch_type',a.stitch,'--log_level',a.log_level]
    if not a.no_flowstate: cmd+=['-enable_flowstate']
    if a.denoise: cmd+=['-enable_denoise']
    if a.fusion: cmd+=['-enable_stitchfusion']
    start=time.time()
    with (ROOT/'logs'/f'{a.label}.log').open('wb') as f: result=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
    record={'command':cmd,'returncode':result.returncode,'elapsed_seconds':time.time()-start,'output_exists':output.exists()}
    (ROOT/'logs'/f'{a.label}_command.json').write_text(json.dumps(record,indent=2))
    print(record)
