# PromptCraft Suite — Clean Standby Build

In this build:
- **No Default Pre-Filled Values:** Input fields (Headline, Message, Brand, Website) are clean by default.
- **Standby Canvas:** The video canvas does not show any image, logo, or Diwali lamp upon opening.
- **Prompt-Driven Generation:** When a user enters a prompt (e.g., Diwali in Kannada, Mega Sale, Corporate Summit) and clicks **Auto-Detect & Generate Video From Prompt**, the matching theme, background images, spoken voice, and text are dynamically generated and displayed.

## Replacing the logo on a finished poster

Upload your actual logo in the poster's **Logo** field and click **Save brand kit**.
In the Brand Kit section, upload the finished poster under **Replace logo on a
finished image**, or click **Replace logo on selected image** after selecting a
base or reference image. You can also upload or paste the image in Step 2 with
the complete-poster option checked, or generate it in the app. The preview places
the saved logo over a solid-colored box; it does not automatically detect the
original logo. Adjust the placement controls, then click **Download poster with
Brand Kit logo** in this app. A file downloaded directly from ChatGPT or Gemini
is not changed. If no logo is saved, the original image is shown unchanged.

## Automatic local narration

The downloaded video can include generated narration and background music without credits.
The browser UI calls `tts_server.py` to generate narration. When installed, `edge-tts`
provides neural voices and requires internet access; narration text is sent to the
Microsoft Edge TTS service. If it is unavailable, the server falls back to `pyttsx3`
and a matching Windows speech voice installed on the computer.

The company name ಪೆಝೋಸಿಸ್ is spoken as "Pezosys" by the English voice, because the Kannada
voice mispronounces ಝ. Edit `BRAND_SPOKEN` in `tts_server.py` to change it or add names, then
restart the server. The text on screen is not changed.

From PowerShell in this folder:

```powershell
py -m pip install pyttsx3 edge-tts
py .\tts_server.py
```

Keep that terminal open, then open the app through a local server such as
`http://127.0.0.1:5500/index.html`. Install the desired language speech voices in
Windows Settings if the service reports that a voice is unavailable. The generated
narration is mixed above optional background music and embedded in the downloaded MP4.
Music volume rises during narration pauses and lowers under speech. The export status
shows the total video duration after download. MP4 export
requires a browser with MediaRecorder MP4 support, such as a current version of Chrome
or Edge; the app reports an error instead of saving a WebM file with an MP4 extension
when the browser does not support MP4 recording.
The selected video duration is a minimum: export continues until the selected duration,
full narration, and uploaded song have all finished. If narration outlasts the song, the
background music loops underneath it. Uploaded background images share the final video
duration equally.

Enter video directions and, when exact spoken wording is needed, a `Narration:` section
in the same Natural Language Prompt. Generating from that prompt fills the Message Text
field with the narration, which is used both on screen and for voice. Without a
`Narration:` section, the app uses its theme-based greeting.
