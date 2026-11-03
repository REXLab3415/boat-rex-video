# boat-rex-video

BOAT REX PRO の「答え合わせ動画」を作るだけの、公開リポジトリです。

- `days/日付.json` : 動画の画面に出す内容だけ(場・レース・結果の3連単・払戻金(100円あたり)・各帯の買い目・的中の判定)。非公開側の全レース検証が、保存のたびに送ってきます。オッズ・出走表・展示タイムは入っていません。
- `build_allrace_video.py` / `template.html` / `signboard.txt` : 動画を作るプログラム・画面・掲示板の文章
- `build_video.py` / `user_dict.json` / `assets/` : 声(VOICEVOX 青山龍星)・口パク・撮影の部品、キャスターと背景の画像
- `.github/workflows/video.yml` : `days/` に新しいファイルが来ると、動画を作る(手動でも動く)

音声: VOICEVOX:青山龍星
