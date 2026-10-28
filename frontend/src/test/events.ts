/** Un `EventSource` simulé : les tests poussent les événements du serveur à la main. */
export class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = []

  static reset() {
    FakeEventSource.instances = []
  }

  /** Le dernier ouvert sur `url`. */
  static last(url?: string): FakeEventSource {
    const found = FakeEventSource.instances.filter((source) => !url || source.url === url)
    const source = found.at(-1)
    if (!source) throw new Error(`aucun EventSource ouvert${url ? ` sur ${url}` : ''}`)
    return source
  }

  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2

  readonly url: string
  readyState = FakeEventSource.OPEN
  closed = false

  constructor(url: string | URL) {
    super()
    this.url = String(url)
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }

  /** Le serveur envoie `event: type` avec `data` (en JSON). */
  emit(type: string, data: unknown) {
    if (this.closed) return
    this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }))
  }

  /** La connexion se coupe. */
  fail() {
    this.dispatchEvent(new Event('error'))
  }
}
