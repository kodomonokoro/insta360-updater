import argparse, collections, csv, json, math, statistics, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run_json(args, target):
    with target.open('w', encoding='utf-8') as out, target.with_suffix('.stderr.txt').open('w', encoding='utf-8') as err:
        subprocess.run(['ffprobe', '-v', 'error', *args, '-of', 'json'], stdout=out, stderr=err, check=True)
    return json.loads(target.read_text(encoding='utf-8'))

def probe(path, label, frames=False, reuse_frames=False):
    data = run_json(['-show_format', '-show_streams', str(path)], ROOT / f'{label}_ffprobe.json')
    v = next(s for s in data['streams'] if s['codec_type'] == 'video')
    print(label, {k:v.get(k) for k in ['codec_name','width','height','r_frame_rate','duration','bit_rate','nb_frames']}, flush=True)
    if not frames: return
    frame_path=ROOT / f'{label}_frames.json'
    data = json.loads(frame_path.read_text(encoding='utf-8')) if reuse_frames else run_json(['-select_streams','v:0','-threads','4','-show_frames','-show_entries','frame=best_effort_timestamp_time,pict_type,pkt_size,key_frame',str(path)], frame_path)
    rows = data['frames']
    with (ROOT / f'{label}_frames.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['best_effort_timestamp_time','pict_type','pkt_size','key_frame'],extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    sizes=collections.defaultdict(list); seconds=collections.defaultdict(int); keys=[]; iframe=[]
    for i,r in enumerate(rows):
        size=int(r.get('pkt_size',0)); sizes[r['pict_type']].append(size)
        seconds[math.floor(float(r['best_effort_timestamp_time']))] += size*8
        if r['key_frame']: keys.append(i)
        if r['pict_type']=='I': iframe.append(i)
    duration=float(v['duration']); full=[seconds[i] for i in range(math.floor(duration))]
    summary={'frame_count':len(rows),'types':{k:{'count':len(x),'mean_bytes':statistics.mean(x)} for k,x in sizes.items()},'keyframe_indices':keys,'gop_lengths':dict(collections.Counter(b-a for a,b in zip(keys,keys[1:]))),'i_intervals':dict(collections.Counter(b-a for a,b in zip(iframe,iframe[1:]))),'full_second_bitrate':{'min':min(full),'max':max(full),'mean':statistics.mean(full),'cv':statistics.pstdev(full)/statistics.mean(full),'mean_absolute_step_fraction':statistics.mean(abs(b-a) for a,b in zip(full,full[1:]))/statistics.mean(full)},'note':'1-second bins use presentation timestamps; final partial second excluded from statistics.'}
    (ROOT / f'{label}_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    with (ROOT / f'{label}_seconds.csv').open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['second','bits','complete_second']); w.writerows((s,b,s+1<=duration) for s,b in sorted(seconds.items()))
    print(label,{k:v for k,v in summary.items() if k!='keyframe_indices'},flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('path'); p.add_argument('label'); p.add_argument('--frames',action='store_true'); p.add_argument('--reuse-frames',action='store_true'); a=p.parse_args(); probe(Path(a.path),a.label,a.frames,a.reuse_frames)
