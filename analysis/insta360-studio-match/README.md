# Insta360 Studio / MediaSDK comparison

8Kと6K後半の比較調査結果。元ファイルは読み取り専用で扱い、生成動画は `outputs/`、ログは `logs/` に保存した。
結論と検証範囲は [results/comparison.md](results/comparison.md)、実測表は [results/measurements.md](results/measurements.md)。
8Kは「ほぼできる」、6Kは位置ずれとビットレート変動が残るため「まだ判断不能」。6K前半の新規変換は未実施。

## 入力

- 8K INSV: `D:\DCIM\Camera01\VID_20260905_153205_00_004.insv`
- 8K Studio: `X:\crotchet rest\processed\mp4_本物\VID_20260905_153205_00_004.mp4`
- 6K INSV: `D:\DCIM\Camera01\VID_20260906_162319_00_012.insv` と `_013.insv`
- 6K Studio: `X:\crotchet rest\processed\mp4_本物\VID_20260906_162319_00_012.mp4`
- SDK: `../../sdk/MediaSDK/`、実行時バージョン3.1.5。
- インストール済みStudio: 6.0.4.0。既存MP4生成時のバージョンは別途未確認。
- GPU: RTX 4070、ドライバ591.86。ffprobe/ffmpeg: 8.0.1。

ユーザーによると360度動画以外はStudioのデフォルト。スクリーンショットは8K 154、6K 80、両方29.97fps/H.265/ビットレート「オリジナル」。既存MP4生成時の完全な設定記録ではない。

## 再現

Python 3.12、比較処理にはnumpyを使用。ffprobe/ffmpegをPATHに配置する。

```powershell
python scripts/probe_video.py '<video path>' '<label>' --frames
python scripts/run_sdk.py sdk_8k_154_flowstate
python scripts/align_video.py '<Studio MP4>' 'outputs/sdk_8k_154_flowstate.mp4' sdk_8k_154_flowstate
python scripts/compare_video.py sdk_8k_154_flowstate --offset 89
```

`run_sdk.py` は同名出力があれば停止する。ラベルを変えて実行する。
`probe_video.py` は既存の同ラベル解析結果を更新する。
`compare_video.py` は8K素材専用。3区間各30フレームをフル解像度でSSIM/PSNR比較する。
1秒ビットレート統計はPTS基準。末尾の不完全な1秒は統計から除外する。
時間合わせ用160×80グレースケールは解析専用であり、最終出力への中間素材には使用しない。

## 判明した重要事項

- Studio 8Kは705フレーム、23.5235秒。元INSVは各レンズ883フレーム、29.462767秒。
- SDK 8Kは884フレーム、29.496133秒。Studio先頭はSDK frame 89に最もよく一致する。
- Studio 8KとSDK試験はGOP 30、I/Pのみ。平均ビットレートだけで同等とは判断しない。
- 既存の `processed/mp4` と `raw` の6K名動画は1920×960/H.264。目標の6K/H.265ではない。
- 6Kの2本は時間分割。各ファイルに2つのレンズ映像ストリームがある。SDKの複数入力はレンズ分割用なので、2本を単純に `-inputs` に並べて連結扱いにしない。
- Studioログは通常のテキストとして読めず、書き出し設定の根拠には使用していない。

詳細と最終判定は `results/comparison.md` にまとめる。

## 6Kと集計の再現

```powershell
python scripts/run_sdk.py sdk_6k_new --input 'D:\DCIM\Camera01\VID_20260906_162319_00_013.insv' --size 6016x3008 --bitrate 50000000 --stitch aistitch --denoise --fusion
python scripts/probe_video.py outputs/sdk_6k_new.mp4 sdk_6k_new --frames
python scripts/compare_6k.py sdk_6k_new --full
python scripts/analyze_headers.py
python scripts/build_measurements.py
python scripts/plot_bitrates.py
python scripts/validate_results.py
```

`align_6k.py` でStudioとの対応を3か所確認。`diagnose_6k.py` と `compare_6k.py --spatial-diagnostic` は位置ずれの診断専用。
`probe_video.py --frames --reuse-frames` は保存済みの完全なframes.jsonを再集計する。
図の生成にはmatplotlibも使用する。
