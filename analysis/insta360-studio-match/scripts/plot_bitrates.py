from pathlib import Path
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
def rows(label):
    with (ROOT/f'{label}_aligned_seconds.csv').open() as f:return list(csv.reader(f))[1:]
fig,axes=plt.subplots(2,1,figsize=(11,7),layout='constrained')
for ax,labels,title in [(axes[0],['sdk_8k_142_baseline','sdk_8k_154_ai_denoise_fusion'],'8K: same 23-second interval'),(axes[1],['sdk_6k_80_ai_denoise_fusion_013','sdk_6k_50_ai_denoise_fusion_013'],'6K: same 148-second interval from part 013')]:
    r=rows(labels[0]);x=[float(a[0]) for a in r];ax.plot(x,[float(a[1])/1e6 for a in r],label='Studio',color='#171717',linewidth=1.8)
    for label in labels:
        r=rows(label);ax.plot([float(a[0]) for a in r],[float(a[2])/1e6 for a in r],label=label.replace('sdk_','SDK ').replace('_',' '),alpha=.8,linewidth=1.1)
    ax.set(title=title,xlabel='Seconds in aligned comparison interval',ylabel='Video bitrate (Mbps)');ax.grid(alpha=.2);ax.legend(fontsize=8,loc='best')
fig.savefig(ROOT/'results/bitrate_comparison.png',dpi=160)
print('Wrote results/bitrate_comparison.png')
