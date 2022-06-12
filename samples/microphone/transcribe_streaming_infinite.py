#!/usr/bin/env python

# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# 解説
# https://yamory.io/blog/about-apache-license/

"""Google Cloud Speech API sample application using the streaming API.

NOTE: This module requires the dependencies `pyaudio` and `termcolor`.
To install using pip:

    pip install pyaudio
    pip install termcolor

Example usage:
    python transcribe_streaming_infinite.py
"""

# [START speech_transcribe_infinite_streaming]

import re
import sys
import time
import os
import deepl
import tkinter as tk
from tkinter import messagebox as mb
from tkinter import filedialog, simpledialog
import threading as th
import subprocess
import webbrowser

from google.cloud import speech
import pyaudio
from six.moves import queue

# Audio recording parameters
STREAMING_LIMIT = 240000  # 4 minutes
SAMPLE_RATE = 16000
CHUNK_SIZE = int(SAMPLE_RATE / 10)  # 100ms

#os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'phonic-ceremony-xxxxxx-yyyyyyyyyyyy.json'
"""
お試し期間を終了すると以下のようになる。
This API method requires billing to be enabled. Please enable billing on project #835696364981 by visiting https://console.developers.google.com/billing/enable?project=835696364981 then retry. If you enabled billing for this project recently, wait a few minutes for the action to propagate to our systems and retry.
以降の従量課金を有効にしてアカウントを有効に復活させると、大丈夫かな
メールでgcpを検索して、トライアルが終わった趣旨のメールのリンクからも、上記のURLからも有効にできた。(たしか最初にクレジットカード登録させられたな。)そのamexが登録されていて見える。
最近やったのにダメだったら数分待ってもう一度やれと書いてある。
予算とアラートで予算額設定してアラートメールを飛ばしてくれる設定もできる。1000円でやってみた
"""
"""
windows10のスピーカーアイコンを右クリック→「サウンド」
再生=CABLE Inputを規定のデバイス スピーカーアイコンで選ばれるデバイス=システムもこれになる。
録音=CABLE Outputを選択。右クリック→「聴く」→このデバイスを聴く→BenQOK。ゼンハイザーOK。Realtekはダメ!しかしアプリには入って認識できた。実家ではできなかったのに。不安定?
Youtubeの音を再生。システムで選択されたデバイスがCABLE Inputなので、選ぶとアプリに入れられた!
 スピーカ/ヘッドホン Realtek High Definition Audion(SST)ではなぜか聴けない。ノートパソコンからの音も、ノートパソコンに刺したイヤホンも聞こえない。再起動なのか実家ではできなかったが聞こえない状態でもアプリには入った。
 BenQ聴ける。senhizer聴ける。イヤホン聴けた。
 イヤホンを抜いているとノートパソコンのスピーカーから流れることになるが、CABLE Outputを聴くにしても音が出ない。しかしアプリで認識はできた。実家と違う。再起動か?
まとめ20220510
VBCableを入れてから再起動をしていなかったかもしれない。記憶にない。
確かに本日事件をする前には仕事で再起動を行った。
CABLE OutputをRealtekで聴くと、イヤホンでは聴ける。PCのスピーカーでは聴けない。@thinkpad
これはおそらくPC依存realtek依存。asusではpcのスピーカーで開発していた。(まだvbcableではないかも。たしかステレオミキサー機能がこちらのrealtekには有ったから)
realtek依存は大きく怖い。
ゼンハイザーマイクでzoomに英語を録音して、CABLE Inputを出力先に選び、CABLE Outputをアプリに入れて認識させつつ、CABLE Outputをゼンハイザーで聴くことは成功!
"""
translator = deepl.Translator("YOUR_DEEPL_API_KEY")

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"


def get_current_time():
    """Return Current Time in MS."""

    return int(round(time.time() * 1000))


class ResumableMicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate, chunk_size):
        self._rate = rate
        self.chunk_size = chunk_size
        self._num_channels = 1
        self._buff = queue.Queue()
        self.closed = True
        self.start_time = get_current_time()
        self.restart_counter = 0
        self.audio_input = []
        self.last_audio_input = []
        self.result_end_time = 0
        self.is_final_end_time = 0
        self.final_request_end_time = 0
        self.bridging_offset = 0
        self.last_transcript_was_final = False
        self.new_stream = True
        self._audio_interface = pyaudio.PyAudio()
        # for i in range(0, self._audio_interface.get_device_count()):
        #     if isinstance(self._audio_interface.get_device_info_by_index(i)['name'], str):
        #         # str
        #         print(i, self._audio_interface.get_device_info_by_index(i)['name'], "str")
        #     elif isinstance(self._audio_interface.get_device_info_by_index(i)['name'], bytes):
        #         # bytes
        #         print(i, self._audio_interface.get_device_info_by_index(i)['name'].decode("CP932"), "bytes")
        # サウンドデバイスを管理する→ステレオミキサー無効時
        # 0 Microsoft Sound Mapper - Input
        # 1 ƒ}ƒCƒN (Realtek High Definition
        # 2 Microsoft Sound Mapper - Output
        # 3 BenQ EW2780 (ƒCƒ“ƒeƒ‹(R) ƒfƒBƒX
        # 4 b'\x83X\x83s\x81[\x83J\x81[ (Realtek High Defini'
        # サウンドデバイスを管理する→ステレオミキサー有効時
        # 0 Microsoft Sound Mapper - Input
        # 1 ƒ}ƒCƒN (Realtek High Definition
        # 2 b'\x83X\x83e\x83\x8c\x83I \x83~\x83L\x83T\x81[ (Realtek High' 違う
        # 3 Microsoft Sound Mapper - Output
        # 4 BenQ EW2780 (ƒCƒ“ƒeƒ‹(R) ƒfƒBƒX
        # 5 b'\x83X\x83s\x81[\x83J\x81[ (Realtek High Defini'
        # 入力から順に出てきているのだな。するとmicrosoftのやつは、システムと同じというやつだろう
        self._audio_stream = None
        # self._audio_stream = self._audio_interface.open(
        #     format=pyaudio.paInt16,
        #     channels=self._num_channels,
        #     rate=self._rate,
        #     input=True,
        #     frames_per_buffer=self.chunk_size,
        #     # Run the audio stream asynchronously to fill the buffer object.
        #     # This is necessary so that the input device's buffer doesn't
        #     # overflow while the calling thread makes network requests, etc.
        #     stream_callback=self._fill_buffer,
        #     input_device_index=2,
        #     # まずステレオミキサーを無効にしたままで実験
        #     # 5番目がないのに5を設定すると、segmentation fault
        #     # 4番目にあるはずのbenqを選ぶと、invalid number of channels　出力デバイス蘭に、benqがある。出力じゃだめだよな。
        #     # 3番目のスピーカー(real teck)も invalid number of channels　出力デバイス蘭に、スピーカー(real teck)がある。出力じゃだめだよな。
        #     # 1番目の文字化け(real teck)は、OK。マイクが入力された。　入力デバイス蘭に、マイク(real teck)がある
        #     # 2番目のmicrosoft sound mapper outputはinvalid numver of channnel
        #     # 0番目のmicrosft sound mapper inputは、OK.マイクが入力された。 
        #         # youtube 
        #             # HostをPCスピーカー
        #                 # OK入力。 Hostをbenq→NG入らない。
            
        # )
        self.pause_flg = False
        self.comma_flg = False
        self.refresh_flg = False

    def __enter__(self):

        self.closed = False
        return self

    def __exit__(self, type, value, traceback):

        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()
        
    def get_audio_device_list(self):
        device_names = []
        for i in range(self._audio_interface.get_device_count()):
            device_names.append(self._audio_interface.get_device_info_by_index(i)['name'])
        return device_names
        
    def audio_interface_open(self, device_index=0):
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=self._num_channels,
            rate=self._rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
            input_device_index=device_index,            
        )

    def _fill_buffer(self, in_data, *args, **kwargs):
        """Continuously collect data from the audio stream, into the buffer."""

        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        """Stream Audio from microphone to API and to local buffer"""

        while not self.closed:
            data = []

            if self.new_stream and self.last_audio_input:

                chunk_time = STREAMING_LIMIT / len(self.last_audio_input)

                if chunk_time != 0:

                    if self.bridging_offset < 0:
                        self.bridging_offset = 0

                    if self.bridging_offset > self.final_request_end_time:
                        self.bridging_offset = self.final_request_end_time

                    chunks_from_ms = round(
                        (self.final_request_end_time - self.bridging_offset)
                        / chunk_time
                    )

                    self.bridging_offset = round(
                        (len(self.last_audio_input) - chunks_from_ms) * chunk_time
                    )

                    for i in range(chunks_from_ms, len(self.last_audio_input)):
                        data.append(self.last_audio_input[i])

                self.new_stream = False

            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            self.audio_input.append(chunk)

            if chunk is None:
                return
            data.append(chunk)
            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)

                    if chunk is None:
                        return
                    data.append(chunk)
                    self.audio_input.append(chunk)

                except queue.Empty:
                    break

            yield b"".join(data)


