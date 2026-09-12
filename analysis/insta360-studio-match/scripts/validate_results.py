import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
checks=[]
for path in ROOT.glob('*_summary.json'):
    label=path.name.removesuffix('_summary.json')
    if not (ROOT/f'{label}_frames.csv').exists():continue
    summary=json.loads(path.read_text(encoding='utf-8'))
    probe=json.loads((ROOT/f'{label}_ffprobe.json').read_text(encoding='utf-8'))
    stream=next(s for s in probe['streams'] if s['codec_type']=='video')
    with (ROOT/f'{label}_frames.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==summary['frame_count']==int(stream['nb_frames']),label
    assert sum(t['count'] for t in summary['types'].values())==len(rows),label
    bitrate=sum(int(r['pkt_size'])*8 for r in rows)/float(stream['duration'])
    assert abs(bitrate-int(stream['bit_rate']))<10,(label,bitrate,stream['bit_rate'])
    assert stream['r_frame_rate']=='30000/1001',label
    checks.append({'label':label,'frames':len(rows),'bitrate_error_bps':bitrate-int(stream['bit_rate'])})
originals={r'D:\DCIM\Camera01\VID_20260905_153205_00_004.insv':586600797,r'D:\DCIM\Camera01\VID_20260906_162319_00_012.insv':18305700155,r'D:\DCIM\Camera01\VID_20260906_162319_00_013.insv':1547358561,r'X:\crotchet rest\processed\mp4_本物\VID_20260905_153205_00_004.mp4':463999961,r'X:\crotchet rest\processed\mp4_本物\VID_20260906_162319_00_012.mp4':12210915841}
for p,size in originals.items():assert Path(p).stat().st_size==size,p
result={'checks':checks,'original_sizes_unchanged':True,'note':'Size checks do not substitute for before/after content hashes. No source mutation commands were used.'}
(ROOT/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('Validated',len(checks),'frame datasets and 5 original sizes.')
