/**
 * Les types de l'API, tirés de src/api/schema.d.ts, lui-même généré depuis
 * src/forceupdate/web/openapi.json (`npm run gen:api`). Ne rien écrire à la main ici qui ne
 * vienne du schéma.
 */
import type { components, operations } from './schema'

type Schemas = components['schemas']

/** Le corps JSON de la réponse `status` de l'opération `op` (son operationId). */
export type Response<Op extends keyof operations, Status extends number = 200> =
  operations[Op]['responses'] extends Record<Status, { content: { 'application/json': infer Body } }>
    ? Body
    : never

export type Listing = Response<'list_folder'>
export type Entry = Schemas['Entry']
export type EntryKind = Schemas['EntryKind']
export type RecentPath = Schemas['RecentPath']

export type ScanRequest = Schemas['ScanRequest']
export type ScanSummary = Response<'start_scan', 202>
export type ScanDetail = Response<'get_scan'>
export type ScanOptions = Schemas['ScanOptions']
export type SourceKind = Schemas['SourceKind']
export type TaskStatus = Schemas['TaskStatus']
export type ScanEvent = Schemas['Event']
export type EventKind = Schemas['EventKind']

export type Report = Schemas['Document']
export type Summary = Schemas['SummaryDocument']
export type Language = Schemas['Language']
export type Project = Schemas['Project']
export type Dependency = Schemas['Dependency']
export type Finding = Schemas['Finding']
export type Update = Schemas['Update']
export type UpdateOption = Schemas['UpdateOption']
export type UpdateReason = Schemas['UpdateReason']
export type Edit = Schemas['Edit']
export type Notice = Schemas['Notice']
export type Ecosystem = Schemas['Ecosystem']
export type Severity = Schemas['Severity']
export type FindingKind = Schemas['FindingKind']
export type Gap = Schemas['Gap']
export type Scope = Schemas['Scope']

export type PlanRequest = Schemas['PlanRequest']
export type ApplyRequest = Schemas['ApplyRequest']
export type UpdatePlan = Response<'plan_update', 201>
/** Une sélection : `{id de la mise à jour: version}`. */
export type Selection = PlanRequest['selection']
export type Chosen = Schemas['Chosen']
export type SkippedOption = Schemas['SkippedOption']
export type FileDiff = Schemas['FileDiff']
export type LockJob = Schemas['LockJob']
export type LockResult = Schemas['LockResult']
export type LockStatus = Schemas['LockStatus']
export type InstalledVersion = Schemas['InstalledVersion']
export type Reach = Schemas['Reach']

export type AccountList = Response<'list_accounts'>
export type ForgeStatus = Schemas['ForgeStatus']
export type ForgeKind = Schemas['ForgeKind']
export type Account = Response<'connect_token', 201>
export type Access = Schemas['Access']
export type ConnectMethod = Schemas['ConnectMethod']
export type AccountConnection = Response<'start_device', 201>
export type ConnectionStatus = Schemas['ConnectionStatus']
export type Disconnection = Response<'disconnect'>

export type RepositoryList = Response<'list_repositories'>
export type RepositoryRow = Schemas['RepositoryRow']
export type RepositoryAccount = Schemas['RepositoryAccount']
export type RepositorySynthesis = Schemas['RepositorySynthesis']
export type RepositoryState = Schemas['RepositoryState']
export type RepositoryCounts = Schemas['RepositoryCounts']
export type RepositoryBatch = Response<'start_batch', 202>
export type BatchStatus = Schemas['BatchStatus']
export type RepositoryRef = Schemas['RepositoryRef']
export type Restriction = Schemas['Restriction']
export type RateLimit = Schemas['RateLimit']
export type BatchRequest = Schemas['BatchRequest']
export type RepositoryRequest = Schemas['RepositoryRequest']

export type ProposalRequest = Schemas['ProposalRequest']
export type ProposedSelection = Schemas['ProposedSelection']
export type SendRequest = Schemas['SendRequest']
export type Proposal = Response<'create_proposal', 201>
export type ProposedRepository = Schemas['ProposedRepository']
export type ProposedUpdate = Schemas['ProposedUpdate']
export type ProposedSkip = Schemas['ProposedSkip']
export type ProposedState = Schemas['ProposedState']
export type ProposalStatus = Schemas['ProposalStatus']
export type ChangeRequest = Schemas['ChangeRequest']
export type Step = Schemas['Step']
