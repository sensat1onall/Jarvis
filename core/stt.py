"""
Speech-to-Text engines for MARK XL.

Whisper  – offline transcription via faster-whisper (VAD-buffered)
Vosk     – offline streaming transcription (lighter)
"""
import json
import numpy as np


def _setup_cuda_dlls() -> bool:
    """Put the pip-installed CUDA runtime DLLs (cublas/cudnn/cudart) on the
    Windows DLL search path so CTranslate2 can load them for GPU inference.

    Returns True if the CUDA libraries are present (≥ cublas + cudnn)."""
    import os
    try:
        import nvidia  # provided by nvidia-cublas-cu12 / nvidia-cudnn-cu12
        bases = list(nvidia.__path__)  # namespace package → __file__ is None, use __path__
    except Exception:
        return False
    found = []
    for base in bases:
        for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                found.append(d)
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")
    return len(found) >= 2


class WhisperSTT:
    """Offline transcription using faster-whisper (GPU if available, else CPU)."""

    def __init__(self, model_name: str = "base", language: str | None = None):
        import os
        from faster_whisper import WhisperModel
        print(f"[STT] Loading Whisper '{model_name}'…")

        self._language = None if (not language or language.strip().lower() == "auto") else language.strip().lower()

        # Bias the decoder toward Uzbek in LATIN script — large-v3 otherwise drifts to
        # Turkish or Cyrillic on low-resource Uzbek audio.  Only applied for language="uz".
        self._initial_prompt = (
            "Bu suhbat o'zbek tilida. Salom, men sizga qanday yordam bera olaman?"
            if self._language == "uz" else None
        )

        # Prefer GPU (CUDA) when the runtime libs are installed; fall back to CPU.
        # int8_float16 on GPU ≈ 1.3 GB VRAM for large-v3-turbo and is very fast.
        if _setup_cuda_dlls():
            attempts = [("cuda", "int8_float16"), ("cpu", "int8")]
        else:
            attempts = [("cpu", "int8")]

        self._model = None
        last_err = None
        for device, compute in attempts:
            try:
                self._model = WhisperModel(model_name, device=device, compute_type=compute)
                print(f"[STT] Whisper '{model_name}' ready ({device}/{compute})")
                break
            except Exception as err:
                last_err = err
                _e = str(err).lower()
                # Offline flag set but model not cached yet → download once, retry same device.
                if any(k in _e for k in ("offline", "not found", "cache", "localentry", "does not exist")):
                    print(f"[STT] '{model_name}' not cached — downloading (first run)…")
                    os.environ.pop("HF_HUB_OFFLINE",      None)
                    os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    os.environ.pop("HF_DATASETS_OFFLINE",  None)
                    try:
                        self._model = WhisperModel(model_name, device=device, compute_type=compute)
                        print(f"[STT] Whisper '{model_name}' ready ({device}/{compute})")
                        break
                    except Exception as err2:
                        last_err = err2
                else:
                    print(f"[STT] {device}/{compute} load failed: {str(err)[:120]}")
        if self._model is None:
            raise RuntimeError(f"Whisper failed to load: {last_err}")

        # Warm up: the first CUDA inference pays a one-time ~30 s cuDNN
        # autotuning cost.  Do it now (at load) so the user's first real
        # utterance is instant instead of stalling for half a minute.
        try:
            import numpy as _np
            _segs, _ = self._model.transcribe(_np.zeros(16_000, dtype=_np.float32), beam_size=5)
            for _ in _segs:
                pass
            print("[STT] warmup complete.")
        except Exception as _we:
            print(f"[STT] warmup skipped: {_we}")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 mono 16 kHz numpy array. Returns transcript string."""
        try:
            segments, _ = self._model.transcribe(
                audio,
                language=self._language,
                beam_size=5,                       # beam search — better accuracy (GPU is fast enough)
                best_of=5,
                condition_on_previous_text=False,  # no hallucinations
                initial_prompt=self._initial_prompt,  # bias toward Latin-script Uzbek
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[STT] Transcription error: {e}")
            raise


class ElevenLabsSTT:
    """Cloud speech-to-text via ElevenLabs Scribe (paid API key + internet required).

    Same interface as WhisperSTT — transcribe(np.ndarray) -> str — so it plugs into
    the existing mic → VAD → transcribe loop.  Uses no local GPU, freeing it for the LLM.
    """

    def __init__(self, api_key: str, language: str | None = None, model_id: str = "scribe_v2"):
        if not api_key:
            raise RuntimeError("ElevenLabs STT needs an API key — set 'elevenlabs_api_key' in config.")
        self._api_key  = api_key
        self._model_id = model_id
        self._language = None if (not language or language.strip().lower() == "auto") else language.strip().lower()
        self._url      = "https://api.elevenlabs.io/v1/speech-to-text"
        print(f"[STT] ElevenLabs Scribe ready (model={model_id}, lang={self._language or 'auto'}).")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe float32 mono 16 kHz audio via ElevenLabs Scribe. Returns text ('' on error)."""
        import io, wave, requests
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")  # float32 → 16-bit PCM
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16_000)
            w.writeframes(pcm16.tobytes())
        buf.seek(0)
        data = {"model_id": self._model_id, "tag_audio_events": "false"}  # don't transcribe noise/laughs
        if self._language:
            data["language_code"] = self._language
        try:
            r = requests.post(
                self._url,
                headers={"xi-api-key": self._api_key},
                data=data,
                files={"file": ("audio.wav", buf, "audio/wav")},
                timeout=30,
            )
            r.raise_for_status()
            text = (r.json().get("text") or "").strip()
            # Drop pure non-speech: strip any "[background noise]"/"(silence)" tags;
            # if nothing meaningful remains, return "" so the loop ignores it (no LLM reply to noise).
            import re
            cleaned = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", text).strip()
            return cleaned
        except Exception as e:
            print(f"[STT] ElevenLabs transcription error: {e}")
            return ""


class VoskSTT:
    """Streaming transcription using Vosk."""

    def __init__(self, model_path: str | None = None, language: str = "en-us"):
        from vosk import Model, KaldiRecognizer
        print("[STT] Loading Vosk model…")
        if model_path:
            model = Model(model_path)
        else:
            lang  = language.strip().lower() if language and language.strip().lower() != "auto" else "en-us"
            model = Model(lang=lang)
        self._rec = KaldiRecognizer(model, 16000)
        print("[STT] Vosk ready.")

    def process_chunk(self, audio_bytes: bytes) -> tuple[str, bool]:
        """Feed raw int16 LE PCM bytes. Returns (text, is_final)."""
        if self._rec.AcceptWaveform(audio_bytes):
            result = json.loads(self._rec.Result())
            return result.get("text", ""), True
        partial = json.loads(self._rec.PartialResult())
        return partial.get("partial", ""), False