class Tk():
    def __init__(self):
        # 画面初期化
        self.root = tk.Tk()
        self.root.geometry("640x640")
        self.root.protocol("WM_DELETE_WINDOW", self._force_exit)
        self.force_exit_flg = False  # thread実行中に[x]停止した時の終了処理を行うためのフラグ。このようにグローバル変数(のような)をthreadに渡すことができ、start()後でも更新がかかる。しかしdaemon=Trueでメインと同時にサブも殺しているので、上のフラグは使っていないことになる。
        self.Process = None  # thread実行する前段階で[x]で終了した場合のためのダミー初期化
        self.is_translucented = False
        self.click = "<Button-1>"

        # DeepLインスタンス化
        self.DEEPL_API_KEY = "dummy_api_key"
        self.translator = deepl.Translator(self.DEEPL_API_KEY)  # この段階ではダミーのAPIキーを入れたインスタンスにしておくが、メニューバーにてAPIを入力した時点でインスタンスを更新する。ダミーのままだった時APIキーが異なるエラーメッセージを受け取る

        # マイクストリームインスタンス
        self.mic_manager = ResumableMicrophoneStream(SAMPLE_RATE, CHUNK_SIZE)
        self.filename = str(self.mic_manager.start_time) + ".txt" # デフォルトはカレント保存。指定したら別の場所

        # オーディオデバイス探索結果保持dict
        self.audio_devide_dict = {}  # {"hoge": 0, "huga": 1}
        # オーディオデバイスを選択するオプションメニュー
        self.audio_devices = []

        # Google speech の言語の選択 https://cloud.google.com/speech-to-text/docs/languages
        self.language_dict_speech = {
            "English": "en_US",
            "Japanese": "ja-JP",
            "Chinese": "zh",
            "Bulgarian": "bg-BG",
            "Czech": "cs-CZ",
            "Danish": "da-DK",
            "German": "de-DE",
            "Greek": "el-GR",
            "Spanish": "es-ES",
            "Estonian": "et-EE",
            "Finnish": "fi-FI",
            "French": "fr-FR",
            "Hungarian": "hu-HU",
            "Italian": "it-IT",
            "Lithuanian": "lt-LT",
            "Latvian": "lv-LV",
            "Dutch": "nl-NL",
            "Polish": "pl-PL",
            "Portuguese": "pt-PT",
            "Romanian": "ro-RO",
            "Russian": "ru-RU",
            "Slovak": "sk-SK",
            "Slovenian": "sl-SI",
            "Swedish": "sv-SE",
        }
        self.gs_lng_list = []
        for k in self.language_dict_speech.keys():
            self.gs_lng_list.append(k)
            
        # Google speech の言語選択オプションメニュー作成 デフォルトは一行目English
        self.gs_lng_selected = tk.StringVar()
        self.gs_lng_selected.set(self.gs_lng_list[0])
        self.gs_lng_opt = tk.OptionMenu(self.root, self.gs_lng_selected, *self.gs_lng_list)
        # 取得 self.gs_lng_selected.get()

        # Google speech OUT->IN DeepL対応表
        self.gs2deepl_dict = {
            "Bulgarian": "BG",
            "Czech": "CS",
            "Danish": "DA",
            "German": "DE",
            "Greek": "EL",
            "English": "EN",
            "Spanish": "ES",
            "Estonian": "ET",
            "Finnish": "FI",
            "French": "FR",
            "Hungarian": "HU",
            "Italian": "IT",
            "Japanese": "JA",
            "Lithuanian": "LT",
            "Latvian": "LV",
            "Dutch": "NL",
            "Polish": "PL",
            "Portuguese": "PT",
            "Romanian": "RO",
            "Russian": "RU",
            "Slovak": "SK",
            "Slovenian": "SL",
            "Swedish": "SV",
            "Chinese": "ZH",
        }

        # DeepL の言語の選択 https://www.deepl.com/ja/docs-api/translating-text/response/
        self.language_dict_deepl = {
            "Japanese": "JA",
            "English": "EN-US",
            "Chinese": "ZH",
            "Bulgarian": "BG",
            "Czech": "CS",
            "Danish": "DA",
            "German": "DE",
            "Greek": "EL",
            "Spanish": "ES",
            "Estonian": "ET",
            "Finnish": "FI",
            "French": "FR",
            "Hungarian": "HU",
            "Italian": "IT",
            "Lithuanian": "LT",
            "Latvian": "LV",
            "Dutch": "NL",
            "Polish": "PL",
            "Portuguese": "PT-PT",
            "Romanian": "RO",
            "Russian": "RU",
            "Slovak": "SK",
            "Slovenian": "SL",
            "Swedish": "SV",
        }
        self.deepl_lng_list = []
        for k in self.language_dict_deepl.keys():
            self.deepl_lng_list.append(k)

        # DeepL の言語選択オプションメニュー作成 デフォルトは一行目Japanese
        self.deepl_lng_selected = tk.StringVar()
        self.deepl_lng_selected.set(self.deepl_lng_list[0])
        self.deepl_lng_opt = tk.OptionMenu(self.root, self.deepl_lng_selected, *self.deepl_lng_list)
        # 取得 self.deepl_lng_selected.get()

        # Google speech リアルタイム認識用スクロールバー初期化
        self.frame1 = tk.Frame()
        self.txt1 = tk.Text(self.frame1, height=9)
        self.scrollbar1 = tk.Scrollbar(
            self.frame1,
            orient=tk.VERTICAL,
            command=self.txt1.yview)
        self.txt1['yscrollcommand'] = self.scrollbar1.set
        # Google speech 最終認識用スクロールバー初期化
        self.frame2 = tk.Frame()
        self.txt2 = tk.Text(self.frame2, height=13)
        self.scrollbar2 = tk.Scrollbar(
            self.frame2,
            orient=tk.VERTICAL,
            command=self.txt2.yview)
        self.txt2['yscrollcommand'] = self.scrollbar2.set
        # DeepL用スクロールバー初期化
        self.frame3 = tk.Frame()
        self.txt3 = tk.Text(self.frame3, height=13)
        self.scrollbar3 = tk.Scrollbar(
            self.frame3,
            orient=tk.VERTICAL,
            command=self.txt3.yview)
        self.txt3['yscrollcommand'] = self.scrollbar3.set

        self.curr_transcript = ""
        self._search_audio_device(None)

    def _search_audio_device(self, event=None):
        # searchが二度目移行ならば、audio_devide_dictとaudio_devicesはクリアする
        if len(self.audio_devide_dict):
            self.audio_devide_dict = {}
            self.audio_devices = []
        # 再生デバイス情報をリストに保持。
        # デバイス情報を取得しdictへ登録
        device_names = self.mic_manager.get_audio_device_list()
        for i, device_name in enumerate(device_names):
            self.audio_devide_dict.update({device_name: i})
            self.audio_devices.append(device_name)

    def _connect_audio_device(self, event):
        # startと同時に接続する構成にしたために、このメソッドは使われていない。
        print("Open succseed.")

    def _start(self, event):
        device_index = self.radio_val.get()
        self.mic_manager.audio_interface_open(device_index=device_index)
        # loop処理ではtkがフリーズするのでThreadで投げる
        self.Process = th.Thread(target=self._run, daemon=True)  # daemon=Trueであればメインスレッドが終了したらサブスレッドも終了できる
        self.Process.start()
        print("thread started.")
        return 0

    def _run(self):
        # メインループを開始
        """start bidirectional streaming from microphone input to speech API"""

        client = speech.SpeechClient()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            language_code=self.language_dict_speech[self.gs_lng_selected.get()],  # e.g.{"English": "en_US"}
            max_alternatives=1,
        )

        streaming_config = speech.StreamingRecognitionConfig(
            config=config, interim_results=True
        )

        #mic_manager = ResumableMicrophoneStream(SAMPLE_RATE, CHUNK_SIZE)
        #print(mic_manager.chunk_size)
        # sys.stdout.write(YELLOW)
        # sys.stdout.write('\nListening, say "Quit" or "Exit" to stop.\n\n')
        # sys.stdout.write("End (ms)       Transcript Results/Status\n")
        # sys.stdout.write("=====================================================\n")

        with self.mic_manager as stream:

            while not stream.closed:
                sys.stdout.write(YELLOW)
                sys.stdout.write(
                    "\n" + str(STREAMING_LIMIT * stream.restart_counter) + ": NEW REQUEST\n"
                )
                if self.mic_manager.refresh_flg:
                    # ここにいてrefresh_flg:Trueなのは、前回のリフレッシュボタン時のフラグが残っているだけなので、Falseに下げておく
                    self.mic_manager.refresh_flg = False

                stream.audio_input = []
                audio_generator = stream.generator()

                requests = (
                    speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator
                )

                responses = client.streaming_recognize(streaming_config, requests)  # NEWの後何か認識されるまではここにとどまっている

                # Now, put the transcription responses to use.
                #listen_print_loop(responses, stream)
                self._listen_print_loop(responses, stream)

                if stream.result_end_time > 0:
                    stream.final_request_end_time = stream.is_final_end_time
                stream.result_end_time = 0
                stream.last_audio_input = []
                stream.last_audio_input = stream.audio_input
                stream.audio_input = []
                stream.restart_counter = stream.restart_counter + 1

                if not stream.last_transcript_was_final:  # 最後の文字が最後か 最後じゃなかったら　つまり更新中なら
                    sys.stdout.write("\n")
                stream.new_stream = True  # new_stream=Trueは、次のgeneratorの為にTrueでloopを終わっている。stream.closeじゃない状態で4分経ってbreakでここにきてTrueでまたNEW REQに来れる。
                # つまり4分判定と同じ場所でrefreshボタンでbreakすればリフレッシュできるだろうな

                if self.force_exit_flg:
                    print("force_exit: Exiting from _run()...")
                    break

    def _listen_print_loop(self, responses, stream):
        interruption = False
        for response in responses:
            if get_current_time() - stream.start_time > STREAMING_LIMIT:
                print("get_current_time() - stream.start_time > STREAMING_LIMIT")
                print("Going to break.")
                # 更新は、__init__とここのみ。つまり最初からの時間が4分。4分ずつってことだろう。
                # このloopまで来て4分なので、__init__～マイクが何かを認識し続けて4分。もしくは、__init__～4分以上経過したのちの最初のマイクの何かの認識のタイミング。
                # 4分経過した実験では、直前の一文：直前の全認識結果ではない が重複してNEW REQ後も出た。全く同じ。しかし別にものすごく変ではない。一度切れたのでもう一度出たという程度か。
                stream.start_time = get_current_time()
                break

            if stream.refresh_flg:
                # refreshボタンが押されたらbreakをする。
                print("refresh inside loop. going to break.")  # 認識継続中にリフレッシュすると、リフレッシュする前の音が残っているのだろう リフレッシュ後にもう一度出てきてしまう。
                # responses = []  # 効果なし
                # 認識スタック中に押す想定か
                break

            if stream.comma_flg:
                # 話の途中で切りたいとき
                interruption = True
                self.mic_manager.comma_flg = False  # 一度interruption=Trueにしたので、次回の為にcomma_flgをFalseへ戻しておく

            if self.force_exit_flg:
                # [x]ボタンが押されたとき
                interruption = True

            if not response.results:
                # resultsが来てないので以降飛ばす
                continue

            result = response.results[0]

            if not result.alternatives:
                # alternatives候補が来てないので以降飛ばす
                continue

            if stream.pause_flg:
                # 翻訳を一時停止したいとき
                continue

            transcript = result.alternatives[0].transcript

            result_seconds = 0
            result_micros = 0

            if result.result_end_time.seconds:
                result_seconds = result.result_end_time.seconds

            if result.result_end_time.microseconds:
                result_micros = result.result_end_time.microseconds

            stream.result_end_time = int((result_seconds * 1000) + (result_micros / 1000))

            corrected_time = (
                stream.result_end_time
                - stream.bridging_offset
                + (STREAMING_LIMIT * stream.restart_counter)
            )
            # Display interim results, but with a carriage return at the end of the
            # line, so subsequent lines will overwrite them.

            if result.is_final or interruption:  # is_finalで最後にドン。緑で出す。

                sys.stdout.write(GREEN)
                sys.stdout.write("\033[K")
                sys.stdout.write(str(corrected_time) + ": " + transcript + "\n")
                result = self.translator.translate_text(
                    transcript,
                    source_lang=self.gs2deepl_dict[self.gs_lng_selected.get()],
                    target_lang=self.language_dict_deepl[self.deepl_lng_selected.get()]
                )
                print("deepl", result)
                # 議事録保存
                self._save_minutes_to_file(transcript, result)
                # スクロールバー2に表示
                self._write_scrollbar(self.txt2, transcript)
                # DeepL web にて表示するために現在のtranscriptを保持
                self.curr_transcript = transcript
                # スクロールバー3に表示
                self._write_scrollbar(self.txt3, result.text)

                stream.is_final_end_time = stream.result_end_time  # 最後の時間
                stream.last_transcript_was_final = True  # 最後の文字が最後か

                if interruption:
                    # 中断 OK. 緑で英語が表示され、deeplも表示される。Finaly I am here.が表示される。その後NEW REQUESTが出て赤文字が再開する
                    # commaボタンではbreakのみ。force_exitではclosedまで。
                    if self.force_exit_flg:
                        sys.stdout.write(YELLOW)
                        sys.stdout.write("force_exit: Exiting from _listen_print_loop()...\n")
                        stream.closed = True
                    break

            else:
                sys.stdout.write(RED)
                sys.stdout.write("\033[K")
                sys.stdout.write(str(corrected_time) + ": " + transcript + "\r")
                # スクロールバー1に表示
                self._write_scrollbar(self.txt1, transcript)

                stream.last_transcript_was_final = False
        return 0

    def _save_minutes_to_file(self, transcript, result):
        if self.filename:
            with open(self.filename, "a", encoding="UTF-8") as f:
                f.write(transcript)
                f.write("\n")
                f.write(result.text)
                f.write("\n")
                f.write("\n")

        return 0

    def _comma(self, event):
        print("")
        print("comma is pressed.")
        self.mic_manager.comma_flg = True
        return 0

    def _pause(self, event):
        print("")
        print("pause is pressed.")
        if self.mic_manager.pause_flg:
            # もうすでにPauseされており、もう一度ボタンを押された場合
            self.mic_manager.pause_flg = False  # もうPauseされないようにFalseへ
            self.btn_str_pause.set("Pause")  # ボタンはPauseに戻す
        else:
            # 通常実行中で、Pauseが押された場合
            self.mic_manager.pause_flg = True
            self.btn_str_pause.set("Re-Start")  # ボタンのPauseラベルを解除ラベルに
        return 0

    def _force_exit(self):
        print("[x] is pressed.")
        if self.Process is not None:  # threadが開始していたら
            self.force_exit_flg = True  # thread側で処理を終わらせる
            mb.showinfo("Exit", "Finalizing...")  # メッセージボックスを出している間にthreadを終わらせる
            # self.Process.join()  # threadを集合させる
            print("All threads are finished.")
        self.root.destroy()  # GUIを消す

    def _refresh_old(self, event):
        print("")
        print("refresh is pressed.")
        self.mic_manager.refresh_flg = True
        return 0

    def _refresh(self, event):
        # 既に走っているprocessを殺し、インスタンスを初期化で上書きする。
        if self.Process is not None:  # threadが開始していたら
            self.force_exit_flg = True  # thread側で処理を終わらせる
            mb.showinfo("Refresh", "Refreshed. Now you cat start.")  # メッセージボックスを出している間にthreadを終わらせる
            # インスタンスを初期化し
            self.mic_manager = ResumableMicrophoneStream(SAMPLE_RATE, CHUNK_SIZE)
            # 一気に接続
            # self._connect_audio_device(None)
            # 次のstartに備えてforce_exit_flgは下げておく
            self.force_exit_flg = False

    def _restart(self, event):
        # 既に走っているprocessを殺し、インスタンスを初期化で上書きする。さらにstartを一気に押す
        if self.Process is not None:  # threadが開始していたら
            self.force_exit_flg = True  # thread側で処理を終わらせる
            mb.showinfo("Restart", "Restart now.")  # メッセージボックスを出している間にthreadを終わらせる
            # インスタンスを初期化し
            self.mic_manager = ResumableMicrophoneStream(SAMPLE_RATE, CHUNK_SIZE)
            # 一気に接続
            # self._connect_audio_device(None)
            # 次のstartに備えてforce_exit_flgは下げておく
            self.force_exit_flg = False
            # start
            self._start(None)

    def _save_file(self, event=None):
        print("save")
        self.filename = filedialog.asksaveasfilename(
            title="名前を付けて保存",
            filetypes=[("txt", ".txt")],
            initialdir="./",
            initialfile=self.mic_manager.start_time,
            defaultextension=".txt"
        )
        # e.g. C:/Users/sho_t/Documents/python-speech/1651153727722.txt
        print(self.filename)

    def _ask_gs_api_key(self, event=None):
        gs_api_key_filepath = filedialog.askopenfilename(
            title="Select Google speech API Key (.json)",
            initialdir="./",
            filetypes=[("Json", ".json")]
        )
        print(gs_api_key_filepath)
        # デスクトップに置いて実験。日本語がパスに含まれても大丈夫。
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gs_api_key_filepath
        return 0

    def _write_mgs(self, event):
        self.txt1.insert(tk.END, "\n---\n")
        self.txt1.insert(tk.END, "Hello !!")
        self.txt1.see("end")

    def _write_scrollbar(self, txt, transcript):
        txt.insert(tk.END, "\n---\n")
        txt.insert(tk.END, transcript)
        txt.see("end")
        return 0

    def _translucent(self, event):
        if self.is_translucented:
            self.root.attributes("-alpha",1.0)
            self.is_translucented = False
        else:
            self.root.attributes("-alpha",0.5)
            self.is_translucented = True

    def _menu_click(self, event=None):
        print("メニューバーがクリックされた")

    def _ask_deepl_api_key(self, event=None):
        key = simpledialog.askstring("Input Box", "Enter DeepL API key \n\n (例. 3c9*****-***-***-***-*********29b:fx)",)
        print("simpledialog", key)
        if key:
            self.DEEPL_API_KEY = key
            self.translator = deepl.Translator(self.DEEPL_API_KEY)

    def _open_sound_config(self, event=None):
        subprocess.run(["mmsys.cpl"], shell=True)  # win10にてサウンドを開くコマンド win11も効くだろう

    def _open_deepl(self, event):
        # https://www.deepl.com/translator#EN-US/JA/I%20don't%20see%20the%20name%20of%20the%20new%20employee%20yet%2C%20but%20do%20you%20need%20me%20to%20take%20action%3F%20They%20do%20have%20a%20WOVEN%20account.
        # %20 = 半角スペース
        # %0A = 改行
        # %3F = ?
        # URLに日本語などを直接含めればおそらく解釈できる
        # DeepLの言語dictのvalを小文字もしくは大文字でURLに使う
        FROM = self.gs2deepl_dict[self.gs_lng_selected.get()]
        TO = self.language_dict_deepl[self.deepl_lng_selected.get()]
        MSG = self.curr_transcript
        url = "https://www.deepl.com/translator#" + FROM + "/" + TO + "/" + MSG
        webbrowser.open(url)

    def page(self):

        # 描画定数
        WW = 580  # 文字表示空白部分の幅
        SH = 5    # 上端空白の幅
        BH = 30   # ボタン高さ
        OW = 140  # オプションメニューのボタン幅
        BW = 50   # ボタン幅
        SP = (WW - 5 * BW) / 2
        tk.Label(self.root, text="").grid(row=0, column=2)
        tk.Label(self.root, text="").grid(row=1, column=2)
        tk.Label(self.root, text="").grid(row=2)
        tk.Label(self.root, text="").grid(row=3)

        # Google speech の言語選択オプションメニュー表示
        self.gs_lng_opt.place(x=(WW-(2*OW))/3, y=SH, width=OW, height=BH)
        tk.Label(self.root, text="->").place(x=WW/2-(BH/2), y=SH, width=BH, height=BH)
        # DeepL の言語選択オプションメニュー表示
        self.deepl_lng_opt.place(x=(2*(WW-(2*OW))/3)+OW, y=SH, width=OW, height=BH)

        # メインループ開始ボタン初期化
        self.btn_start = tk.Button(text="Start")
        self.btn_start.bind(self.click, self._start)
        # メインループ開始ボタン表示
        self.btn_start.place(x=SP, y=SH+BH+SH, width=BW, height=BH)

        # 句読点ボタン初期化 my_break
        self.btn_comma = tk.Button(text="Break")
        self.btn_comma.bind(self.click, self._comma)
        # 句読点ボタン表示
        self.btn_comma.place(x=SP+BW, y=SH+BH+SH, width=BW, height=BH)

        # 一時停止ボタン初期化 my_pause
        self.btn_str_pause = tk.StringVar()
        self.btn_str_pause.set("Pause")
        self.btn_pause = tk.Button(textvariable=self.btn_str_pause)
        self.btn_pause.bind(self.click, self._pause)
        # 一時停止ボタン表示
        self.btn_pause.place(x=SP+2*BW, y=SH+BH+SH, width=BW, height=BH)

        # リフレッシュボタン初期化
        self.btn_refresh = tk.Button(text="Refresh")
        self.btn_refresh.bind(self.click, self._refresh)
        # リフレッシュボタン表示
        self.btn_refresh.place(x=SP+3*BW, y=SH+BH+SH, width=BW, height=BH)

        # リフレッシュ2ボタン初期化
        self.btn_refresh2 = tk.Button(text="Restart")
        self.btn_refresh2.bind(self.click, self._restart)
        # リフレッシュ2ボタン表示
        self.btn_refresh2.place(x=SP+4*BW, y=SH+BH+SH, width=BW, height=BH)

        # スクロールバー1表示
        self.frame1.grid(row=4, column=0, columnspan=3, padx=10, pady=2, sticky=(tk.W + tk.E))  # columnspanはこれまで使用したどのcolumnより大きいこと。(0始まりであることに注意.8なら9ということ)
        self.txt1.grid(row=4, column=0, columnspan=3, padx=10, pady=2, sticky=(tk.W + tk.E))
        self.scrollbar1.grid(row=4, column=4, columnspan=1, padx=10, pady=2, sticky=(tk.N + tk.S + tk.E))  # このcolumnはcolunmspan+1でないと、textの右端がかぶってしまう
        # スクロールバー2表示
        self.frame2.grid(row=5, column=0, columnspan=3, padx=10, pady=2, sticky=(tk.W + tk.E))
        self.txt2.grid(row=5, column=0, columnspan=3, padx=10, pady=2, sticky=(tk.W + tk.E))
        self.scrollbar2.grid(row=5, column=4, columnspan=1, padx=10, pady=2, sticky=(tk.N + tk.S + tk.E))
        # スクロールバー3表示
        self.frame3.grid(row=6, column=0, columnspan=3, padx=10, pady=2, sticky=(tk.W + tk.E))
        self.txt3.grid(row=6, column=0, columnspan=3, padx=10, pady=2, sticky=(tk.W + tk.E))
        self.scrollbar3.grid(row=6, column=4, columnspan=1, padx=10, pady=2, sticky=(tk.N + tk.S + tk.E))

        # DeepL web ボタン初期化
        self.btn_dpl = tk.Button(text="DeepL web")
        self.btn_dpl.bind(self.click, self._open_deepl)
        # DeepL web ボタン配置
        self.btn_dpl.place(x=BW, y=580, width=2*BW, height=BH)

        # 画面を透過させるボタン初期化
        self.btn_tls = tk.Button(text="Translucent")
        self.btn_tls.bind(self.click, self._translucent)
        # 画面を透過させるボタン配置
        self.btn_tls.place(x=BW+(2*BW)+(BW/2), y=580, width=2*BW, height=BH)

        # メニューバー
        menubar = tk.Menu()
        # メニューバー/APIキー
        menu_api = tk.Menu(menubar, tearoff=False)
        menu_api.add_command(label="Google speech", command=self._ask_gs_api_key, accelerator="Ctrl+G")
        menu_api.add_command(label="DeepL", command=self._ask_deepl_api_key, accelerator="Ctrl+D")
        # menu_file.add_separator()  # 仕切り線
        # menu_file.add_command(label="終了", command=self.master.destroy)
        # ショートカットキーの関連付け
        menu_api.bind_all("<Control-g>", self._ask_gs_api_key)
        menu_api.bind_all("<Control-d>", self._ask_deepl_api_key)
        # メニューバー/入力
        self.radio_val = tk.IntVar()
        menu_src = tk.Menu(menubar, tearoff=False)
        for device_name in self.audio_devices:
            menu_src.add_radiobutton(label=device_name,
                                     command=None,
                                     variable=self.radio_val,
                                     value=self.audio_devide_dict[device_name])
        # メニューバー/ファイル
        menu_file = tk.Menu(menubar, tearoff=False)
        menu_file.add_command(label="議事録 save as ...", command=self._save_file, accelerator="Ctrl+S")
        # ショートカットキーの関連付け
        menu_file.bind_all("<Control-s>", self._save_file)
        # メニューバー/その他
        menu_misc = tk.Menu(menubar, tearoff=False)
        menu_misc.add_command(label="サウンド設定を開く", command=self._open_sound_config)
        menu_misc.add_command(label="Search sound source again", command=self._search_audio_device)
        # ショートカットキーの関連付け

        # ウィンドウに表示
        menubar.add_cascade(label="APIキー", menu=menu_api)
        menubar.add_cascade(label="入力", menu=menu_src)
        menubar.add_cascade(label="ファイル", menu=menu_file)
        menubar.add_cascade(label="その他", menu=menu_misc)
        self.root.config(menu=menubar)

        # TODO: 順番通りボタンを選択していないとエラーポップアップを出す
        # MEMO: __init__からSTREAMING_LIMIT4分経つと、少なくとも最初の認識でいったん閉じるようだ。でまたNEW REQから始まる。どう扱うか→4分ずつNEW REQになるが続けられる。直前の分が少し重複するが無視できるだろう。
        # MEMO: stackした時の再開ボタン。リフレッシュボタン→スタック中なら効く。正常継続中では直前の文がそれなりに重複して出る。スタックリフレッシュとでもするか。
        # TODO: 前回セッションのログがあれば設定をリジューム
        # TODO: ボタンを画像にするか否か
        # MEMO: URLに込めてwebに飛ばすと、文章を音読してくれる。
        # https://www.deepl.com/translator#en/zh/I%20don't%20see%20the%20name%20of%20the%20new%20employee%20yet%2C%20but%20do%20you%20need%20me%20to%20take%20action%3F%20They%20do%20have%20a%20WOVEN%20account.
        # %20 = 半角スペース
        # %0A = 改行
        # %3F = ?
        # アプリの状態をprintする
        # アプリパスワードmakuakeとか

    def show(self):
        self.root.mainloop()


def mymain():
    tk = Tk()
    tk.page()
    tk.show()


if __name__ == "__main__":
    mymain()

# [END speech_transcribe_infinite_streaming]
