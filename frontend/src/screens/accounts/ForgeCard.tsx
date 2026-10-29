import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  CircleCheck,
  CircleHelp,
  CircleX,
  Copy,
  Eye,
  EyeOff,
  ExternalLink as ExternalIcon,
  KeyRound,
  LoaderCircle,
  LogOut,
  RefreshCw,
  Server,
  Terminal,
  TriangleAlert,
  Unplug,
  WifiOff,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { ApiError, ServerDownError, api, queryKeys } from '@/api/client'
import type {
  Access,
  Account,
  AccountConnection,
  AccountList,
  ConnectMethod,
  ForgeStatus,
} from '@/api/types'
import { Blade } from '@/components/Blade'
import { ExternalLink } from '@/components/ExternalLink'
import { ForgeLogo } from '@/components/ForgeLogo'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { browser, useAccountConnection } from '@/hooks/useAccounts'
import { useCopy } from '@/hooks/useCopy'
import { useOnline } from '@/hooks/useStatus'
import { formatDateTime, formatRelative, formatTime, fr } from '@/lib/format'
import { forgeLabel } from '@/lib/proposals'

/** Le texte d'une erreur de l'API, à montrer près de ce qui l'a provoquée. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof ServerDownError) return error.message
  return 'Erreur inattendue : réessayer.'
}

type AccessLook = { label: string; detail: string; variant: 'success' | 'warning' | 'inconclusive'; icon: LucideIcon }

/**
 * Ce que permet un token : un mot (avec icône) et une précision (MASTER : jamais la couleur seule).
 * `word` : « PR », « MR » sur GitLab, où un token en lecture (`read_api`) lit aussi les projets privés.
 */
function accessLook(access: Access, word: string, forge: Account['forge']): AccessLook {
  switch (access) {
    case 'write':
      return { label: `Lecture et ${word}`, detail: 'dépôts publics et privés', variant: 'success', icon: CircleCheck }
    case 'public':
      return { label: `Lecture et ${word}`, detail: 'dépôts publics seulement', variant: 'warning', icon: TriangleAlert }
    case 'read':
      return {
        label: 'Lecture seule',
        detail: forge === 'gitlab' ? `projets lisibles, aucune ${word}` : `dépôts publics, aucune ${word}`,
        variant: 'warning',
        icon: TriangleAlert,
      }
    default:
      return { label: 'Droits non vérifiés', detail: 'la forge ne les dit pas pour ce token', variant: 'inconclusive', icon: CircleHelp }
  }
}

const METHOD: Record<ConnectMethod, string> = {
  oauth: 'par autorisation (OAuth)',
  device: 'par un code (device flow)',
  token: 'par un token collé',
  gh: 'depuis GitHub CLI (gh)',
}

type Notice = {
  variant: 'success' | 'warning' | 'danger'
  title: string
  text: string
  /** La façon de se connecter à relancer (« Réessayer »). */
  retry?: ConnectMethod
}

/** L'issue d'une connexion finie ; rien pour une connexion annulée. */
function noticeOf(connection: AccountConnection, name: string): Notice | null {
  switch (connection.status) {
    case 'done':
      return { variant: 'success', title: `Connecté à ${name}`, text: `Compte @${connection.account?.login ?? ''}.` }
    case 'failed':
      return { variant: 'danger', title: 'Connexion impossible', text: connection.error ?? '', retry: connection.method }
    case 'expired':
      return { variant: 'warning', title: 'Connexion expirée', text: connection.error ?? '', retry: connection.method }
    default:
      return null
  }
}

const NOTICE_ICON: Record<Notice['variant'], LucideIcon> = {
  success: CircleCheck,
  warning: TriangleAlert,
  danger: CircleX,
}

/**
 * Une forge dont la connexion est prête (GitHub à E16, GitLab à E19) : son compte connecté au
 * service en ligne, ou les façons de s'y connecter ; le device flow en cours ; l'issue d'une
 * connexion ; et pour GitLab, ses instances auto-hébergées. Les tokens ne passent jamais par ici,
 * sauf celui que la personne colle (envoyé au serveur, jamais renvoyé).
 */
