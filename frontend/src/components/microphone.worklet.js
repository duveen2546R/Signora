/* global AudioWorkletProcessor, registerProcessor, sampleRate */
import { PcmPacketizer } from './audioPcm.js'

class SignSureMicrophone extends AudioWorkletProcessor {
  constructor() {
    super()
    this.stopped = false
    this.packetizer = new PcmPacketizer(sampleRate, (packet) => this.port.postMessage(packet, [packet]))
    this.port.onmessage = () => {
      this.stopped = true
      this.packetizer.flush()
      this.port.postMessage({ stopped: true })
    }
  }

  process(inputs) {
    if (!this.stopped && inputs[0]?.[0]) this.packetizer.push(inputs[0][0])
    return !this.stopped
  }
}

registerProcessor('signsure-microphone', SignSureMicrophone)
