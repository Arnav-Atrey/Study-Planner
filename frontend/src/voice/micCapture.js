// Captures microphone audio, resamples it to 16kHz mono, and encodes to
// 16-bit PCM — the exact format Gemini Live expects for realtime audio input.
//
// Browsers virtually always run their AudioContext at 44.1kHz or 48kHz, not
// 16kHz, so we can't just read worklet frames and ship them as-is. We
// linearly resample on the main thread (cheap enough for mono speech audio)
// before handing PCM16 bytes to the caller.

function floatTo16BitPCM(float32Array) {
    const out = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i += 1) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }
  
  function resampleLinear(float32Array, fromRate, toRate) {
    if (fromRate === toRate) return float32Array;
    const ratio = fromRate / toRate;
    const newLength = Math.round(float32Array.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i += 1) {
      const srcIndex = i * ratio;
      const lower = Math.floor(srcIndex);
      const upper = Math.min(lower + 1, float32Array.length - 1);
      const frac = srcIndex - lower;
      result[i] = float32Array[lower] * (1 - frac) + float32Array[upper] * frac;
    }
    return result;
  }
  
  const TARGET_SAMPLE_RATE = 16000;
  
  export class MicCapture {
    constructor({ onChunk }) {
      this.onChunk = onChunk;
      this.audioContext = null;
      this.workletNode = null;
      this.sourceNode = null;
      this.stream = null;
      this._leftover = new Float32Array(0);
    }
  
    async start() {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
  
      this.audioContext = new AudioContext();
      await this.audioContext.audioWorklet.addModule('/mic-capture-worklet.js');
  
      this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
      this.workletNode = new AudioWorkletNode(this.audioContext, 'mic-capture-processor');
  
      this.workletNode.port.onmessage = (event) => {
        this._handleFrames(event.data);
      };
  
      this.sourceNode.connect(this.workletNode);
      // Not connecting workletNode to destination — we don't want mic
      // monitoring/echo played back through the speakers.
    }
  
    _handleFrames(float32Array) {
      const nativeRate = this.audioContext.sampleRate;
      const resampled = resampleLinear(float32Array, nativeRate, TARGET_SAMPLE_RATE);
  
      // Concatenate any leftover samples from the previous frame so chunk
      // boundaries don't introduce clicks/gaps.
      const combined = new Float32Array(this._leftover.length + resampled.length);
      combined.set(this._leftover, 0);
      combined.set(resampled, this._leftover.length);
  
      const pcm16 = floatTo16BitPCM(combined);
      this._leftover = new Float32Array(0);
  
      if (this.onChunk) {
        this.onChunk(pcm16.buffer);
      }
    }
  
    stop() {
      if (this.workletNode) {
        this.workletNode.port.onmessage = null;
        this.workletNode.disconnect();
        this.workletNode = null;
      }
      if (this.sourceNode) {
        this.sourceNode.disconnect();
        this.sourceNode = null;
      }
      if (this.stream) {
        this.stream.getTracks().forEach((track) => track.stop());
        this.stream = null;
      }
      if (this.audioContext) {
        this.audioContext.close();
        this.audioContext = null;
      }
    }
  }