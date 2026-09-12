// Stateful resampler. Carry the fractional source position across render quanta.
// Low-pass filtering before downsampling prevents high-frequency aliasing.
export class PcmPacketizer {
  constructor(sampleRate, emit, targetRate = 16000) {
    this.ratio = sampleRate / targetRate
    this.emit = emit
    this.input = []
    this.position = 0
    this.output = new Int16Array(320)
    this.count = 0
    this.sequence = 0
    this.offset = 0
    this.taps = 32
    const cutoff = Math.min(0.45, targetRate / sampleRate * 0.45)
    this.kernel = Array.from({ length: this.taps }, (_, i) => {
      const x = i - (this.taps - 1) / 2
      const sinc = Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x)
      return sinc * (0.54 - 0.46 * Math.cos(2 * Math.PI * i / (this.taps - 1)))
    })
    const sum = this.kernel.reduce((a, b) => a + b, 0)
    this.kernel = this.kernel.map((v) => v / sum)
    this.history = new Float32Array(this.taps)
    this.head = 0
  }

  push(samples) {
    for (const value of samples) {
      this.history[this.head] = value
      let filtered = 0
      for (let i = 0; i < this.taps; i++) filtered += this.kernel[i] * this.history[(this.head - i + this.taps) % this.taps]
      this.head = (this.head + 1) % this.taps
      this.input.push(filtered)
    }
    while (this.position + 1 < this.input.length) {
      const lo = Math.floor(this.position)
      const fraction = this.position - lo
      const value = this.input[lo] * (1 - fraction) + this.input[lo + 1] * fraction
      this.output[this.count++] = Math.round(Math.max(-1, Math.min(1, value)) * 32767)
      this.position += this.ratio
      if (this.count === this.output.length) this.flush()
    }
    const consumed = Math.min(Math.floor(this.position), this.input.length)
    this.input.splice(0, consumed)
    this.position -= consumed
  }

  flush() {
    if (!this.count) return
    const packet = new ArrayBuffer(652)
    const view = new DataView(packet)
    view.setUint32(0, this.sequence++, true)
    view.setFloat64(4, this.offset, true)
    for (let i = 0; i < this.count; i++) view.setInt16(12 + i * 2, this.output[i], true)
    this.offset += 320
    this.count = 0
    this.emit(packet)
  }
}
