# moon-sweepers-save-editor
《Moon Sweepers》存档修改器 | Team Wallet / Dollars Editor

想要自己修改DIY的拉取原文件，想要下载即用的直接拉取exe就行了
Want to customize it yourself? Pull the source files. Want a plug-and-play version? Just download the EXE.
————————————————————————————————————————
使用前请关闭游戏，并且确保Steam云存档关闭，不然steam云存档会顶掉你改好的存档
Before using it, close the game and make sure Steam Cloud is turned off for this game — otherwise Steam Cloud can overwrite your edited save.
————————————————————————————————————————
告知原因：
由于作者忘记写英文版的了，现在 EXE 运行后只有中文，BAT 也一样。以下是中英对照版本，方便非中文用户理解。

Reason:
The author forgot to include an English version, so the EXE and BAT currently show Chinese only. Below is a Chinese-English reference for non-Chinese users.
————————————————————————————————————————
  中英对照 / Chinese-English Reference
————————————————————————————————————————

Moon Sweepers 团队钱包修改器
= Moon Sweepers Team Wallet Editor

存档根目录
= Save root directory

找到 1 个存档栏位：
= Found 1 save slot:

扇区
= sectors

小时 / 分
= hours / minutes

请选择要修改的栏位编号 (默认 1)
= Select the slot number to modify (default: 1)

已选择
= Selected

存档
= Save file

当前钱包
= Current wallet

位于 payload
= located at payload

请输入目标金额（例如 500000，可带千分位）
= Enter target amount (e.g. 500000; thousands separators allowed)

将要修改
= Will modify

确认写入？[y/N]
= Confirm write? [y/N]
————————————————————————————————————————
              示例 / Example
————————————————————————————————————————
  Moon Sweepers Team Wallet Editor
  
Save root: C:\Users\ZhiQiu\AppData\LocalLow\DragDropGames\MoonSweepers\MoonSessions

Found 1 save slot:
  [1] slot-1   $93,081,415.16  4222 sectors   4 h 34 min

Select the slot number to modify (default 1): 1 or 2,3,4,5……

Selected : slot-1
Save file: C:\Users\ZhiQiu\AppData\LocalLow\DragDropGames\MoonSweepers\MoonSessions\slot-1\e42ac78bf8beac22da5697fa882413bc78e2aa069d2fce61cb9f32d48a2451f7\session.moon
Current wallet: $93081415.16454331771827937195   (scale=20, at payload 0xcfb32)

Enter target amount (e.g. 500000; thousands separators allowed): 100000000

Will modify: $93,081,415.16  ->  $100,000,000.00   (+6,918,584.84)
Confirm write? [y/N]: y Or n
