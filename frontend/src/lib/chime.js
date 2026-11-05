// A short two-note chime for live alerts, synthesised with Web Audio so there is no sound file to load. Browsers
// keep audio muted until the person has interacted with the page; until then this stays silent and the toast alone
// does the job.
let audio = null

export function chime() {
  try {
    audio ??= new (window.AudioContext || window.webkitAudioContext)()
    if (audio.state === 'suspended') audio.resume().catch(() => {})
    const start = audio.currentTime
    ;[880, 1318.5].forEach((frequency, index) => {
      const at = start + index * 0.13
      const oscillator = audio.createOscillator()
      const gain = audio.createGain()
      oscillator.type = 'sine'
      oscillator.frequency.value = frequency
      gain.gain.setValueAtTime(0.0001, at)
      gain.gain.exponentialRampToValueAtTime(0.12, at + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.28)
      oscillator.connect(gain).connect(audio.destination)
      oscillator.start(at)
      oscillator.stop(at + 0.3)
    })
  } catch {
    // No Web Audio: the toast still shows.
  }
}
