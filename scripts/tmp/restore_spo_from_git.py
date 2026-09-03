# Issue #90 の副作用でディスクから消えた SPOアップロード用.xlsx を  
# git 履歴(3cd88bd)からバイナリ復元する。  
# 注意: git show は読み取り専用。index やディスク上の他ファイルには一切触らない。  
import hashlib  
import pathlib  
import subprocess  
import sys  
  
TARGET = "SPOアップロード用.xlsx"  
REV = "3cd88bdd6318e4d487c6157203d461452164df97"  
EXPECTED_BLOB = "4981766677ee793e9933bdddccb55e1f7708292b"  
EXPECTED_SIZE = 14610  
  
dst = pathlib.Path(TARGET)  
if dst.exists():  
    print(f"STOP: {TARGET} は既に存在します。上書きしません。")  
    sys.exit(1)  
  
r = subprocess.run(["git", "show", f"{REV}:{TARGET}"], capture_output=True)  
if r.returncode != 0:  
    print("STOP: git show に失敗しました。")  
    print(r.stderr.decode("utf-8", errors="replace"))  
    sys.exit(1)  
  
data = r.stdout  
print(f"取得サイズ : {len(data)} bytes (期待 {EXPECTED_SIZE})")  
  
blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()  
print(f"blob sha1  : {blob} (期待 {EXPECTED_BLOB})")  
  
if len(data) != EXPECTED_SIZE or blob != EXPECTED_BLOB:  
    print("STOP: サイズまたは blob ハッシュが不一致のため書き込みを中止します。")  
    sys.exit(1)  
  
dst.write_bytes(data)  
print(f"WROTE      : {dst.resolve()}")  
print(f"SHA256     : {hashlib.sha256(data).hexdigest()}")  
