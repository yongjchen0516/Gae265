import sys
import configparser
# Azure Speech
import os
import azure.cognitiveservices.speech as speechsdk
import librosa
# Azure Translation
from azure.ai.translation.text import TextTranslationClient
# from azure.ai.translation.text.models import InputTextItem
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

from flask import Flask, request, abort, render_template, url_for
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    AudioMessage
)

#Config Parser
config = configparser.ConfigParser()
config.read('config.ini')

# Azure Speech Settings
speech_config = speechsdk.SpeechConfig(subscription=config['AzureSpeech']['SPEECH_KEY'], 
                                       region=config['AzureSpeech']['SPEECH_REGION'])
audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
UPLOAD_FOLDER = 'static'

# Translator Setup
text_translator = TextTranslationClient(
    credential=AzureKeyCredential(config["AzureTranslator"]["Key"]),
    endpoint=config["AzureTranslator"]["EndPoint"],
    region=config["AzureTranslator"]["Region"],
)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

channel_access_token = config['Line']['CHANNEL_ACCESS_TOKEN']
channel_secret = config['Line']['CHANNEL_SECRET']
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # parse webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    return_result = []
    translation_results, target_sound_language = azure_translate(event.message.text)
    print(translation_results)
    for translation_result in translation_results:
        return_result.append(
            TextMessage(text=translation_result)
        )
    audio_duration = azure_speech(translation_results[0], target_sound_language)
    return_result.append(
        AudioMessage(
            originalContentUrl=f"{config['Deploy']['URL']}/static/outputaudio.mp3",
            duration=audio_duration
        )
    )
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=return_result,
            )
        )

def azure_translate(user_input):

    try:
        # target_languages = ["en","zh-Hant","fr","de","ja","ko","th","vi"]
        # target_languages = ["zh-Hant"]
        target_languages = ["ko","zh-Hant","en"]
        # input_text_elements = [InputTextItem(text=user_input)]
        input_text_elements = [user_input]

        response = text_translator.translate(
            body=input_text_elements, 
            to_language=target_languages,
            # from_language="lzh",
            # from_language="zh-Hant",
        )
        print(response)
        translation = response[0] if response else None

        original_language = translation.detected_language.language if translation else None
        if translation.detected_language.language == "zh-Hans":
            original_language = "zh-Hant"

        print(f"Original language: {original_language}")
        country_flag_dic = {
            "en": "🇬🇧",
            "zh-Hant": "🇹🇼",
            "fr": "🇫🇷",
            "de": "🇩🇪",
            "ja": "🇯🇵",
            "ko": "🇰🇷",
            "th": "🇹🇭",
            "vi": "🇻🇳"
        }

        target_sound_language = ""
        if original_language == "zh-Hant":
            target_sound_language = "ko"
        elif original_language == "ko":
            target_sound_language = "zh-Hant"
        else:
            target_sound_language = "ko"

        return_result = []
        if translation:
            for translation_item in translation.translations:
                if translation_item.language != original_language:
                    print(f"Translated to {translation_item.language}: {translation_item.text}")
                    return_result.append(f"{translation_item.text}")
                # print(f"Translated to {translation_item.language}: {translation_item.text}")
                # return_result += f"{country_flag_dic.get(translation_item.language, '')}{translation_item.language}: {translation_item.text}\n"
            # return translation.translations[0].text
        return return_result, target_sound_language

    except HttpResponseError as exception:
        print(f"Error Code: {exception.error}")
        print(f"Message: {exception.error.message}")

def azure_speech(user_input, target_sound_language):
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz64KBitRateMonoMp3
    )
    # The language of the voice that speaks.
    voice_name_dic = {
        "ko": "ko-KR-SunHiNeural",
        "zh-Hant": "zh-TW-HsiaoChenNeural",
        "en": "en-US-JennyNeural"
    }
    speech_config.speech_synthesis_voice_name = voice_name_dic.get(target_sound_language, "en-US-JennyNeural")
    file_name = "outputaudio.mp3"
    file_config = speechsdk.audio.AudioOutputConfig(filename="static/" + file_name)
    speech_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=file_config
    )

    # Receives a text from console input and synthesizes it to wave file.
    result = speech_synthesizer.speak_text_async(user_input).get()

    # ssml_input = f"""
    # <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN">
    # <voice name="zh-CN-XiaomoNeural">
    #     <mstts:express-as style="sad" styledegree="2">
    #         快走吧，路上一定要注意安全，早去早回。
    #     </mstts:express-as>
    # </voice>
    # </speak>
    # """
    # ssml_input = f"""
    # <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
    # <voice name="zh-CN-XiaomoNeural">
    #     <p>
    #         飛龍在天
    #         <audio src="{config['Deploy']['URL']}/static/dragon.mp3">
    #             Could not play the beep, please voice your opinion now.
    #         </audio>
    #     </p>
    # </voice>
    # </speak>
    # """

    # result = speech_synthesizer.speak_ssml_async(ssml_input).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(
            "Speech synthesized for text [{}], and the audio was saved to [{}]".format(
                user_input, file_name
            )
        )
        audio_duration = round(
            librosa.get_duration(path="static/outputaudio.mp3") * 1000
        )
        print(audio_duration)
        return audio_duration
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/azure_translate", methods=["POST"])
def call_llm():
    if request.method == "POST":
        print("POST!")
        data = request.form
        print(data)
        chinese_text = data["message"]
        print(chinese_text)
        translation_results, target_sound_language = azure_translate(chinese_text)
        print(translation_results)
        audio_duration = azure_speech(translation_results[0], target_sound_language)
        return translation_results[0]



if __name__ == "__main__":
    app.run()