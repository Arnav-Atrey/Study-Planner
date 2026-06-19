// Plays back the 24kHz PCM16 audio chunks Gemini Live streams down.
//
// We schedule each incoming chunk back-to-back on the AudioContext timeline
// (gapless playback) rather than firing them as soon as they arrive, which
// would cause overlapping/garbled audio. On interruption (user barges in),
// we stop everything scheduled and reset the timeline immediately.

const PLAYBACK_SAMPLE_RATE = 24000;

function pcm16ToFloat32(arrayBuffer) {
  const int16 = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i += 1) {
    float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff);
  }
  return float32;
}

export class AudioPlayback {
  constructor() {
    this.audioContext = null;
    this._nextStartTime = 0;
    this._activeSources = new Set();
  }

  start() {
    this.audioContext = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE });
    this._nextStartTime = this.audioContext.currentTime;
  }

  enqueueChunk(arrayBuffer) {
    if (!this.audioContext) return;

    const float32 = pcm16ToFloat32(arrayBuffer);
    const buffer = this.audioContext.createBuffer(1, float32.length, PLAYBACK_SAMPLE_RATE);
    buffer.copyToChannel(float32, 0);

    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);

    const now = this.audioContext.currentTime;
    const startTime = Math.max(this._nextStartTime, now);
    source.start(startTime);
    this._nextStartTime = startTime + buffer.duration;

    this._activeSources.add(source);
    source.onended = () => this._activeSources.delete(source);
  }

  /** Immediately stop everything queued/playing — used when the user interrupts. */
  flush() {
    this._activeSources.forEach((source) => {
      try {
        source.stop();
      } catch {
        // already stopped/ended — ignore
      }
    });
    this._activeSources.clear();
    if (this.audioContext) {
      this._nextStartTime = this.audioContext.currentTime;
    }
  }

  stop() {
    this.flush();
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
  }
}