// AudioWorklet processor: runs on the audio rendering thread.
// It just forwards raw Float32 mic frames to the main thread via postMessage.
// Resampling (browser native rate -> 16kHz) and PCM16 encoding happen on the
// main thread in micCapture.js, since AudioWorkletGlobalScope has no access
// to OfflineAudioContext for resampling and keeping this processor minimal
// avoids doing heavy work on the realtime audio thread.
class MicCaptureProcessor extends AudioWorkletProcessor {
    process(inputs) {
      const input = inputs[0];
      if (input && input[0] && input[0].length > 0) {
        // Copy out of the reused buffer before posting.
        const channelData = input[0];
        const copy = new Float32Array(channelData.length);
        copy.set(channelData);
        this.port.postMessage(copy);
      }
      return true;
    }
  }
  
  registerProcessor('mic-capture-processor', MicCaptureProcessor);