import pathlib,re,json,hashlib
root=pathlib.Path(__file__).resolve().parents[3]
p=root/'sdk/MediaSDK'
files=[p/'bin/MediaSDKTest.exe',p/'bin/MediaSDK.dll',p/'example/main.cc',p/'include/stitcher/ins_stitcher.h']
out={str(f.relative_to(root)):{'size':f.stat().st_size,'sha256':hashlib.file_digest(f.open('rb'),'sha256').hexdigest()} for f in files}
src=files[2].read_text(encoding='utf-8-sig')
out['parsed_cli_options']=sorted(set(re.findall(r'std::string\("(-[^"]+)"\)',src)))
(root/'analysis/insta360-studio-match/sdk_inventory.json').write_text(json.dumps(out,indent=2))
print(out['parsed_cli_options'])
