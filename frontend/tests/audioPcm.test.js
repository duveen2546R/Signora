import test from 'node:test'
import assert from 'node:assert/strict'
import { PcmPacketizer } from '../src/components/audioPcm.js'

test('44.1/48 kHz input produces bounded, contiguous 16 kHz little-endian packets', () => {
  for (const rate of [44100, 48000]) {
    const packets = []
    const encoder = new PcmPacketizer(rate, (packet) => packets.push(packet))
    for (let offset = 0; offset < rate * 5; offset += 128) {
      encoder.push(new Float32Array(Math.min(128, rate * 5 - offset)).fill(0.5))
    }
    encoder.flush()
    assert.equal(packets.length, 250)
    packets.forEach((packet, index) => {
      assert.equal(packet.byteLength, 652)
      const view = new DataView(packet)
      assert.equal(view.getUint32(0, true), index)
      assert.equal(view.getFloat64(4, true), index * 320)
    })
    assert.ok(encoder.input.length < 4)
    assert.ok(Math.abs(new DataView(packets[1]).getInt16(12, true) - 16384) < 3)
  }
})

test('stop flush pads at most one packet; a second flush never duplicates it', () => {
  const packets = []
  const encoder = new PcmPacketizer(48000, (packet) => packets.push(packet))
  encoder.push(new Float32Array(128))
  encoder.flush()
  encoder.flush()
  assert.equal(packets.length, 1)
})
