import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def video(label): return next(s for s in read(ROOT/f'{label}_ffprobe.json')['streams'] if s['codec_type']=='video')
labels=['studio_8k','studio_6k']+[f.name.removesuffix('_summary.json') for f in sorted(ROOT.glob('sdk_*_summary.json')) if f.name!='sdk_inventory_summary.json']
out=['# 実測表','', '全長値と時間合わせ済みの値を区別する。6KのStudioは全長、SDKは末尾の013素材（約151秒）。', '', '| 対象 | 解像度 | profile / level | pix_fmt / range | fps | 秒数 | 平均Mbps | GOP | B数 | I平均bytes | P平均bytes | 秒bps min/max/mean (Mbps) | CV | 平均隣接変動/平均 |','|---|---|---|---|---|---:|---:|---|---:|---:|---:|---|---:|---:|']
for label in labels:
    f=ROOT/f'{label}_summary.json'
    if not f.exists(): continue
    v=video(label);s=read(f);types=s['types'];r=s['full_second_bitrate']
    out.append(f"|{label}|{v['width']}×{v['height']}|{v['profile']} / {v['level']}|{v['pix_fmt']} / {v.get('color_range')}|{v['r_frame_rate']}|{float(v['duration']):.3f}|{int(v['bit_rate'])/1e6:.3f}|{s['gop_lengths']}|{types.get('B',{}).get('count',0)}|{types['I']['mean_bytes']:.1f}|{types['P']['mean_bytes']:.1f}|{r['min']/1e6:.3f} / {r['max']/1e6:.3f} / {r['mean']/1e6:.3f}|{r['cv']:.4f}|{r['mean_absolute_step_fraction']:.4f}|")
out += ['', '## 8K：時間合わせ後の比較', '', '| 試験 | 対応区間Mbps | 秒単位bitrate相関 | PSNR早期 / 中間 / 後期 (dB) | SSIM早期 / 中間 / 後期 | 全705フレームPSNR / SSIM |','|---|---:|---:|---|---|---|']
for f in sorted(ROOT.glob('sdk_8k*_comparison.json')):
    label=f.name.removesuffix('_comparison.json');d=read(f);ps=[];ss=[]
    for frame in [60,330,630,0]:
        log=ROOT/'logs'/f'{label}_quality_{frame}.log';t=log.read_text(errors='replace') if log.exists() else ''
        a=re.search(r'average:([0-9.]+)',t);b=re.search(r'All:([0-9.]+)',t);ps.append(float(a[1]) if a else None);ss.append(float(b[1]) if b else None)
    out.append(f"|{label}|{d['aligned_sdk_video_bitrate']/1e6:.3f}|{d['aligned_bitrate_correlation']:.4f}|"+' / '.join(f'{x:.3f}' if x else '—' for x in ps[:3])+'|'+' / '.join(f'{x:.6f}' if x else '—' for x in ss[:3])+'|'+(f'{ps[3]:.3f} / {ss[3]:.6f}' if ps[3] else '—')+'|')
out += ['', 'Studio 8K基準：157.664105 Mbps。対応するSDK区間はframe 89から705フレーム。', '秒ごとの相関は23個の完全な1秒区間のPearson相関。画質指標はequirectangular全画素。', '']
out += ['## 6K：後半013の共通区間', '', '| 試験 | Studio / SDK Mbps | 秒単位相関 | PSNR 10秒 / 70秒 / 130秒 (dB) | SSIM 同区間 | 全4437フレーム PSNR / SSIM |', '|---|---|---:|---|---|---|']
for f in sorted(ROOT.glob('sdk_6k*_comparison.json')):
    label=f.name.removesuffix('_comparison.json');d=read(f);ps=[];ss=[]
    for frame in [300,2100,3900,0]:
        log=ROOT/'logs'/f'{label}_quality_{frame}.log';t=log.read_text(errors='replace') if log.exists() else ''
        a=re.search(r'average:([0-9.]+)',t);b=re.search(r'All:([0-9.]+)',t);ps.append(float(a[1]) if a else None);ss.append(float(b[1]) if b else None)
    out.append(f"|{label}|{d['studio']['bitrate']/1e6:.3f} / {d['sdk']['bitrate']/1e6:.3f}|{d['correlation']:.4f}|"+' / '.join(f'{x:.3f}' if x else '—' for x in ps[:3])+'|'+' / '.join(f'{x:.6f}' if x else '—' for x in ss[:3])+'|'+(f'{ps[3]:.3f} / {ss[3]:.6f}' if ps[3] else '—')+'|')
out += ['', 'GOP 30フレーム = 1.001秒。B-frameは全試験で0のためB平均サイズは該当なし。', '1画素補正診断はこの未加工出力の画質表には混在させない。', '']
(ROOT/'results/measurements.md').write_text('\n'.join(out),encoding='utf-8')
print('Wrote results/measurements.md')
