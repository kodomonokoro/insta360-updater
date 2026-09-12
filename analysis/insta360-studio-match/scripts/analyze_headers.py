import json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
result={}
labels=['studio_8k','studio_6k']+[p.stem for p in (ROOT/'outputs').glob('*.mp4') if (ROOT/f'{p.stem}_ffprobe.json').exists()]
for label in labels:
    log=ROOT/'logs'/f'{label}_headers.log'
    if not log.exists() or 'bit_rate_value_minus1' not in log.read_text(encoding='utf-8',errors='replace'):
        with log.open('wb') as f:
            subprocess.run(['ffmpeg','-hide_banner','-i',str(ROOT/'outputs'/f'{label}.mp4'),'-map','0:v:0','-c:v','copy','-bsf:v','trace_headers','-frames:v','1','-f','null','-'],stdout=f,stderr=subprocess.STDOUT,check=True)
    fields={}
    for line in log.read_text(encoding='utf-8',errors='replace').splitlines():
        m=re.search(r'\]\s+\d+\s+(\S+)\s+[01]+\s+=\s+(-?\d+)',line)
        if m: fields.setdefault(m[1],int(m[2]))
    if 'bit_rate_value_minus1[0]' not in fields: continue
    result[label]={'hrd_bitrate_bps':(fields['bit_rate_value_minus1[0]']+1)*2**(6+fields['bit_rate_scale']),'hrd_cpb_bits':(fields['cpb_size_value_minus1[0]']+1)*2**(4+fields['cpb_size_scale']),'cbr_flag':fields['cbr_flag[0]'],'fields':fields}
(ROOT/'headers_summary.json').write_text(json.dumps(result,indent=2))
print({k:{f:v for f,v in d.items() if f!='fields'} for k,d in result.items()})
