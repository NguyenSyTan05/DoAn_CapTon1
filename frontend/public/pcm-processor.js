/**
 * ClassBridge PCM Processor (AudioWorklet)
 *
 * Nhận audio float32 từ AudioContext (44.1 / 48 kHz / 16 kHz),
 * lọc thông thấp Butterworth bậc 4 chống răng cưa (khi sampleRate != 16 kHz)
 * và downsample về 16 kHz mono bằng nội suy tuyến tính có trạng thái liên tục qua các khối.
 *
 * Gửi từng block chuẩn 100ms (1600 mẫu float32) về main thread qua postMessage.
 * Output: PCM Float32 LE, 16.000 Hz, mono.
 */
function createLowpassBiquad(fc, fs, Q) {
  const w0 = (2 * Math.PI * fc) / fs;
  const cosw0 = Math.cos(w0);
  const sinw0 = Math.sin(w0);
  const alpha = sinw0 / (2 * Q);
  const a0 = 1 + alpha;
  return {
    b0: (1 - cosw0) / 2 / a0,
    b1: (1 - cosw0) / a0,
    b2: (1 - cosw0) / 2 / a0,
    a1: (-2 * cosw0) / a0,
    a2: (1 - alpha) / a0,
    x1: 0.0,
    x2: 0.0,
    y1: 0.0,
    y2: 0.0,
  };
}

function processBiquad(bq, x) {
  const y =
    bq.b0 * x +
    bq.b1 * bq.x1 +
    bq.b2 * bq.x2 -
    bq.a1 * bq.y1 -
    bq.a2 * bq.y2;
  bq.x2 = bq.x1;
  bq.x1 = x;
  bq.y2 = bq.y1;
  bq.y1 = y;
  return y;
}

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.bufferSize = 1600; // Chuẩn 100ms mono PCM tại 16 kHz
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
    this.prev = 0.0;
    this.t = 1.0;
    this.filterRate = 0;
    this.biquads = [];
    this.port.postMessage({ type: "pcm_processor_ready" });
  }

  ensureFilters(inRate) {
    if (this.filterRate === inRate) return;
    this.filterRate = inRate;
    const fc = Math.min(7000, 0.45 * inRate);
    this.biquads = [
      createLowpassBiquad(fc, inRate, 0.5412),
      createLowpassBiquad(fc, inRate, 1.3066),
    ];
  }

  pushSample(sample) {
    if (!Number.isFinite(sample)) sample = 0;
    if (sample > 1.0) sample = 1.0;
    else if (sample < -1.0) sample = -1.0;

    this.buffer[this.bufferIndex++] = sample;
    if (this.bufferIndex >= this.bufferSize) {
      const copy = new Float32Array(this.buffer);
      this.port.postMessage(
        { type: "pcm_data", buffer: copy.buffer, sampleRate: this.targetSampleRate },
        [copy.buffer],
      );
      this.bufferIndex = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const inputChannel = input[0];
    const len = inputChannel.length;
    if (len === 0) return true;

    const inRate =
      typeof sampleRate === "number" && sampleRate > 0 ? sampleRate : 48000;

    // Trường hợp 1: AudioContext chạy native ở 16kHz
    if (Math.abs(inRate - this.targetSampleRate) < 1) {
      for (let i = 0; i < len; i++) {
        this.pushSample(inputChannel[i]);
      }
      return true;
    }

    // Trường hợp 2: Lọc thông thấp Butterworth bậc 4 + nội suy tuyến tính giữ trạng thái liên khối
    this.ensureFilters(inRate);
    const ratio = inRate / this.targetSampleRate;
    for (let i = 0; i < len; i++) {
      let y = inputChannel[i];
      if (!Number.isFinite(y)) y = 0.0;
      for (let b = 0; b < this.biquads.length; b++) {
        y = processBiquad(this.biquads[b], y);
      }
      while (this.t <= 1.0) {
        this.pushSample(this.prev + (y - this.prev) * this.t);
        this.t += ratio;
      }
      this.t -= 1.0;
      this.prev = y;
    }
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