export function ForgeCard({
  status,
  keyring,
  returned,
  onForgetReturn,
}: {
  status: ForgeStatus
  keyring: string | null
  /** La connexion OAuth dont la forge vient de revenir (`?connexion=`). */
  returned: string | null
  onForgetReturn: () => void
}) {
  const { forge, name, account } = status
  const client = useQueryClient()
  const online = useOnline()
  const heading = useRef<HTMLHeadingElement>(null)
  const [followed, setFollowed] = useState<string | null>(() => status.connection?.id ?? returned)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [leaving, setLeaving] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const connection = useAccountConnection(followed)
  // Le retour d'OAuth (`?connexion=`) est donné à toutes les cartes : chacune ne suit que les siennes.
  const current = connection.data?.forge === forge ? connection.data : null
  const pending = current?.status === 'pending' ? current : null
  const ended = current && current.status !== 'pending' ? current : null
  const endedKey = ended ? `${ended.id}:${ended.status}` : null

  useEffect(() => {
    // Une connexion finie (device flow, retour d'OAuth) : le compte a pu changer.
    if (endedKey) void client.invalidateQueries({ queryKey: queryKeys.accounts })
  }, [endedKey, client])

  const blocked = !online
    ? fr(`Pas de réseau : ${name} est injoignable. Les comptes connectés restent.`)
    : keyring
      ? fr('Le trousseau du système est indisponible : aucun token ne peut être gardé.')
      : null

  function refresh() {
    void client.invalidateQueries({ queryKey: queryKeys.accounts })
  }

  function show(next: Notice | null) {
    setNotice(next)
    setFollowed(null)
    onForgetReturn()
    heading.current?.focus()
  }

  function connected(found: Account) {
    show({ variant: 'success', title: `Connecté à ${name}`, text: `Compte @${found.login}.` })
    refresh()
  }

  const oauth = useMutation({
    mutationFn: () => api.startOAuth(forge),
    onSuccess: (started) => {
      setLeaving(true)
      browser.go(started.authorize_url ?? '/comptes')
    },
  })
  const device = useMutation({
    mutationFn: () => api.startDevice(forge),
    onSuccess: (started) => {
      client.setQueryData(queryKeys.connection(started.id), started)
      setNotice(null)
      onForgetReturn()
      setFollowed(started.id)
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelConnection(id),
    onSuccess: (cancelled) => {
      client.setQueryData(queryKeys.connection(cancelled.id), cancelled)
      refresh()
      heading.current?.focus()
    },
  })
  const gh = useMutation({ mutationFn: () => api.connectGh(forge), onSuccess: connected })
  const verify = useMutation({
    mutationFn: () => api.verifyAccount(forge),
    onSuccess: (checked) => client.setQueryData<AccountList>(queryKeys.accounts, (list) => list && withChecked(list, checked)),
  })
  const disconnect = useMutation({
    mutationFn: () => api.disconnect(forge),
    onSuccess: (result) => {
      show({
        variant: result.revoked === false ? 'warning' : 'success',
        title: `Déconnecté de ${name}`,
        text: result.message,
      })
      refresh()
    },
  })

  // Les droits sont relus une fois à l'ouverture de l'écran : un token révoqué sur la forge se
  // voit tout de suite.
  const verifyNow = verify.mutate
  const verified = useRef(false)
  const canVerify = account !== null && online && !keyring
  useEffect(() => {
    if (canVerify && !verified.current) {
      verified.current = true
      verifyNow()
    }
  }, [canVerify, verifyNow])

  function start(method: ConnectMethod) {
    if (method === 'oauth') oauth.mutate()
    else device.mutate()
  }

  const shown = notice ?? (ended ? noticeOf(ended, name) : null)
  const reconnect: ConnectMethod | null = status.methods.includes('oauth')
    ? 'oauth'
    : status.methods.includes('device')
      ? 'device'
      : null
  const titleId = `${forge}-titre`

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-5 rounded-md border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 ref={heading} id={titleId} tabIndex={-1} className="flex items-center gap-2 text-lg focus:outline-none">
          <ForgeLogo forge={forge} className="size-6" />
          {name}
        </h2>
        {account ? (
          <Badge variant="success">
            <CircleCheck aria-hidden="true" />
            Connecté
          </Badge>
        ) : pending ? (
          <Badge variant="primary">
            <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
            Connexion en cours
          </Badge>
        ) : (
          <Badge variant="neutral">
            <Unplug aria-hidden="true" />
            Non connecté
          </Badge>
        )}
      </div>

      {shown && (
        <NoticeAlert
          notice={shown}
          blocked={blocked}
          onRetry={shown.retry ? () => start(shown.retry as ConnectMethod) : undefined}
          onClose={() => show(null)}
        />
      )}

      {pending?.method === 'device' ? (
        <DeviceFlow
          connection={pending}
          name={name}
          cancelling={cancel.isPending}
          onCancel={() => cancel.mutate(pending.id)}
        />
      ) : pending?.method === 'oauth' ? (
        <OAuthPending
          connection={pending}
          name={name}
          cancelling={cancel.isPending}
          onCancel={() => cancel.mutate(pending.id)}
        />
      ) : account ? (
        <ConnectedAccount
          account={account}
          name={name}
          word={status.request}
          verifying={verify.isPending}
          verifyError={verify.error}
          disconnecting={disconnect.isPending}
          disconnectError={disconnect.error}
          blocked={blocked}
          onVerify={() => verify.mutate()}
          onReconnect={reconnect ? () => start(reconnect) : undefined}
          onDisconnect={() => setConfirming(true)}
        />
      ) : (
        <ConnectOptions
          status={status}
          blocked={blocked}
          leaving={leaving || oauth.isPending}
          oauthError={oauth.error}
          deviceStarting={device.isPending}
          deviceError={device.error}
          ghPending={gh.isPending}
          ghError={gh.error}
          onOAuth={() => oauth.mutate()}
          onDevice={() => device.mutate()}
          onGh={() => gh.mutate()}
          onConnected={connected}
        />
      )}

      {account && (
        <ConfirmDialog
          open={confirming}
          title={`Se déconnecter de ${name} ?`}
          confirm="Se déconnecter"
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false)
            disconnect.mutate()
          }}
        >
          <p>{fr(`Le token du compte @${account.login} est effacé du trousseau de cet ordinateur.`)}</p>
          <p>{fr(REVOKE[account.method](name))}</p>
          <p>Les analyses déjà faites restent.</p>
        </ConfirmDialog>
      )}

      {status.self_hosted && <Instances status={status} blocked={blocked} />}
    </section>
  )
}

