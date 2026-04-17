from gtts import gTTS
tts = gTTS("Test bestanden", lang='de')
tts.save("test.mp3")
print("Audio generiert!")