/** La liste des comptes, avec ``checked`` à la place du compte qu'il a relu (même forge, même hôte). */
function withChecked(list: AccountList, checked: Account): AccountList {
  return {
    ...list,
    forges: list.forges.map((f) => {
      if (f.forge !== checked.forge) return f
      if (f.host === checked.host) return { ...f, account: checked }
      return { ...f, instances: f.instances.map((other) => (other.host === checked.host ? checked : other)) }
    }),
  }
}

/**
 * Les instances auto-hébergées d'une forge (GitLab) : un compte par hôte, connecté par son adresse
 * et un token d'accès personnel (l'OAuth demanderait d'enregistrer forceupdate sur chaque instance).
 */
function Instances({ status, blocked }: { status: ForgeStatus; blocked: string | null }) {
  const client = useQueryClient()
  const id = useId()
  const [notice, setNotice] = useState<Notice | null>(null)
  return (
    <div className="flex flex-col gap-4 border-t border-border pt-4" role="group" aria-labelledby={`${id}-titre`}>
      <div className="flex flex-col gap-1">
        <h3 id={`${id}-titre`} className="flex items-center gap-2 text-base">
          <Server className="size-4 text-fg-muted" aria-hidden="true" />
          Instances auto-hébergées
        </h3>
        <p className="text-sm text-fg-muted">
          {fr(`Une instance ${status.name} de votre entreprise ou de votre équipe : son adresse et un token d'accès personnel.`)}
        </p>
      </div>
      {notice && <NoticeAlert notice={notice} blocked={blocked} onClose={() => setNotice(null)} />}
      {status.instances.length > 0 && (
        <ul className="flex flex-col gap-3">
          {status.instances.map((account) => (
            <li key={account.host}>
              <InstanceAccount account={account} status={status} blocked={blocked} onGone={setNotice} />
            </li>
          ))}
        </ul>
      )}
      <TokenForm
        status={status}
        blocked={blocked}
        instance
        onConnected={(account) => {
          setNotice({
            variant: 'success',
            title: `Connecté à ${forgeLabel(account.forge, account.host)}`,
            text: `Compte @${account.login}.`,
          })
          void client.invalidateQueries({ queryKey: queryKeys.accounts })
        }}
      />
    </div>
  )
}

/** Le compte d'une instance : comme celui du service en ligne, ses droits relus et sa déconnexion. */
function InstanceAccount({
  account,
  status,
  blocked,
  onGone,
}: {
  account: Account
  status: ForgeStatus
  blocked: string | null
  onGone: (notice: Notice) => void
}) {
  const client = useQueryClient()
  const online = useOnline()
  const [confirming, setConfirming] = useState(false)
  const name = forgeLabel(account.forge, account.host)
  const verify = useMutation({
    mutationFn: () => api.verifyAccount(account.forge, account.host),
    onSuccess: (checked) => client.setQueryData<AccountList>(queryKeys.accounts, (list) => list && withChecked(list, checked)),
  })
  const disconnect = useMutation({
    mutationFn: () => api.disconnect(account.forge, account.host),
    onSuccess: (result) => {
      onGone({ variant: 'success', title: `Déconnecté de ${name}`, text: result.message })
      void client.invalidateQueries({ queryKey: queryKeys.accounts })
    },
  })
  const verifyNow = verify.mutate
  const verified = useRef(false)
  useEffect(() => {
    if (online && !blocked && !verified.current) {
      verified.current = true
      verifyNow()
    }
  }, [online, blocked, verifyNow])
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-4">
      <h4 className="flex flex-wrap items-center gap-2 font-mono text-base break-all">
        {account.host}
        <Badge variant="success">
          <CircleCheck aria-hidden="true" />
          Connecté
        </Badge>
      </h4>
      <ConnectedAccount
        account={account}
        name={name}
        word={status.request}
        verifying={verify.isPending}
        verifyError={verify.error}
        disconnecting={disconnect.isPending}
        disconnectError={disconnect.error}
        blocked={blocked}
        onVerify={() => verify.mutate()}
        onDisconnect={() => setConfirming(true)}
      />
      <ConfirmDialog
        open={confirming}
        title={`Se déconnecter de ${name} ?`}
        confirm="Se déconnecter"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false)
          disconnect.mutate()
        }}
      >
        <p>{fr(`Le token du compte @${account.login} est effacé du trousseau de cet ordinateur.`)}</p>
        <p>{fr(REVOKE[account.method](name))}</p>
        <p>Les analyses déjà faites restent.</p>
      </ConfirmDialog>
    </div>
  )
}

const REVOKE: Record<ConnectMethod, (name: string) => string> = {
  oauth: (name) => `Il est aussi révoqué auprès de ${name}.`,
  device: (name) => `Il est aussi révoqué auprès de ${name}.`,
  token: (name) => `Ce token collé reste valable sur ${name} : le révoquer dans ses réglages si besoin.`,
  gh: () => 'gh reste connecté : son token n\'est pas révoqué.',
}

function NoticeAlert({
  notice,
  blocked,
  onRetry,
  onClose,
}: {
  notice: Notice
  blocked: string | null
  onRetry?: () => void
  onClose: () => void
}) {
  const Icon = NOTICE_ICON[notice.variant]
  return (
    <Alert variant={notice.variant} role={notice.variant === 'danger' ? 'alert' : 'status'}>
      <Icon aria-hidden="true" />
      <AlertTitle>{notice.title}</AlertTitle>
      <AlertDescription>
        <p>{notice.text}</p>
      </AlertDescription>
      <AlertActions>
        {onRetry && (
          <Button size="sm" onClick={onRetry} disabled={blocked !== null}>
            Réessayer
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onClose}>
          Fermer
        </Button>
      </AlertActions>
    </Alert>
  )
}

function ConnectedAccount({
  account,
  name,
  word,
  verifying,
  verifyError,
  disconnecting,
  disconnectError,
  blocked,
  onVerify,
  onReconnect,
  onDisconnect,
}: {
  account: Account
  name: string
  /** « PR », « MR » sur GitLab. */
  word: string
  verifying: boolean
  verifyError: Error | null
  disconnecting: boolean
  disconnectError: Error | null
  blocked: string | null
  onVerify: () => void
  /** Se reconnecter (OAuth, device flow) ; absent : coller un nouveau token. */
  onReconnect?: () => void
  onDisconnect: () => void
}) {
  const access = accessLook(account.access, word, account.forge)
  const AccessIcon = access.icon
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <span className="font-mono text-base">
          <ExternalLink href={account.url}>@{account.login}</ExternalLink>
        </span>
        {account.name && <span className="text-sm text-fg-muted">{account.name}</span>}
      </div>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr] sm:gap-y-2">
        <dt className="text-fg-muted">Droits</dt>
        <dd className="mb-2 flex flex-wrap items-center gap-2 sm:mb-0">
          <Badge variant={access.variant}>
            <AccessIcon aria-hidden="true" />
            {access.label}
          </Badge>
          <span className="text-fg-muted">{access.detail}</span>
        </dd>
        <dt className="text-fg-muted">Portées</dt>
        <dd className="mb-2 flex flex-wrap items-center gap-1.5 sm:mb-0">
          {account.scopes === null ? (
            <span className="text-fg-muted">
              {account.forge === 'github' ? 'non données par la forge (token fine-grained)' : 'non données par la forge'}
            </span>
          ) : account.scopes.length === 0 ? (
            <span className="text-fg-muted">aucune</span>
          ) : (
            account.scopes.map((scope) => (
              <Badge key={scope} variant="outline" mono>
                {scope}
              </Badge>
            ))
          )}
        </dd>
        <dt className="text-fg-muted">Connecté le</dt>
        <dd className="mb-2 sm:mb-0">
          {formatDateTime(account.connected_at)}, {METHOD[account.method]}
        </dd>
        <dt className="text-fg-muted">Vérifié</dt>
        <dd>{verifying ? 'vérification…' : formatRelative(account.checked_at)}</dd>
      </dl>

      {account.problem && (
        <Alert variant="danger" role="alert">
          <CircleX aria-hidden="true" />
          <AlertTitle>{fr(`${name} refuse le token`)}</AlertTitle>
          <AlertDescription>
            <p>{account.problem}</p>
          </AlertDescription>
          {onReconnect ? (
            <AlertActions>
              <Button size="sm" variant="primary" onClick={onReconnect} disabled={blocked !== null}>
                Se reconnecter
              </Button>
            </AlertActions>
          ) : (
            <p className="text-sm">{fr('Se déconnecter, puis coller un nouveau token.')}</p>
          )}
        </Alert>
      )}

      {verifyError && (
        <Alert variant="warning" role="status">
          <WifiOff aria-hidden="true" />
          <AlertTitle>Droits non revérifiés</AlertTitle>
          <AlertDescription>
            <p>{errorText(verifyError)}</p>
          </AlertDescription>
        </Alert>
      )}

      {account.warnings.length > 0 && (
        <Alert variant={account.access === 'unknown' ? 'inconclusive' : 'warning'} role="status">
          {account.access === 'unknown' ? <CircleHelp aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
          <AlertTitle>À savoir sur ces droits</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-5">
              {account.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {disconnectError && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {errorText(disconnectError)}
        </p>
      )}

      <div className="flex flex-wrap gap-2 max-sm:*:w-full">
        <Button onClick={onVerify} disabled={verifying || blocked !== null}>
          {verifying ? (
            <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          Vérifier les droits
        </Button>
        <Button variant="danger" onClick={onDisconnect} disabled={disconnecting}>
          {disconnecting ? (
            <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
          ) : (
            <LogOut aria-hidden="true" />
          )}
          Se déconnecter…
        </Button>
      </div>
    </div>
  )
}

function ConnectOptions({
  status,
  blocked,
  leaving,
  oauthError,
  deviceStarting,
  deviceError,
  ghPending,
  ghError,
  onOAuth,
  onDevice,
  onGh,
  onConnected,
}: {
  status: ForgeStatus
  blocked: string | null
  leaving: boolean
  oauthError: Error | null
  deviceStarting: boolean
  deviceError: Error | null
  ghPending: boolean
  ghError: Error | null
  onOAuth: () => void
  onDevice: () => void
  onGh: () => void
  onConnected: (account: Account) => void
}) {
  const { forge, name, methods } = status
  const withOAuth = methods.includes('oauth')
  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm">
        {fr(`Lire vos dépôts, publics et privés, et y ouvrir des ${status.request}. ${status.scopes.length >= 2 ? 'Portées demandées' : 'Portée demandée'} : `)}
        {status.scopes.map((scope, index) => (
          <span key={scope}>
            {index > 0 && ', '}
            <code>{scope}</code>
          </span>
        ))}
        .
      </p>

      {blocked && (
        <p role="status" className="flex items-start gap-2 text-sm text-warning">
          <WifiOff className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {blocked}
        </p>
      )}

      {withOAuth && (
        <div className="flex flex-col items-start gap-2">
          <Button variant="primary" onClick={onOAuth} disabled={blocked !== null || leaving} className="max-sm:w-full">
            {leaving ? (
              <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <ForgeLogo forge={forge} className="size-4" />
            )}
            {leaving ? `Ouverture de ${name}…` : `Se connecter avec ${name}`}
          </Button>
          <p className="text-sm text-fg-muted">{fr(`${name} demande d'autoriser forceupdate, puis revient ici.`)}</p>
          <FieldError error={oauthError} />
        </div>
      )}

      <div className="flex flex-col gap-1 border-t border-border pt-4">
        <h3 className="text-base">{withOAuth ? 'Autres façons de se connecter' : 'Se connecter'}</h3>
        <ul className="flex flex-col divide-y divide-border">
          {methods.includes('device') && (
            <OptionRow
              title="Avec un code"
              text={fr(`Un code à taper sur ${status.host} : quand le retour vers cet ordinateur ne marche pas.`)}
              error={deviceError}
              action={
                <Button
                  variant={withOAuth ? 'secondary' : 'primary'}
                  onClick={onDevice}
                  disabled={blocked !== null || deviceStarting}
                >
                  {deviceStarting ? (
                    <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
                  ) : (
                    <KeyRound aria-hidden="true" />
                  )}
                  Se connecter avec un code
                </Button>
              }
            />
          )}
          {methods.includes('gh') && (
            <OptionRow
              title="Avec GitHub CLI"
              text={fr('gh est installé sur cet ordinateur : reprendre le compte avec lequel il est connecté.')}
              error={ghError}
              action={
                <Button onClick={onGh} disabled={blocked !== null || ghPending}>
                  {ghPending ? (
                    <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
                  ) : (
                    <Terminal aria-hidden="true" />
                  )}
                  Reprendre le compte de gh
                </Button>
              }
            />
          )}
          {methods.includes('token') && (
            <li className="py-3">
              <TokenForm status={status} blocked={blocked} onConnected={onConnected} />
            </li>
          )}
          {methods.includes('token') && methods.length === 1 && (
            <li className="py-3 text-sm text-fg-muted">
              {fr(`La connexion par ${status.host} n'est pas prête ici : coller un token.`)}
            </li>
          )}
        </ul>
      </div>
    </div>
  )
}

function OptionRow({
  title,
  text,
  action,
  error,
}: {
  title: string
  text: string
  action: ReactNode
  error: Error | null
}) {
  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 basis-64 flex-col gap-0.5">
          <span className="font-medium">{title}</span>
          <span className="text-sm text-fg-muted">{text}</span>
        </div>
        <div className="max-sm:w-full max-sm:*:w-full">{action}</div>
      </div>
      <FieldError error={error} />
    </li>
  )
}

function FieldError({ error, id }: { error: Error | null; id?: string }) {
  if (!error) return null
  return (
    <p id={id} role="alert" className="flex items-start gap-2 text-sm text-danger">
      <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {errorText(error)}
    </p>
  )
}

/** L'adresse d'une instance tapée par la personne, si elle en a la forme (`https://hôte`). */
function instanceHost(url: string): string | null {
  const text = url.trim()
  if (!text) return null
  try {
    const parsed = new URL(text.includes('://') ? text : `https://${text}`)
    return parsed.protocol === 'https:' && parsed.hostname.includes('.') ? parsed.host : null
  } catch {
    return null
  }
}

/**
 * Un token collé : envoyé au serveur, qui le vérifie auprès de la forge ; effacé du champ ensuite.
 * `instance` : pour une instance auto-hébergée, son adresse en plus.
 */
function TokenForm({
  status,
  blocked,
  instance = false,
  onConnected,
}: {
  status: ForgeStatus
  blocked: string | null
  instance?: boolean
  onConnected: (account: Account) => void
}) {
  const id = useId()
  const [value, setValue] = useState('')
  const [url, setUrl] = useState('')
  const [visible, setVisible] = useState(false)
  const connect = useMutation({
    mutationFn: (token: string) => api.connectToken(status.forge, token, instance ? url.trim() : null),
    onSuccess: (account) => {
      setValue('')
      setUrl('')
      onConnected(account)
    },
  })
  const described = [`${id}-aide`, connect.error ? `${id}-erreur` : null].filter(Boolean).join(' ')
  const host = instance ? instanceHost(url) : status.host
  const tokenUrl = instance
    ? host && `https://${host}/-/user_settings/personal_access_tokens?name=forceupdate&scopes=api`
    : status.token_url
  const ready = value.trim() !== '' && (!instance || url.trim() !== '')

  return (
    <form
      className="flex flex-col gap-2"
      aria-label={instance ? `Connecter une instance ${status.name}` : undefined}
      onSubmit={(event) => {
        event.preventDefault()
        if (ready) connect.mutate(value)
      }}
    >
      {instance && (
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-adresse`} className="font-medium">
            {`Adresse de l'instance`}
          </label>
          <Input
            id={`${id}-adresse`}
            type="url"
            inputMode="url"
            mono
            autoComplete="url"
            placeholder="https://gitlab.example.com"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            aria-describedby={`${id}-aide`}
            disabled={connect.isPending}
          />
        </div>
      )}
      <label htmlFor={id} className="font-medium">
        {instance ? `Token de l'instance` : `Token ${status.name}`}
      </label>
      {/* Un lien dans une phrase se distingue autrement que par sa couleur : souligné. */}
      <p id={`${id}-aide`} className="text-sm text-fg-muted [&_a]:underline">
        {status.forge === 'github' ? fr('Un token classic avec les portées ') : fr("Un token d'accès personnel avec la portée ")}
        {status.scopes.map((scope, index) => (
          <span key={scope}>
            {index > 0 && ' et '}
            <code>{scope}</code>
          </span>
        ))}
        {status.forge === 'github'
          ? fr(', ou un token fine-grained (ses droits ne se vérifient pas). ')
          : instance
            ? fr(', créé sur l\'instance (https seulement : le token ne part jamais en clair). ')
            : '. '}
        {tokenUrl && <ExternalLink href={tokenUrl}>{`Créer un token sur ${host}`}</ExternalLink>}
      </p>
      <div className="flex flex-wrap gap-2">
        <div className="flex min-w-0 flex-1 basis-64 gap-2">
          <Input
            id={id}
            type={visible ? 'text' : 'password'}
            mono
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            aria-describedby={described}
            aria-invalid={connect.error ? true : undefined}
            disabled={connect.isPending}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label="Afficher le token"
            aria-pressed={visible}
            aria-controls={id}
            onClick={() => setVisible((shown) => !shown)}
          >
            {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          </Button>
        </div>
        <Button type="submit" disabled={blocked !== null || connect.isPending || !ready} className="max-sm:w-full">
          {connect.isPending ? (
            <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
          ) : (
            <KeyRound aria-hidden="true" />
          )}
          {instance ? "Connecter l'instance" : 'Connecter avec ce token'}
        </Button>
      </div>
      <FieldError id={`${id}-erreur`} error={connect.error} />
    </form>
  )
}

/** Le device flow en cours : le code en grand, « Copier », le lien vers la forge, l'attente. */
function DeviceFlow({
  connection,
  name,
  cancelling,
  onCancel,
}: {
  connection: AccountConnection
  name: string
  cancelling: boolean
  onCancel: () => void
}) {
  const code = connection.user_code ?? ''
  const { copied, said, copy } = useCopy(code, 'Code copié.')
  const where = connection.verification_uri ?? ''
  const shortWhere = where.replace(/^https?:\/\//, '')
  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-base">Se connecter avec un code</h3>
      <ol className="flex list-decimal flex-col gap-4 pl-5 text-sm marker:text-fg-muted">
        <li>
          <span>Copier ce code :</span>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <code className="rounded-sm border border-border bg-surface-2 px-4 py-2 text-[30px] leading-tight font-semibold tracking-[0.12em] tabular-nums">
              {code}
            </code>
            <Button onClick={() => void copy()} aria-label={copied ? 'Copié' : 'Copier le code'}>
              {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
              {copied ? 'Copié' : 'Copier'}
            </Button>
            <span className="sr-only" aria-live="polite">
              {said}
            </span>
          </div>
        </li>
        <li>
          {/* Le `flex` sur un div : sur le `li`, il effacerait son numéro. */}
          <div className="flex flex-col items-start gap-2">
            <span>{fr(`Le saisir sur ${shortWhere}, puis autoriser forceupdate :`)}</span>
            <a
              href={where}
              target="_blank"
              rel="noreferrer"
              aria-label={`Ouvrir ${shortWhere} (nouvel onglet)`}
              className={buttonVariants({ variant: 'primary', className: 'max-sm:w-full' })}
            >
              {`Ouvrir ${shortWhere}`}
              <ExternalIcon aria-hidden="true" />
            </a>
          </div>
        </li>
      </ol>
      <div className="flex flex-col gap-2">
        <Blade label={`En attente de l'autorisation sur ${name}`} />
        <p role="status" className="text-sm text-fg-muted">
          {fr(`En attente de l'autorisation sur ${name}… Le code expire à ${formatTime(connection.expires_at)}.`)}
        </p>
      </div>
      <div>
        <Button onClick={onCancel} disabled={cancelling} className="max-sm:w-full">
          Annuler
        </Button>
      </div>
    </div>
  )
}

/** Une autorisation OAuth commencée, pas revenue (retour arrière du navigateur depuis la forge). */
function OAuthPending({
  connection,
  name,
  cancelling,
  onCancel,
}: {
  connection: AccountConnection
  name: string
  cancelling: boolean
  onCancel: () => void
}) {
  return (
    <Alert variant="info" role="status">
      <LoaderCircle aria-hidden="true" />
      <AlertTitle>{`Connexion en cours sur ${name}`}</AlertTitle>
      <AlertDescription>
        <p>
          {fr(
            `Autoriser forceupdate sur la page de ${name}, qui revient ici ensuite. La demande expire à ${formatTime(connection.expires_at)}.`,
          )}
        </p>
      </AlertDescription>
      <AlertActions>
        {connection.authorize_url && (
          <a href={connection.authorize_url} className={buttonVariants({ variant: 'primary', size: 'sm' })}>
            {`Continuer sur ${name}`}
          </a>
        )}
        <Button size="sm" onClick={onCancel} disabled={cancelling}>
          Annuler
        </Button>
      </AlertActions>
    </Alert>
  )
}
